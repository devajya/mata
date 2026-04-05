"""
Provider configuration registry — single source of truth for LLM backend tuning.

AGENT-CTX: This module centralises all provider-specific knobs so that adding a
new LLM backend (e.g. vLLM, LM Studio) requires only a new entry in _PROVIDER_CONFIGS,
not edits scattered across worker.py, llm.py, and edges.py.

AGENT-CTX: get_provider_config() is called ONCE at worker startup (not per-request).
The result is stored in the ARQ ctx dict and passed to each job. This ensures the
concurrency limits and token budgets are decided before any job runs — not re-evaluated
on each call which would add import-time env-var reads throughout the codebase.

AGENT-CTX: probe_ollama_concurrency() is an OPTIONAL startup enhancement.
It queries Ollama's /api/ps endpoint to detect whether the loaded model is running
on GPU (size_vram > 0) or CPU (size_vram == 0). GPU inference can handle modest
concurrency (2 parallel calls); CPU cannot (sequential is mandatory).
The probe is best-effort — any error (connection refused, timeout, malformed JSON)
returns the safe default (1 = sequential). This means the worker is never blocked
by a failing probe.

AGENT-CTX: WHY OLLAMA NEEDS concurrency=1 BY DEFAULT (the bug this module fixes).
Running asyncio.gather() with 10 simultaneous Ollama calls causes ARQ TimeoutError:

    Traceback:
      File "backend/worker.py", run_search_job
          structured_results = await asyncio.gather(...)   ← hangs here
      asyncio.exceptions.CancelledError
      → asyncio.exceptions.TimeoutError (arq/worker.py wait_for)

The httpcore layer shows the call reached Ollama's TCP socket but stalled waiting
for response headers — Ollama accepted the connection but queued the request:

      File "httpcore/_async/http11.py", _receive_response_headers
          event = await self._receive_event(timeout=timeout)
      asyncio.exceptions.CancelledError

Root cause: Ollama serialises inference internally regardless of HTTP concurrency.
10 concurrent requests → 10× single-call latency → exceeds job_timeout.
Setting extraction_concurrency=1 makes asyncio.gather() effectively sequential,
matching Ollama's internal behaviour without hanging open connections.
"""

import os
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class ProviderConfig:
    """
    Immutable profile for a single LLM provider.

    AGENT-CTX: All fields are intentionally flat (no nested config) so that
    they can be logged in a single line at startup for easy debugging.

    extraction_concurrency:
        Max parallel calls to extract_structured_evidence() in worker.py.
        Groq: 10 — safe within 30 RPM free tier at ~2s/call.
        Ollama CPU: 1 — sequential; Ollama GPU: 2 (set by probe).
        Do NOT set above 1 for Ollama without confirming GPU inference via probe.

    edge_concurrency:
        Max parallel calls inside compute_all_edges(). Currently edge classification
        is a single batch LLM call so this is unused in practice. Present so that
        if edges.py is later changed to make per-pair calls, the limit is already
        wired and tested.

    max_tokens_extraction:
        Token budget per structured evidence extraction call (llm.py).
        500 = 11 fields × ~30 tokens each + JSON overhead + safety margin.

    max_tokens_edge:
        Token budget for the single edge classification batch call (edges.py).
        3000 = up to 45 paper-pair JSON objects + reasoning text.

    timeout_hint_s:
        Advisory estimate of expected job wall time at this concurrency level.
        Not enforced here — WorkerSettings.job_timeout is the hard limit.
        Used as a reference when deciding whether to raise job_timeout.
    """
    extraction_concurrency: int
    edge_concurrency: int
    max_tokens_extraction: int
    max_tokens_edge: int
    timeout_hint_s: int


