"""
LLM structured evidence extraction module.

AGENT-CTX: Uses Groq API (groq SDK) for structured evidence extraction.
Provider decision: Groq chosen over Google Gemini for:
  - Free tier limits: 30 RPM / 6000 RPD (vs Gemini: 5 RPM / 20 RPD)
  - OpenAI-compatible chat completions API with JSON mode support
  - No gRPC stack — avoids the event-loop binding problem with google-generativeai

AGENT-CTX: We use the SYNCHRONOUS Groq client wrapped in asyncio.to_thread(),
NOT the AsyncGroq client. Reason: AsyncGroq creates an httpx.AsyncClient at
construction time which binds to the event loop. pytest-asyncio creates a new
event loop per test function, so a module-level AsyncGroq instance would be on
a stale loop from the second test onward.
asyncio.to_thread() runs the sync client in a thread pool — immune to this issue.
Do NOT switch to AsyncGroq without also switching to a session-scoped event loop.

AGENT-CTX: Milestone 1 change — switched from free-text single-label classification
to structured JSON extraction. The old classify_evidence_type() returned only a
string. The new extract_structured_evidence() returns a StructuredEvidence Pydantic
model with four fields. classify_evidence_type() is retained as a deprecated wrapper
(see bottom of file) until main.py is updated in T6.
Search for DEPRECATED WRAPPER to find it.

AGENT-CTX: _raw_llm_call() is separated from extract_structured_evidence() as a
named module-level function specifically to allow monkeypatching in tests:
  monkeypatch.setattr(llm, "_raw_llm_call", async_fn_returning_bad_json)
This lets us test safe-default fallback behaviour without hitting real APIs.
Do not inline _raw_llm_call back into extract_structured_evidence — the test suite
depends on it being patchable.
"""

import asyncio
import json
import os

import httpx
from groq import Groq
from groq import APIError as GroqAPIError
from groq import RateLimitError as GroqRateLimitError
from pydantic import ValidationError

from backend.models import StructuredEvidence, VALID_EVIDENCE_TYPES  # noqa: F401

# AGENT-CTX: VALID_EVIDENCE_TYPES is defined in models.py and imported here.
# It is re-exported (noqa: F401) so test_llm.py can import it from backend.llm
# without change. If a future cleanup moves that import to backend.models directly,
# this re-export can be removed. EvidenceType is no longer imported here — the
# deprecated classify_evidence_type() wrapper that used it was removed in T6/T7.

# AGENT-CTX: Model name in one place — change here only.
# llama-3.1-8b-instant: fast (~200-400ms), sufficient for structured extraction.
# Alternative for higher accuracy: "llama-3.3-70b-versatile" (slower, still free tier).
_GROQ_MODEL = "llama-3.1-8b-instant"

# AGENT-CTX: LLM_PROVIDER selects the backend: "groq" (default, cloud) or "ollama" (local).
# Ollama is used for local development to avoid burning Groq quota.
# Both paths use identical system prompts and response_format — the code does NOT
# branch on provider after _raw_llm_call() returns. Ollama ≥0.1.34 is required
# for response_format={"type":"json_object"} support. See MEMORY.md for setup.
_LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "groq").lower()
_OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# AGENT-CTX: Module-level Groq client, lazily initialised on first call.
# None until GROQ_API_KEY is available at runtime. Lazy init prevents import-time
# errors during pytest collection when the env var is not set.
_client: Groq | None = None

# AGENT-CTX: Safe defaults returned when LLM output cannot be parsed or validated.
# "review" is the least-specific evidence_type — never factually wrong as a fallback.
# "neutral" is the least-specific effect_direction — safe for unknowns.
# "not reported" is the sentinel for absent optional string fields.
# All values must be valid members of their Literal types defined in models.py.
# If models.py Literal values change, update these defaults and re-verify they pass
# StructuredEvidence.model_validate().
_SAFE_DEFAULTS: dict[str, str] = {
    "evidence_type": "review",
    "effect_direction": "neutral",
    "model_organism": "not reported",
    "sample_size": "not reported",
}

