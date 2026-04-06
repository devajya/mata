from typing import Literal
from pydantic import BaseModel, Field

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

# AGENT-CTX: EdgeType — 10 semantic relationship types between evidence papers.
# These replace the old 4-value RelationshipType. Values follow the scientific
# taxonomy defined in the chain-links design brief. Do not rename values without
# updating: edges.py classify prompt, frontend/types.ts EdgeType, RelationshipLegend.tsx.
#
# Priority order for assignment (most specific first):
#   resistance_link → fails_to_translate → translates → contradicts →
#   qualifies → mechanistically_extends → combination_context → supports → replicates
#
# contradicts_methodological is assigned instead of contradicts when the conflict
# is explained by a methodological difference (dose, assay, timepoint) rather than
# a genuine biological disagreement.
EdgeType = Literal[
    "supports",
    "contradicts",
    "contradicts_methodological",
    "translates",
    "fails_to_translate",
    "mechanistically_extends",
    "qualifies",
    "combination_context",
    "resistance_link",
    "replicates",
]

# AGENT-CTX: VALID_EDGE_TYPES as a frozenset for runtime membership checks.
# Mirrors EdgeType Literal above — keep in sync if EdgeType changes.
VALID_EDGE_TYPES: frozenset[str] = frozenset([
    "supports",
    "contradicts",
    "contradicts_methodological",
    "translates",
    "fails_to_translate",
    "mechanistically_extends",
    "qualifies",
    "combination_context",
    "resistance_link",
    "replicates",
])


