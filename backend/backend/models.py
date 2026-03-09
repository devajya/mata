from typing import Literal
from pydantic import BaseModel

# AGENT-CTX: EvidenceType is the canonical enum for this slice.
# All five values are locked by the acceptance criteria — do not add/remove
# without updating the LLM prompt in llm.py and the frontend badge styles.
EvidenceType = Literal[
    "animal model",
    "human genetics",
    "clinical trial",
    "in vitro",
    "review",
]

# AGENT-CTX: VALID_EVIDENCE_TYPES as a frozenset for runtime membership checks.
# Mirrors the EvidenceType Literal above. Must stay in sync — if you add a value
# to EvidenceType, add it here too. Used by tests and the confidence engine.
VALID_EVIDENCE_TYPES: frozenset[str] = frozenset(
    ["animal model", "human genetics", "clinical trial", "in vitro", "review"]
)

# AGENT-CTX: EffectDirection captures the direction of the reported relationship
# between the target/intervention and the outcome. Three values only:
#   "supports"    — evidence supports a causal/therapeutic link
#   "contradicts" — evidence argues against the link or shows harm/failure
#   "neutral"     — review, correlational, or inconclusive evidence
# These values are locked by the AC and the LLM system prompt. Do not add values
# without updating: llm.py system prompt, frontend/types.ts, frontend/app/page.tsx.
EffectDirection = Literal["supports", "contradicts", "neutral"]

# AGENT-CTX: ConfidenceTier is the bucketed output of the ConfidenceEngine
# (backend/confidence.py). It is NOT extracted by the LLM — it is computed
# server-side from the StructuredEvidence fields via a pluggable factor pipeline.
# Three tiers map to weighted score ranges defined in confidence.py:
#   "high"   — score >= 0.67
#   "medium" — score >= 0.33
#   "low"    — score <  0.33
# Do not move the tier thresholds here — they live in confidence.py so they can
# be tuned without touching the data model.
ConfidenceTier = Literal["high", "medium", "low"]


class StructuredEvidence(BaseModel):
    """
    Raw output of the LLM extraction step (extract_structured_evidence in llm.py).

    AGENT-CTX: This model represents ONLY what the LLM extracts — it intentionally
    does NOT include confidence_tier. Confidence is computed post-extraction by the
    ConfidenceEngine in confidence.py using a pluggable factor pipeline. Keeping
    extraction and scoring separate means the scoring logic can evolve (new factors,
    reweighting) without changing the LLM call or this model.

    AGENT-CTX: model_organism and sample_size use the sentinel string "not reported"
    (not None / null) when the information is absent. This keeps the API schema
    uniform — every field is always a string, never nullable. The frontend hides
    rows where the value equals "not reported".

    AGENT-CTX: All four fields are required (no defaults). The LLM is instructed to
    always populate them; if JSON parsing or validation fails, llm.py falls back to
    safe defaults before constructing this model. So a StructuredEvidence instance
    in memory is always fully populated and valid.
    """

    evidence_type: EvidenceType
    effect_direction: EffectDirection
    # AGENT-CTX: model_organism — the biological system studied. Examples: "mouse",
    # "rat", "Drosophila", "human cell line". Use "not reported" (exact sentinel)
    # when not applicable (clinical trials, pure in-silico) or not stated.
    model_organism: str
    # AGENT-CTX: sample_size — narrative string as stated in the abstract. Examples:
    # "n=345", "~200 patients", "3 independent experiments". Use "not reported" when
    # absent. Kept as a string (not int) because PubMed abstracts state sizes in
    # narrative form; parsing to int would be lossy and hallucination-prone.
    sample_size: str


class EvidenceItem(BaseModel):
    """
    Full evidence record returned by the /search API endpoint.

    AGENT-CTX: This is the response model for the /search endpoint. It combines:
      - Raw PubMed metadata (pmid, title, abstract)
      - LLM-extracted fields from StructuredEvidence (evidence_type, effect_direction,
        model_organism, sample_size)
      - Engine-derived field (confidence_tier) from ConfidenceEngine.score()
    Construction happens in main.py after both extraction and scoring are complete.

    AGENT-CTX: The four new fields (effect_direction, model_organism, sample_size,
    confidence_tier) have safe default values. These defaults are TRANSITIONAL —
    they exist solely to keep main.py and its mock tests passing while the endpoint
    wiring is updated in T6. After T6, main.py always sets these fields explicitly
    from StructuredEvidence + ConfidenceEngine output. Do not rely on these defaults
    in production code paths; treat them as dead code once T6 is complete.
    """

    pmid: str
    title: str
    # AGENT-CTX: abstract is included in the API response to keep the response
    # self-contained (no follow-up fetches from frontend). Future slices may
    # drop it if payload size becomes a concern.
    abstract: str
    evidence_type: EvidenceType

    # AGENT-CTX: Fields below are new in Milestone 1 (Structured Evidence Extraction).
    # Defaults are transitional placeholders — see class docstring above.
    effect_direction: EffectDirection = "neutral"
    model_organism: str = "not reported"
    sample_size: str = "not reported"
    confidence_tier: ConfidenceTier = "low"


class SearchResponse(BaseModel):
    query: str
    results: list[EvidenceItem]


class ErrorResponse(BaseModel):
    # AGENT-CTX: Mirrors FastAPI's default HTTPException detail shape.
    # Kept explicit so the frontend can reliably read .detail on errors.
    detail: str
