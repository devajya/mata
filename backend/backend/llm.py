"""
LLM evidence type classification module.

AGENT-CTX: Uses Google Gemini Flash via the google-generativeai SDK (v0.8.x).
NOTE: google-generativeai is deprecated upstream — the successor is google-genai.
We keep google-generativeai for now because it is already installed and functional.
Migration path: replace `import google.generativeai as genai` with `from google import genai`
and update the client/model instantiation pattern in _get_model(). See T3 annotation below.

AGENT-CTX: We use the SYNCHRONOUS generate_content() wrapped in asyncio.to_thread(),
NOT generate_content_async(). Reason: google-generativeai uses grpc.aio internally.
grpc.aio channels bind to the event loop that was running when they are first created.
pytest-asyncio (asyncio_mode=auto) creates a NEW event loop per test function.
After the first test completes its loop, subsequent tests get "Event loop is closed" errors
because the cached gRPC channel is still bound to the old loop.
asyncio.to_thread() runs the sync call in a thread pool executor — the gRPC channel
operates in the thread's own loop context and is immune to the pytest loop-per-test pattern.
Do NOT revert to generate_content_async() without first switching to a session-scoped loop.

AGENT-CTX: Model chosen: gemini-2.5-flash.
Rationale: gemini-2.0-flash has limit=0 on the free tier for this API key.
gemini-2.5-flash has confirmed free-tier quota. If quota errors appear in production,
fall back to gemini-2.5-flash-lite (also confirmed working, lower capability).
Model name is in _GEMINI_MODEL constant — change it in one place only.

AGENT-CTX: One LLM call per abstract (not batched). In T4, calls are parallelised
with asyncio.gather() to keep total latency ~3-5s for 10 abstracts rather than ~25s sequential.
Do not add batching here — keep this function single-item for composability.

AGENT-CTX: The prompt instructs the model to respond with ONLY the label.
The parser strips whitespace, lowercases, and validates membership.
Fallback on unrecognised output: "review" — least specific, never wrong.
"""

import asyncio
import os
import warnings

# AGENT-CTX: FutureWarning about Python 3.10 EOL is emitted on import.
# Suppress it so it does not pollute test/application output.
# Remove this suppression when the project moves to Python 3.11+.
warnings.filterwarnings("ignore", category=FutureWarning, module="google")

import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from backend.models import EvidenceType

# AGENT-CTX: VALID_EVIDENCE_TYPES mirrors EvidenceType Literal for runtime validation.
# Must stay in sync with models.py — the prompt lists exactly these five values.
# If you add a value here you MUST also add it to: models.py, the prompt below, frontend/types.ts.
VALID_EVIDENCE_TYPES: frozenset[str] = frozenset(
    ["animal model", "human genetics", "clinical trial", "in vitro", "review"]
)

# AGENT-CTX: Model name in one place. gemini-2.5-flash confirmed working on free tier.
# gemini-2.0-flash has limit=0 for this key — do NOT revert to it without testing quota.
_GEMINI_MODEL = "gemini-2.5-flash"

# AGENT-CTX: Module-level model instance. Initialised lazily on first call (see _get_model()).
# Do not initialise at import time — GOOGLE_API_KEY may not be set yet during test collection.
_model: genai.GenerativeModel | None = None


def _get_model() -> genai.GenerativeModel:
    """
    Lazily initialise and return the Gemini model instance.

    AGENT-CTX: Lazy init pattern chosen so that importing this module during pytest
    collection does not immediately require GOOGLE_API_KEY in the environment.
    The key is only needed when classify_evidence_type() is actually called.

    AGENT-CTX: genai.configure() is process-global state in google-generativeai.
    Calling it multiple times is safe (idempotent) but wasteful — the module-level
    _model guard ensures we only configure and instantiate once per process.
    """
    global _model
    if _model is not None:
        return _model

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY environment variable is not set. "
            "Get a key from https://aistudio.google.com/app/apikey and set it in backend/.env"
        )

    genai.configure(api_key=api_key)

    # AGENT-CTX: system_instruction sets persistent model behaviour for all calls on this instance.
    # Keeping the hard constraint in system_instruction (not the user prompt) gives the model
    # a stronger signal that format compliance is a system-level requirement, not a preference.
    _model = genai.GenerativeModel(
        model_name=_GEMINI_MODEL,
        system_instruction=(
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
        ),
    )
    return _model


# AGENT-CTX: Prompt template kept as a module-level constant for easy inspection and testing.
# The {title} / {abstract} slots are filled per-call in classify_evidence_type().
# Deliberate choice: title AND abstract are both included even when abstract is empty —
# the model can still classify from title alone (e.g. "review of KRAS targeting" → review).
_PROMPT_TEMPLATE = """\
Title: {title}

Abstract: {abstract}

Classify the evidence type."""


