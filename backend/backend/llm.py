"""
LLM evidence type classification module.

AGENT-CTX: Uses Google Gemini Flash (google-generativeai SDK) for classification.
Provider decision: Google AI Studio / Gemini Flash chosen for speed and cost on free tier.
Model: gemini-1.5-flash — update model name here if a newer flash variant is preferred.

AGENT-CTX: One LLM call per abstract. In T4, calls are parallelised with asyncio.gather()
to keep total latency ~3-5s for 10 abstracts instead of ~20s sequential.

AGENT-CTX: The prompt instructs the model to respond with ONLY the label.
The parser strips whitespace and lowercases the response, then validates membership.
Fallback on unrecognised output: "review" (least specific, safest default).
"""

# AGENT-CTX: STUB — raises NotImplementedError.
# Tests will ERROR (not FAIL) until T3 replaces this body.
# Do not remove the function signature — it is part of the locked interface.

from backend.models import EvidenceType

# AGENT-CTX: VALID_EVIDENCE_TYPES mirrors EvidenceType Literal for runtime validation.
# Keep in sync with models.py. The LLM prompt must list exactly these values.
VALID_EVIDENCE_TYPES: frozenset[str] = frozenset(
    ["animal model", "human genetics", "clinical trial", "in vitro", "review"]
)


async def classify_evidence_type(title: str, abstract: str) -> EvidenceType:
    """
    Classify a PubMed abstract into one of five evidence types using Gemini Flash.

    Args:
        title:    Paper title
        abstract: Full abstract text (may be empty string)

    Returns:
        One of: "animal model" | "human genetics" | "clinical trial" | "in vitro" | "review"

    Raises:
        RuntimeError: if the LLM API call fails

    AGENT-CTX: Invariant — always returns a member of VALID_EVIDENCE_TYPES.
    Never raises on unrecognised LLM output — falls back to "review".
    """
    raise NotImplementedError("classify_evidence_type not yet implemented — see T3")