# AGENT-CTX: System prompt for JSON mode extraction.
# response_format={"type":"json_object"} guarantees syntactically valid JSON but
# does NOT guarantee our specific keys are present or that enum values are valid.
# This prompt constrains the semantic content: lists exact allowed values and
# defines classification rules to reduce ambiguous model output.
# Do not shorten this prompt to save tokens — the classification rules are
# necessary to keep edge cases (e.g. observational vs interventional human studies)
# consistent. max_tokens=200 absorbs the prompt cost with headroom to spare.
_SYSTEM_PROMPT = """\
You are a biomedical evidence extractor. Given a paper title and abstract, \
extract structured evidence fields and return them as a JSON object.

Return a JSON object with exactly these four keys:
  "evidence_type": one of "animal model", "human genetics", "clinical trial", \
"in vitro", "review"
  "effect_direction": one of "supports", "contradicts", "neutral"
  "model_organism": the organism studied (e.g. "mouse", "rat", "zebrafish"), \
or "not reported" if not applicable or not stated
  "sample_size": the sample size as stated in the abstract \
(e.g. "n=345", "~200 patients", "3 independent experiments"), \
or "not reported" if not stated

Classification rules:
  evidence_type — classify the primary study design:
    "clinical trial"  : interventional study in humans (RCT, Phase I/II/III, open-label)
    "human genetics"  : observational study in humans (GWAS, cohort, case-control, biobank)
    "animal model"    : in vivo non-human experiments (mouse, rat, zebrafish, etc.)
    "in vitro"        : cell lines, organoids, biochemical assays, computational models
    "review"          : systematic review, meta-analysis, narrative review, opinion piece

  effect_direction:
    "supports"     — evidence supports a causal or therapeutic link
    "contradicts"  — evidence argues against the link, shows failure or harm
    "neutral"      — review, inconclusive finding, or purely descriptive

  model_organism: use "not reported" for clinical trials and human genetics studies
    unless a model organism is explicitly co-mentioned
  sample_size: use the exact phrasing from the abstract; "not reported" if absent

Never hallucinate values. Use "not reported" if information is absent or unclear.
Return only the JSON object — no explanation, no preamble, no markdown fences."""

# AGENT-CTX: User prompt template. Title + abstract both provided even when one
# is empty — the model classifies from whichever is available.
_PROMPT_TEMPLATE = """\
Title: {title}

Abstract: {abstract}

Extract the evidence fields as a JSON object."""


def _get_client() -> Groq:
    """
    Lazily initialise and return the Groq sync client.

    AGENT-CTX: Lazy init so importing this module does not immediately require
    GROQ_API_KEY. The key is only read when extract_structured_evidence() is first
    called. The Groq sync client is thread-safe — one instance shared across all
    asyncio.to_thread() calls is correct. Do not create a new client per call.
    """
    global _client
    if _client is not None:
        return _client

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY environment variable is not set. "
            "Get a free key from https://console.groq.com and add it to backend/.env"
        )

    _client = Groq(api_key=api_key)
    return _client