async def classify_evidence_type(title: str, abstract: str) -> EvidenceType:
    """
    Classify a PubMed abstract into one of five evidence types using Gemini Flash.

    Args:
        title:    Paper title (non-empty string expected, but empty is handled).
        abstract: Full abstract text. May be empty string for records without one.

    Returns:
        One of: "animal model" | "human genetics" | "clinical trial" | "in vitro" | "review"

    Raises:
        RuntimeError: if the Gemini API call fails (network error, auth error, quota exhausted).
                      Does NOT raise on unrecognised model output — falls back to "review".

    AGENT-CTX: Invariant — always returns a member of VALID_EVIDENCE_TYPES.
    AGENT-CTX: Invariant — never raises due to unexpected LLM output format.
    These invariants are relied upon by the /search endpoint in main.py (T4).
    """
    model = _get_model()
    prompt = _PROMPT_TEMPLATE.format(
        title=title or "(no title)",
        # AGENT-CTX: Replace empty abstract with explicit marker so the model
        # knows the field is absent, not just forgotten. Improves classification
        # accuracy when only the title is available.
        abstract=abstract if abstract else "(no abstract available)",
    )

    # AGENT-CTX: generation_config caps output tokens to 10.
    # The longest valid label is "human genetics" (14 chars ≈ 4 tokens).
    # Capping prevents runaway completions and reduces cost.
    gen_config = genai.types.GenerationConfig(
        max_output_tokens=10,
        temperature=0.0,  # AGENT-CTX: temp=0 for deterministic classification output.
    )

    try:
        # AGENT-CTX: asyncio.to_thread runs the synchronous generate_content() in a
        # thread pool executor. This sidesteps grpc.aio's event-loop binding problem
        # (see module docstring above). The function remains async-compatible for callers.
        response = await asyncio.to_thread(
            model.generate_content,
            prompt,
            generation_config=gen_config,
        )
    except google_exceptions.ResourceExhausted as e:
        raise RuntimeError(f"Gemini API quota exceeded: {e}") from e
    except google_exceptions.GoogleAPIError as e:
        raise RuntimeError(f"Gemini API error: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Unexpected error calling Gemini: {e}") from e

    return _parse_response(response)


def _parse_response(response: genai.types.GenerateContentResponse) -> EvidenceType:
    """
    Extract and validate the evidence type label from the Gemini response.

    AGENT-CTX: Parsing is intentionally lenient to handle common LLM noise:
      - Leading/trailing whitespace and newlines → strip()
      - Mixed capitalisation → lower()
      - Quoted labels e.g. '"clinical trial"' → strip('"\'')
      - Trailing punctuation e.g. "review." → rstrip('.')
    If the result still isn't in VALID_EVIDENCE_TYPES, fallback to "review".
    "review" is the safest fallback — it's never factually wrong, just least specific.

    AGENT-CTX: We do NOT attempt fuzzy matching (e.g. difflib) because it risks
    silently mapping a hallucinated category to a wrong-but-valid label.
    The explicit fallback "review" is more honest than a wrong confident classification.
    """
    raw: str = ""

    try:
        # AGENT-CTX: response.text raises ValueError if the response was blocked by safety filters.
        # The try/except below catches this and falls through to the fallback.
        raw = response.text
    except ValueError:
        # AGENT-CTX: Safety filter blocked the response. This shouldn't happen for
        # biomedical literature classification, but if it does, "review" is the safe fallback.
        return "review"  # type: ignore[return-value]

    if not raw:
        return "review"  # type: ignore[return-value]

    # Normalise: strip whitespace, lowercase, remove common punctuation noise.
    cleaned = raw.strip().lower().strip('"\'').rstrip(".")

    if cleaned in VALID_EVIDENCE_TYPES:
        return cleaned  # type: ignore[return-value]

    # AGENT-CTX: Secondary attempt — check if any valid label appears as a substring.
    # Handles cases where the model prefixes the label e.g. "Evidence type: clinical trial"
    # despite the system instruction. Prefer longer matches to avoid "review" matching
    # inside "systematic review" when "review" should actually be the label.
    for label in sorted(VALID_EVIDENCE_TYPES, key=len, reverse=True):
        if label in cleaned:
            return label  # type: ignore[return-value]

    # AGENT-CTX: Fallback — model output was unrecognisable.
    # Log the raw response to help debug prompt compliance issues in production.
    # TODO (T4): replace print with structured logging once the app has a logger.
    print(f"[llm.py] Unrecognised Gemini output: {raw!r} — falling back to 'review'")
    return "review"  # type: ignore[return-value]