class StructuredEvidence(BaseModel):
    """
    Raw output of the LLM extraction step (extract_structured_evidence in llm.py).

    AGENT-CTX: This model represents ONLY what the LLM extracts — it intentionally
    does NOT include confidence_tier. Confidence is computed post-extraction by the
    ConfidenceEngine in confidence.py using a pluggable factor pipeline. Keeping
    extraction and scoring separate means the scoring logic can evolve (new factors,
    reweighting) without changing the LLM call or this model.

    AGENT-CTX: All string fields use the sentinel "not reported" (not None/null)
    when information is absent. This keeps the schema uniform — every field is always
    a string, never nullable. Edge computation in edges.py checks for "not reported"
    before using a field for comparability decisions.

    AGENT-CTX: The original 4 fields (evidence_type, effect_direction, model_organism,
    sample_size) are unchanged from Milestone 1. The 7 new fields (cancer_type through
    key_claim) are added for edge computation only — they are NOT copied onto EvidenceItem
    and NOT returned in the API payload. They exist transiently in worker.py to drive
    edges.py and are then discarded. This keeps EvidenceItem clean and avoids bloating
    the API response.

    AGENT-CTX: The original 4 fields are required (no Pydantic defaults) — the LLM is
    always expected to return them and tests assert specific values. The 7 new fields
    default to "not reported" to preserve backwards compatibility with existing test mocks
    that return 4-field JSON. Safe defaults in llm.py (_SAFE_DEFAULTS) cover the case
    where the entire JSON is unparseable. A StructuredEvidence instance is always valid.
    """

    # ── Original 4 fields (Milestone 1) ─────────────────────────────────────
    evidence_type: EvidenceType
    effect_direction: EffectDirection
    # AGENT-CTX: model_organism maps to the prompt's "model_system" field.
    # "not reported" is correct for clinical trials where no model system applies.
    model_organism: str
    # AGENT-CTX: sample_size kept as narrative string — parsing to int is lossy.
    sample_size: str

    # ── New fields for edge computation (Milestone 5 — Chain Links) ──────────
    # AGENT-CTX: The 7 new fields below all default to "not reported". This is
    # intentional and different from the original 4 fields (which have no defaults).
    # Reason: existing tests mock _raw_llm_call to return 4-field JSON; if the new
    # fields were required, model_validate() would raise ValidationError and fall back
    # to ALL safe defaults, breaking assertions on the original extracted values.
    # With defaults, partial JSON (4 fields only) validates fine — new fields just
    # remain "not reported". Full 11-field JSON from the updated prompt populates all.
    # Do NOT remove these defaults without updating all test mocks to return 11 fields.

    # AGENT-CTX: cancer_type — the specific cancer/disease context studied.
    # Examples: "NSCLC", "PDAC", "CRC", "pan-cancer", "not reported".
    # Used by edges.py: same cancer_type → +0.15 confidence on comparable edges.
    cancer_type: str = "not reported"

    # AGENT-CTX: intervention — the drug, molecule, or genetic perturbation studied.
    # Examples: "sotorasib", "KRAS G12C siRNA", "erlotinib + bevacizumab".
    # This is the PRIMARY comparability signal: two papers testing the same
    # intervention in different contexts are the most likely edge candidates.
    # edges.py uses this as the first filter in is_comparable().
    intervention: str = "not reported"

    # AGENT-CTX: primary_endpoint — what outcome was measured.
    # Examples: "IC50", "ORR", "tumor volume", "ERK phosphorylation", "OS".
    # Used for confidence scoring: same endpoint between papers → +0.10.
    primary_endpoint: str = "not reported"

    # AGENT-CTX: effect_size — quantitative result if reported.
    # Examples: "IC50 = 8nM", "ORR = 36%", "tumor regression 70%", "not reported".
    # Kept as a string (not float) — units and measurement types vary too much
    # for reliable numeric extraction. Used qualitatively in edge rationale only.
    effect_size: str = "not reported"

    # AGENT-CTX: mechanism_described — the biological mechanism the paper proposes.
    # Examples: "covalent GDP-state locking", "ERK suppression", "SOS1 bypass".
    # Used to detect MECHANISTICALLY_EXTENDS edges: if paper B's mechanism explains
    # paper A's phenotypic observation, edge B→A is assigned.
    mechanism_described: str = "not reported"

    # AGENT-CTX: resistance_findings — any resistance mutations or bypass mechanisms.
    # Examples: "Y96D KRAS mutation", "MET amplification bypass", "not reported".
    # Presence of resistance findings in a paper is a strong signal for RESISTANCE_LINK
    # edges pointing FROM the resistance paper TOWARD the efficacy paper.
    resistance_findings: str = "not reported"

    # AGENT-CTX: key_claim — a single sentence summarising the central finding.
    # LLM-extracted. Used as the primary input for edge type classification in the
    # batch edge prompt (edges.py). All other fields provide comparability context;
    # key_claim provides the semantic content for relationship determination.
    # Unlike other fields, "not reported" is a weak fallback — the LLM prompt
    # instructs it to always produce a key_claim even for sparse abstracts.
    key_claim: str = "not reported"


class EvidenceItem(BaseModel):
    """
    Full evidence record returned by the API endpoints.

    AGENT-CTX: This is the public API model. It combines:
      - Raw PubMed metadata (pmid, title, abstract)
      - LLM-extracted fields from StructuredEvidence (evidence_type, effect_direction,
        model_organism, sample_size) — note: the 7 new StructuredEvidence fields are
        NOT included here. They are transient, used only for edge computation.
      - Engine-derived field (confidence_tier) from ConfidenceEngine.score()
      - Graph metadata (layer, publication_year) assigned post-extraction

    AGENT-CTX: The four new fields (effect_direction, model_organism, sample_size,
    confidence_tier) have permanent defensive defaults. main.py always sets these
    explicitly from StructuredEvidence + ConfidenceEngine output, so the defaults
    are never hit in the normal request path. They exist as a safety net for any
    future code path (e.g. a new endpoint or test helper) that constructs EvidenceItem
    without setting all fields. Do NOT remove the defaults.
    """

    pmid: str
    title: str
    # AGENT-CTX: abstract is included in the API response to keep the response
    # self-contained (no follow-up fetches from frontend). Future slices may
    # drop it if payload size becomes a concern.
    abstract: str
    evidence_type: EvidenceType

    # AGENT-CTX: Fields below are new in Milestone 1 (Structured Evidence Extraction).
    # Defaults are permanent defensive fallbacks — see class docstring above.
    effect_direction: EffectDirection = "neutral"
    model_organism: str = "not reported"
    sample_size: str = "not reported"
    confidence_tier: ConfidenceTier = "low"

    # AGENT-CTX: Fields below are new in Milestone 2 (Graph View).
    # layer — assigned deterministically by assign_layer() in graph.py, never by the LLM.
    #   Default -1 (not 0): returning 0 would silently misclassify unknown types as
    #   in-vitro evidence. -1 excludes the item from CHAIN_LAYER_ORDER and surfaces
    #   the gap visually rather than hiding it.
    # publication_year — extracted from PubMed XML by pubmed.py. None means the year
    #   was absent or non-parseable; items with year=None are never grayed out by
    #   ChainPanel's temporal filter.
    layer: int = -1
    publication_year: int | None = None



