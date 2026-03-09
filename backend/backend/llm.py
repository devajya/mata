"""
LLM evidence type classification module.

AGENT-CTX: Uses Groq API (groq SDK) for classification.
Provider decision: Groq chosen over Google Gemini for:
  - Free tier limits: 30 RPM / 6000 RPD (vs Gemini: 5 RPM / 20 RPD)
  - OpenAI-compatible chat completions API — simple, well-documented
  - No gRPC stack — avoids the event-loop binding problem we had with google-generativeai
  - Responses are plain strings, no response object wrapping

AGENT-CTX: We use the SYNCHRONOUS Groq client wrapped in asyncio.to_thread(),
NOT the AsyncGroq client. Reason: AsyncGroq creates an httpx.AsyncClient at
construction time which binds to the event loop. pytest-asyncio creates a new
event loop per test function, so a module-level AsyncGroq instance would be on
a stale loop from the second test onward.
asyncio.to_thread() runs the sync client in a thread pool — immune to this issue.
Do NOT switch to AsyncGroq without also switching to a session-scoped event loop.

AGENT-CTX: One LLM call per abstract. The /search endpoint uses asyncio.gather()
to run all calls concurrently (each in its own thread). With Groq's 30 RPM limit,
10 concurrent calls are safely within quota. Do not add a Semaphore here unless
rate-limit errors appear in production.

AGENT-CTX: The prompt instructs the model to respond with ONLY the label.
The parser strips whitespace, lowercases, validates membership.
Fallback on unrecognised output: "review" — least specific, never factually wrong.
"""

import asyncio
import os

import httpx
from groq import Groq
from groq import APIError as GroqAPIError
from groq import RateLimitError as GroqRateLimitError

from backend.models import EvidenceType

# AGENT-CTX: VALID_EVIDENCE_TYPES mirrors EvidenceType Literal for runtime validation.
# Must stay in sync with models.py — the prompt lists exactly these five values.
# If you add a value here, ALSO update: models.py, _SYSTEM_PROMPT below, frontend/types.ts.
VALID_EVIDENCE_TYPES: frozenset[str] = frozenset(
    ["animal model", "human genetics", "clinical trial", "in vitro", "review"]
)

# AGENT-CTX: Model name in one place — change here only.
# llama-3.1-8b-instant: fast (~200ms), sufficient accuracy for 5-class classification.
# Alternative for higher accuracy: "llama-3.3-70b-versatile" (slower, still free tier).
_GROQ_MODEL = "llama-3.1-8b-instant"

# AGENT-CTX: System prompt is kept as a constant so it is visible and grep-able.
# It sets the classification task and format constraint once at the system level.
# Keeping constraints in the system role (not user role) gives the model a stronger
# signal that format compliance is required, not optional.
_SYSTEM_PROMPT = (
    "You are an evidence type classifier for biomedical literature. "
    "You will be given a paper title and abstract. "
    "You must respond with EXACTLY ONE of the following labels and nothing else:\n"
    "animal model\n"
    "human genetics\n"
    "clinical trial\n"
    "in vitro\n"
    "review\n\n"
    "Do not add punctuation, explanations, or any other text. "
    "Your entire response must be one of those five labels, verbatim."
)

# AGENT-CTX: User prompt template. Title + abstract both included even when abstract is
# empty — the model can still classify from title alone.
_PROMPT_TEMPLATE = """\
Title: {title}

Abstract: {abstract}

Classify the evidence type."""

# AGENT-CTX: LLM_PROVIDER selects the backend: "groq" (default, cloud) or "ollama" (local).
# When "ollama", OLLAMA_BASE_URL points at the Ollama server (default: localhost:11434).
# The Groq SDK appends /openai/v1/ to its base URL, which Ollama does not serve;
# the ollama path uses httpx directly against Ollama's /v1/ endpoint instead.
_LLM_PROVIDER: str = os.environ.get("LLM_PROVIDER", "groq").lower()
_OLLAMA_BASE_URL: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# AGENT-CTX: Module-level client, lazily initialised on first call (see _get_client()).
# None until GROQ_API_KEY is available. Do not initialise at import time — the key
# may not be set in the environment during pytest collection.
_client: Groq | None = None