async def _groq_call(prompt: str) -> str:
    """
    Call the Groq API in JSON mode and return the raw completion string.

    AGENT-CTX: response_format={"type":"json_object"} enforces syntactically valid
    JSON from Groq. Combined with _SYSTEM_PROMPT, this produces consistently
    structured output. JSON mode is a hard requirement — do not remove it; without
    it the model may return free-text that fails json.loads() and triggers fallback.

    AGENT-CTX: max_tokens=200. Minimum valid JSON response is ~40 tokens; 200 gives
    headroom for longer sample_size strings. Previous value was 10 (single-label) —
    must NOT be reverted. Groq does not charge extra for unused token budget.

    AGENT-CTX: asyncio.to_thread() wraps the sync Groq call. See module docstring
    for why we use sync client + thread rather than AsyncGroq.
    """
    client = _get_client()
    try:
        completion = await asyncio.to_thread(
            client.chat.completions.create,
            model=_GROQ_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            # AGENT-CTX: JSON mode — guarantees syntactically valid JSON output.
            # Semantic correctness (correct keys, valid enum values) is enforced
            # by the prompt + _parse_structured() validation.
            response_format={"type": "json_object"},
            # AGENT-CTX: max_tokens raised from 10 to 200 for JSON output. See above.
            max_tokens=200,
            # AGENT-CTX: temperature=0 for deterministic, reproducible extraction.
            temperature=0,
        )
    except GroqRateLimitError as e:
        # AGENT-CTX: 429 from Groq. 30 RPM free tier; should be rare for <=10 calls.
        # If this appears in production, add asyncio.Semaphore in main.py.
        raise RuntimeError(f"Groq rate limit exceeded: {e}") from e
    except GroqAPIError as e:
        raise RuntimeError(f"Groq API error: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Unexpected error calling Groq: {e}") from e

    return completion.choices[0].message.content or ""


async def _ollama_call(prompt: str) -> str:
    """
    Call the Ollama local API via httpx and return the raw completion string.

    AGENT-CTX: Uses httpx directly against Ollama's /v1/chat/completions endpoint.
    The Groq SDK hardcodes /openai/v1/ which Ollama does not serve — httpx avoids
    this path mismatch without a separate SDK dependency.

    AGENT-CTX: response_format={"type":"json_object"} is included in the payload.
    This is a hard requirement (same as the Groq path) — Ollama ≥0.1.34 supports it.
    If your Ollama version is older and make test-local produces unexpected "review"/
    "neutral" safe defaults, upgrade Ollama: curl -fsSL https://ollama.com/install.sh | sh

    AGENT-CTX: Reuses _GROQ_MODEL as the Ollama model name. Works because setup
    creates an alias: echo "FROM llama3.1:8b" | ollama create llama-3.1-8b-instant -f -
    If _GROQ_MODEL is ever changed to a Groq-specific model ID, introduce a separate
    _OLLAMA_MODEL constant here rather than reusing _GROQ_MODEL.
    """
    url = f"{_OLLAMA_BASE_URL}/v1/chat/completions"
    payload = {
        "model": _GROQ_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        # AGENT-CTX: response_format must match the Groq call — hard parity requirement.
        # Both providers must behave identically so make dev and make dev-local produce
        # the same structured output. Do not remove or make provider-conditional.
        "response_format": {"type": "json_object"},
        "max_tokens": 200,
        "temperature": 0,
    }
    try:
        # AGENT-CTX: timeout=600.0 (10 minutes) for Ollama, not the 60s used elsewhere.
        # Reason: asyncio.gather() fires 10 concurrent HTTP requests, but Ollama processes
        # them sequentially in a server-side queue. On CPU inference (WSL2, no GPU),
        # llama3.1:8b can take 30-120s per call. The 10th request must wait for 9 others
        # to complete before Ollama starts processing it — total queue wait can reach
        # 9 * 120s = 1080s in the worst case. 600s is a pragmatic cap that handles typical
        # WSL2 CPU performance (~30-60s/call * 10 = 300-600s) without hanging forever if
        # Ollama is genuinely down (the connection itself would fail fast on connect error).
        # Do NOT lower this to match the Groq timeout — Groq is cloud-parallel, Ollama
        # on CPU is serial. GPU-accelerated Ollama would be much faster and may tolerate
        # a shorter timeout in the future.
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"] or ""
    except Exception as e:
        raise RuntimeError(f"Ollama request failed: {e}") from e