class EdgeResult(BaseModel):
    """
    A single semantic edge between two evidence papers.

    AGENT-CTX: EdgeResult is computed by edges.py (compute_all_edges) during the
    background job and stored as part of SearchResponse. It is NOT computed on-demand
    or via a separate endpoint — edges are persisted inside result_json in the jobs
    SQLite table alongside the EvidenceItem results. This means no extra DB table
    and no recomputation on page refresh.

    AGENT-CTX: source_pmid and target_pmid reference EvidenceItem.pmid values from
    the same SearchResponse. The frontend uses these to look up node IDs
    (e.g. "evidence-{pmid}") for React Flow edge rendering.

    AGENT-CTX: confidence is floored at 0.1 and capped at 0.95 by edges.py.
    No edge is certain (0.95 max) and no edge is assigned below minimum signal (0.1 min).

    AGENT-CTX: direction is a human-readable semantic label, NOT a graph direction enum.
    Examples: "A→B", "B→A". The React Flow source/target already encode directionality;
    direction here is for display in tooltips and the NodeDrawer edge panel.

    AGENT-CTX: confidence_factors is a list of short strings explaining the confidence
    score, e.g. ["+0.20 same intervention", "-0.15 different species"]. Surfaced in
    the frontend edge detail panel to help researchers understand confidence.

    AGENT-CTX: flag is null for well-supported edges. Set to a human-readable string
    when confidence < 0.4, e.g. "Low confidence: co-mutation status unknown in Paper A".
    """

    source_pmid: str
    target_pmid: str
    edge_type: EdgeType
    # AGENT-CTX: direction encodes which paper's finding bears on the other.
    # Convention matches the design brief: "A→B" means the relationship runs from
    # source_pmid (A) to target_pmid (B). For CONTRADICTS, store bidirectionally
    # (two EdgeResult objects, one each direction) so the graph shows arrows on both ends.
    direction: str
    # AGENT-CTX: confidence range [0.1, 0.95] — enforced by edges.py, not validated
    # here to avoid re-clamping on deserialization. If a future path produces values
    # outside this range, add a validator.
    confidence: float
    rationale: str
    # AGENT-CTX: confidence_factors is a list of short explanation strings.
    # Default empty list (not None) keeps serialization uniform.
    confidence_factors: list[str] = Field(default_factory=list)
    flag: str | None = None


class SearchResponse(BaseModel):
    query: str
    results: list[EvidenceItem]
    # AGENT-CTX: edges default [] for backwards compatibility.
    # Jobs completed before this field existed (or where edge computation failed)
    # will deserialize correctly with an empty list rather than raising ValidationError.
    # The frontend treats [] edges as "no connections to render" — graph still shows nodes.
    edges: list[EdgeResult] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    # AGENT-CTX: Mirrors FastAPI's default HTTPException detail shape.
    # Kept explicit so the frontend can reliably read .detail on errors.
    detail: str