def _get_client() -> Groq:
    """
    Lazily initialise and return the Groq sync client.

    AGENT-CTX: Lazy init so that importing this module does not immediately require
    GROQ_API_KEY. The key is only read when classify_evidence_type() is first called.

    AGENT-CTX: The Groq sync client is thread-safe — one instance shared across all
    asyncio.to_thread() calls is safe. Do not create a new client per call.
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


async def classify_evidence_type(title: str, abstract: str) -> EvidenceType:
    """
    Classify a PubMed abstract into one of five evidence types using Groq LLM.

    Args:
        title:    Paper title (non-empty string expected, but empty is handled).
        abstract: Full abstract text. May be empty string for records without one.

    Returns:
        One of: "animal model" | "human genetics" | "clinical trial" | "in vitro" | "review"

    Raises:
        RuntimeError: if the Groq API call fails (network error, auth error, rate limit).
                      Does NOT raise on unrecognised model output — falls back to "review".

    AGENT-CTX: Invariant — always returns a member of VALID_EVIDENCE_TYPES.
    AGENT-CTX: Invariant — never raises due to unexpected LLM output format.
    Both invariants are relied upon by asyncio.gather() in main.py — a single raise
    cancels all in-flight tasks for that request.
    """
    prompt = _PROMPT_TEMPLATE.format(
        title=title or "(no title)",
        # AGENT-CTX: Explicit marker for absent abstract — tells the model the field is
        # intentionally empty, not accidentally omitted. Improves title-only classification.
        abstract=abstract if abstract else "(no abstract available)",
    )

    if _LLM_PROVIDER == "ollama":
        return await _classify_via_ollama(prompt)

    client = _get_client()

    try:
        # AGENT-CTX: asyncio.to_thread() runs the synchronous Groq client call in a
        # thread pool executor. This keeps classify_evidence_type() awaitable for
        # asyncio.gather() in main.py while sidestepping the event-loop binding issue
        # described in the module docstring. See also: pubmed.py uses httpx.AsyncClient
        # directly — a different pattern, both are valid for their respective use cases.
        completion = await asyncio.to_thread(
            client.chat.completions.create,
            model=_GROQ_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            # AGENT-CTX: max_tokens=10 caps output. Longest label is "human genetics"
            # (~4 tokens). Prevents runaway completions and reduces latency + cost.
            max_tokens=10,
            # AGENT-CTX: temperature=0 for deterministic, reproducible classification.
            # Do not raise temperature — this is not a creative task.
            temperature=0,
        )
    except GroqRateLimitError as e:
        # AGENT-CTX: 429 from Groq. With 30 RPM free tier this should be rare for <=10
        # concurrent calls. If it appears in production, add a Semaphore in main.py.
        raise RuntimeError(f"Groq rate limit exceeded: {e}") from e
    except GroqAPIError as e:
        raise RuntimeError(f"Groq API error: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Unexpected error calling Groq: {e}") from e

    raw = completion.choices[0].message.content or ""
    return _parse_label(raw)


async def _classify_via_ollama(prompt: str) -> EvidenceType:
    """
    Call Ollama's OpenAI-compatible /v1/chat/completions endpoint directly via httpx.

    AGENT-CTX: The Groq SDK hardcodes /openai/v1/ as its resource path prefix, which
    Ollama does not serve (Ollama uses /v1/). Using httpx directly avoids this mismatch.
    OLLAMA_BASE_URL + /v1/chat/completions is the correct Ollama endpoint.
    """
    url = f"{_OLLAMA_BASE_URL}/v1/chat/completions"
    payload = {
        "model": _GROQ_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 10,
        "temperature": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"] or ""
    except Exception as e:
        raise RuntimeError(f"Ollama request failed: {e}") from e
    return _parse_label(raw)


def _parse_label(raw: str) -> EvidenceType:
    """
    Normalise and validate the raw LLM output string into a valid EvidenceType.

    AGENT-CTX: Parsing is intentionally lenient to handle common LLM noise:
      - Leading/trailing whitespace and newlines → strip()
      - Mixed capitalisation → lower()
      - Quoted output e.g. '"clinical trial"' → strip('"\'')
      - Trailing punctuation e.g. "review." → rstrip('.')
    Secondary pass: substring scan (longest-match first) catches prefixed responses
    like "Evidence type: in vitro" despite the system instruction.
    Final fallback: "review" — least specific, never factually wrong.

    AGENT-CTX: We do NOT fuzzy-match (e.g. difflib) — it risks mapping hallucinated
    output to a wrong-but-valid label. Explicit fallback is more honest.

    AGENT-CTX: Invariant — always returns a member of VALID_EVIDENCE_TYPES.
    """
    if not raw:
        return "review"  # type: ignore[return-value]

    cleaned = raw.strip().lower().strip('"\'').rstrip(".")

    if cleaned in VALID_EVIDENCE_TYPES:
        return cleaned  # type: ignore[return-value]

    # AGENT-CTX: Substring scan — sort by length descending to prefer longer (more
    # specific) matches. e.g. "human genetics" before "review" in case both appear.
    for label in sorted(VALID_EVIDENCE_TYPES, key=len, reverse=True):
        if label in cleaned:
            return label  # type: ignore[return-value]

    print(f"[llm.py] Unrecognised Groq output: {raw!r} — falling back to 'review'")
    return "review"  # type: ignore[return-value]