async def _raw_llm_call(prompt: str) -> str:
    """
    Dispatch to the configured LLM provider and return the raw response string.

    AGENT-CTX: This function exists as a named module-level callable specifically
    to be monkeypatchable in tests:
        monkeypatch.setattr(llm, "_raw_llm_call", async_fn_returning_bad_json)
    Tests that verify safe-default fallback can inject malformed JSON here without
    needing a live LLM. Do NOT inline this into extract_structured_evidence().

    AGENT-CTX: Both _groq_call and _ollama_call raise RuntimeError on API failure.
    Those errors propagate through here and are caught by the caller in main.py
    (mapped to HTTP 502). Parse errors are NOT raised here — _parse_structured()
    handles them with safe defaults.
    """
    if _LLM_PROVIDER == "ollama":
        return await _ollama_call(prompt)
    return await _groq_call(prompt)


def _parse_structured(raw: str) -> StructuredEvidence:
    """
    Parse and validate the raw LLM JSON string into a StructuredEvidence model.

    AGENT-CTX: Two-stage validation:
      1. json.loads()                      — syntactic JSON parse
      2. StructuredEvidence.model_validate() — enum membership + required keys

    AGENT-CTX: Both failure modes return _SAFE_DEFAULTS rather than raising.
    Invariant: _parse_structured() never raises — it always returns a valid
    StructuredEvidence. This matches the extract_structured_evidence() contract
    which only raises on API failure, not on bad model output.

    AGENT-CTX: No partial recovery. If any field is invalid, ALL fields reset to
    safe defaults. A partially valid extraction is harder to trust than a known-safe
    default; "not reported" is preferable to a wrong-but-plausible value.
    """
    if not raw:
        print("[llm.py] Empty LLM response — using safe defaults")
        return StructuredEvidence(**_SAFE_DEFAULTS)  # type: ignore[arg-type]

    try:
        parsed = json.loads(raw)
        return StructuredEvidence.model_validate(parsed)
    except json.JSONDecodeError as e:
        print(f"[llm.py] JSON decode error: {e!r} | raw={raw[:200]!r} — using safe defaults")
    except ValidationError as e:
        print(f"[llm.py] Schema validation error: {e!r} | raw={raw[:200]!r} — using safe defaults")

    return StructuredEvidence(**_SAFE_DEFAULTS)  # type: ignore[arg-type]


async def extract_structured_evidence(title: str, abstract: str) -> StructuredEvidence:
    """
    Extract structured evidence fields from a PubMed abstract using Groq JSON mode.

    Args:
        title:    Paper title. May be empty string — model classifies from abstract alone.
        abstract: Full abstract text. May be empty string — model classifies from title alone.

    Returns:
        StructuredEvidence with all four fields populated. Always a valid instance.
        On LLM parse/validation failure: returns safe defaults (evidence_type="review",
        effect_direction="neutral", model_organism="not reported", sample_size="not reported").

    Raises:
        RuntimeError: if the LLM API call fails (network, auth, rate limit).
                      Does NOT raise on bad/unparseable LLM output — falls back to defaults.

    AGENT-CTX: Invariant — always returns a valid StructuredEvidence instance.
    AGENT-CTX: Invariant — raises RuntimeError only on API failure, not on parse failure.
    Both invariants are relied upon by asyncio.gather() in main.py — a single raise
    cancels all in-flight tasks and returns HTTP 502 to the client.
    """
    prompt = _PROMPT_TEMPLATE.format(
        title=title or "(no title)",
        # AGENT-CTX: Explicit marker for absent abstract tells the model the field
        # is intentionally empty, not accidentally omitted. Improves title-only accuracy.
        abstract=abstract if abstract else "(no abstract available)",
    )
    raw = await _raw_llm_call(prompt)
    return _parse_structured(raw)


# AGENT-CTX: classify_evidence_type() was removed here in T6/T7.
# It was a transitional wrapper retained during T2→T5 to keep main.py and
# test_search_endpoint.py passing before they were updated. main.py now calls
# extract_structured_evidence() directly, and all mock tests patch that function.
# If you see an ImportError for classify_evidence_type, the caller is stale —
# update it to use extract_structured_evidence() and handle StructuredEvidence.