# AGENT-CTX: Registry of known providers. Keyed by the LLM_PROVIDER env var value.
# To add a new provider: add one entry here. No other file needs to change for
# concurrency/token tuning (llm.py and edges.py still hardcode max_tokens for now —
# see the AGENT-CTX in those files about pulling from this registry in the future).
_PROVIDER_CONFIGS: dict[str, ProviderConfig] = {
    "groq": ProviderConfig(
        extraction_concurrency=10,   # 30 RPM free tier; ~2s/call → safe
        edge_concurrency=5,          # single batch call in practice; headroom for future
        max_tokens_extraction=500,
        max_tokens_edge=3000,
        timeout_hint_s=120,          # ~20-40s expected for 10 concurrent Groq calls
    ),
    # AGENT-CTX: Ollama defaults assume CPU inference (the common case for local dev
    # on a laptop). probe_ollama_concurrency() may raise extraction_concurrency to 2
    # at startup if a GPU-loaded model is detected. Never raise above 2 for Ollama
    # without profiling — Ollama's own batching limit is the real ceiling.
    "ollama": ProviderConfig(
        extraction_concurrency=1,    # CPU default: sequential (see module docstring)
        edge_concurrency=1,
        max_tokens_extraction=500,
        max_tokens_edge=3000,
        timeout_hint_s=300,          # 10 × ~30s/call CPU estimate
    ),
}


def get_provider_config() -> ProviderConfig:
    """
    Return the ProviderConfig for the active LLM_PROVIDER.

    AGENT-CTX: Falls back to Groq config for unknown providers so that a typo in
    LLM_PROVIDER does not silently run with Ollama's conservative limits on a
    cloud provider that can handle higher concurrency. The fallback is logged
    by the caller (worker.py startup) so it is visible in container logs.
    """
    provider = os.environ.get("LLM_PROVIDER", "groq").lower()
    config = _PROVIDER_CONFIGS.get(provider)
    if config is None:
        # AGENT-CTX: Unknown provider — return Groq config as the permissive default.
        # The caller should log a warning; this function never raises so the worker
        # starts even with a misconfigured LLM_PROVIDER.
        return _PROVIDER_CONFIGS["groq"]
    return config


async def probe_ollama_concurrency(base_url: str) -> int:
    """
    Query Ollama's /api/ps to determine safe extraction concurrency.

    Returns:
        2  — a model with size_vram > 0 is loaded (GPU inference; modest concurrency safe)
        1  — no GPU VRAM in use (CPU inference; must be sequential)
        1  — on any error (connection refused, timeout, bad JSON) — safe default

    AGENT-CTX: /api/ps is an Ollama-specific endpoint (not part of the OpenAI-compat
    /v1/ API). It returns the list of currently loaded models with memory stats:
        {"models": [{"name": "llama3.1:8b", "size_vram": 4294967296, ...}]}
    size_vram is bytes of VRAM used. 0 means the model is running on CPU RAM only.

    AGENT-CTX: timeout=5.0s is intentionally short. The probe runs during worker
    startup before any jobs are accepted. A slow or unreachable Ollama should not
    delay the worker from accepting jobs — it falls back to concurrency=1 (safe).

    AGENT-CTX: We return 2 (not a higher number) even for GPU because:
      1. Ollama's own scheduler may still serialise some workloads depending on
         model size vs VRAM capacity.
      2. GPU inference is fast enough (~2-5s/call) that concurrency=2 provides
         meaningful speedup (2× vs sequential) without risking queue buildup.
      3. Higher values need profiling against the specific GPU + model combination.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/api/ps")
    except Exception:
        # AGENT-CTX: Connection refused, DNS failure, or timeout — Ollama may not
        # be fully started yet. Return 1 so the worker still starts cleanly.
        return 1

    if resp.status_code != 200:
        return 1

    try:
        data = resp.json()
    except Exception:
        return 1

    models = data.get("models", [])
    for model in models:
        if model.get("size_vram", 0) > 0:
            return 2  # GPU-loaded: 2 concurrent calls safe

    return 1  # CPU-only: sequential
