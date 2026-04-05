"""
Tests for the edge computation engine (backend.edges).

AGENT-CTX: This file is intentionally RED until T4 creates backend/backend/edges.py.
All tests import from backend.edges at module level — any ImportError causes the
entire file to fail at collection time, which is the intended red state for TDD.
Once edges.py is implemented, ALL tests in this file should turn green together.

AGENT-CTX: Test scope covers:
  1. Model-level validation (EdgeResult, EdgeType) — structural contracts from models.py
  2. is_comparable() — rule-based paper pair pre-filtering
  3. compute_all_edges() — top-level edge computation with mocked LLM
  These tests do NOT call the real LLM (no @pytest.mark.live marker).

AGENT-CTX: classify_edges_via_llm() is monkeypatched (not mocked via patch()) because
it is a module-level async function in backend.edges — the same pattern used for
_raw_llm_call in test_llm.py. Patch via monkeypatch.setattr(edges, "classify_edges_via_llm", ...).
"""

import pytest
from pydantic import ValidationError

from backend.models import (
    EdgeResult,
    EvidenceItem,
    StructuredEvidence,
    VALID_EDGE_TYPES,
)

# AGENT-CTX: This import is what makes the file RED until T4. PaperContext,
# is_comparable, compute_all_edges, and classify_edges_via_llm must all be
# defined as module-level names in backend/backend/edges.py.
from backend import edges
from backend.edges import PaperContext, is_comparable, compute_all_edges


# ── Shared fixtures ───────────────────────────────────────────────────────────

# AGENT-CTX: MOCK_STRUCTURED has all 11 fields populated (not "not reported") so
# tests can verify that field values are actually used by is_comparable() and
# compute_all_edges(). Using "not reported" for all new fields would make
# is_comparable() always return False for the intervention check, hiding bugs.
MOCK_STRUCTURED_CLINICAL = StructuredEvidence(
    evidence_type="clinical trial",
    effect_direction="supports",
    model_organism="not reported",
    sample_size="n=100",
    cancer_type="NSCLC",
    intervention="sotorasib",
    primary_endpoint="ORR",
    effect_size="ORR = 36%",
    mechanism_described="covalent GDP-state locking",
    resistance_findings="not reported",
    key_claim="Sotorasib achieves 36% ORR in KRAS G12C NSCLC patients.",
)

MOCK_STRUCTURED_INVITRO = StructuredEvidence(
    evidence_type="in vitro",
    effect_direction="supports",
    model_organism="NCI-H358",
    sample_size="3 independent experiments",
    cancer_type="NSCLC",
    intervention="sotorasib",
    primary_endpoint="IC50",
    effect_size="IC50 = 8nM",
    mechanism_described="ERK phosphorylation suppression",
    resistance_findings="not reported",
    key_claim="Sotorasib inhibits KRAS G12C with IC50 = 8nM in NCI-H358 cells.",
)

# AGENT-CTX: MOCK_STRUCTURED_UNRELATED has "not reported" intervention and a
# non-adjacent layer (in vitro = layer 0, human genetics = layer 2) — used to
# test the is_comparable() negative case.
MOCK_STRUCTURED_UNRELATED = StructuredEvidence(
    evidence_type="human genetics",
    effect_direction="neutral",
    model_organism="not reported",
    sample_size="n=10000",
    cancer_type="pan-cancer",
    intervention="not reported",
    primary_endpoint="variant frequency",
    effect_size="not reported",
    mechanism_described="not reported",
    resistance_findings="not reported",
    key_claim="KRAS G12C mutation frequency varies across cancer types.",
)

MOCK_ITEM_CLINICAL = EvidenceItem(
    pmid="11111111",
    title="Sotorasib Phase II Trial",
    abstract="Phase II trial of sotorasib in KRAS G12C NSCLC.",
    evidence_type="clinical trial",
    layer=3,
)

MOCK_ITEM_INVITRO = EvidenceItem(
    pmid="22222222",
    title="Sotorasib In Vitro Characterisation",
    abstract="Biochemical characterisation of sotorasib in NCI-H358.",
    evidence_type="in vitro",
    layer=0,
)

MOCK_ITEM_UNRELATED = EvidenceItem(
    pmid="33333333",
    title="KRAS Mutation Landscape",
    abstract="Pan-cancer analysis of KRAS mutation frequencies.",
    evidence_type="human genetics",
    layer=2,
)

MOCK_EDGE = EdgeResult(
    source_pmid="22222222",
    target_pmid="11111111",
    edge_type="translates",
    direction="A→B",
    confidence=0.72,
    rationale="In vitro sotorasib finding translates to clinical efficacy.",
    confidence_factors=["+0.20 same intervention", "+0.15 same cancer type", "-0.15 different species"],
    flag=None,
)


# ── T3a: EdgeResult model validation ─────────────────────────────────────────

class TestEdgeResultModel:
    """
    AGENT-CTX: These tests verify the EdgeResult Pydantic model defined in models.py.
    They are co-located here (not in test_models.py) because they form the foundation
    for the edge engine tests — a reader of this file should understand what a valid
    EdgeResult looks like before reading the engine tests.
    """

    def test_edge_result_valid_construction(self):
        """A fully-populated EdgeResult with valid values constructs without error."""
        e = EdgeResult(
            source_pmid="111",
            target_pmid="222",
            edge_type="translates",
            direction="A→B",
            confidence=0.72,
            rationale="Test rationale.",
            confidence_factors=["+0.20 same intervention"],
        )
        assert e.source_pmid == "111"
        assert e.edge_type == "translates"
        assert e.flag is None  # default

    def test_edge_result_all_ten_edge_types_are_valid(self):
        """Every EdgeType value can be used in an EdgeResult without ValidationError."""
        # AGENT-CTX: Iterating VALID_EDGE_TYPES ensures this test stays in sync
        # with the Literal definition — adding a new type to EdgeType automatically
        # covers it here without test edits.
        for edge_type in VALID_EDGE_TYPES:
            e = EdgeResult(
                source_pmid="a", target_pmid="b",
                edge_type=edge_type, direction="A→B",  # type: ignore[arg-type]
                confidence=0.5, rationale="r",
            )
            assert e.edge_type == edge_type

    def test_edge_result_confidence_factors_defaults_to_empty_list(self):
        """confidence_factors has a default empty list — not None."""
        e = EdgeResult(
            source_pmid="a", target_pmid="b",
            edge_type="supports", direction="A→B",
            confidence=0.5, rationale="r",
        )
        assert e.confidence_factors == []
        assert isinstance(e.confidence_factors, list)


# ── T3b: EdgeType rejects unknown values ─────────────────────────────────────

class TestEdgeTypeValidation:
    def test_edge_type_rejects_old_relationship_type_extends(self):
        """'extends' was a valid RelationshipType in M2 — it must now be rejected."""
        with pytest.raises(ValidationError):
            EdgeResult(
                source_pmid="a", target_pmid="b",
                edge_type="extends",  # type: ignore[arg-type]
                direction="A→B", confidence=0.5, rationale="r",
            )

    def test_edge_type_rejects_old_relationship_type_contextualizes(self):
        """'contextualizes' was a valid RelationshipType in M2 — must now be rejected."""
        with pytest.raises(ValidationError):
            EdgeResult(
                source_pmid="a", target_pmid="b",
                edge_type="contextualizes",  # type: ignore[arg-type]
                direction="A→B", confidence=0.5, rationale="r",
            )

    def test_edge_type_rejects_arbitrary_string(self):
        """Arbitrary strings are rejected by EdgeType Literal validation."""
        with pytest.raises(ValidationError):
            EdgeResult(
                source_pmid="a", target_pmid="b",
                edge_type="strong_evidence",  # type: ignore[arg-type]
                direction="A→B", confidence=0.5, rationale="r",
            )


# ── T3e/T3f: is_comparable() rule-based filtering ─────────────────────────────

class TestIsComparable:
    """
    AGENT-CTX: is_comparable() is the pre-filter gate before the LLM batch call.
    It uses only extracted fields (no LLM calls) and must be fast and deterministic.
    Tests here define the contract that edges.py must implement.
    """

    def test_comparable_when_same_intervention(self):
        """Two papers studying the same named intervention are comparable."""
        a = PaperContext(
            pmid="111", evidence_type="in vitro", layer=0,
            effect_direction="supports", cancer_type="NSCLC",
            intervention="sotorasib", primary_endpoint="IC50",
            effect_size="8nM", mechanism_described="ERK suppression",
            resistance_findings="not reported",
            key_claim="Sotorasib inhibits KRAS G12C in vitro.",
            model_organism="NCI-H358",
        )
        b = PaperContext(
            pmid="222", evidence_type="clinical trial", layer=3,
            effect_direction="supports", cancer_type="NSCLC",
            intervention="sotorasib", primary_endpoint="ORR",
            effect_size="36%", mechanism_described="not reported",
            resistance_findings="not reported",
            key_claim="Sotorasib achieves 36% ORR clinically.",
            model_organism="not reported",
        )
        assert is_comparable(a, b) is True

    def test_comparable_when_adjacent_layers_even_without_shared_intervention(self):
        """
        Papers at adjacent evidence layers (e.g. in vitro→animal) are comparable
        even when intervention is 'not reported', because they may show translational
        progression of any mechanism.
        """
        # AGENT-CTX: Adjacent layer comparability catches translational edges between
        # papers that describe a target mechanism across evidence levels, even when
        # the specific drug name was not extracted. This is a deliberate permissive
        # rule — better to over-generate candidates for the LLM to filter than to miss
        # real TRANSLATES/FAILS_TO_TRANSLATE edges.
        a = PaperContext(
            pmid="111", evidence_type="in vitro", layer=0,
            effect_direction="supports", cancer_type="NSCLC",
            intervention="not reported", primary_endpoint="cell viability",
            effect_size="not reported", mechanism_described="KRAS inhibition",
            resistance_findings="not reported",
            key_claim="KRAS inhibition reduces cell viability in vitro.",
            model_organism="NCI-H358",
        )
        b = PaperContext(
            pmid="222", evidence_type="animal model", layer=1,
            effect_direction="supports", cancer_type="NSCLC",
            intervention="not reported", primary_endpoint="tumor volume",
            effect_size="not reported", mechanism_described="not reported",
            resistance_findings="not reported",
            key_claim="KRAS inhibition reduces tumor volume in mouse model.",
            model_organism="BALB/c nude mouse",
        )
        assert is_comparable(a, b) is True

    def test_not_comparable_when_both_interventions_not_reported_and_non_adjacent_layers(self):
        """
        Papers where neither has a named intervention AND layers are non-adjacent
        (distance > 1) are not comparable — no basis for a meaningful edge.
        """
        a = PaperContext(
            pmid="111", evidence_type="in vitro", layer=0,
            effect_direction="neutral", cancer_type="not reported",
            intervention="not reported", primary_endpoint="not reported",
            effect_size="not reported", mechanism_described="not reported",
            resistance_findings="not reported",
            key_claim="General review of KRAS biology.",
            model_organism="not reported",
        )
        b = PaperContext(
            pmid="333", evidence_type="human genetics", layer=2,
            effect_direction="neutral", cancer_type="pan-cancer",
            intervention="not reported", primary_endpoint="variant frequency",
            effect_size="not reported", mechanism_described="not reported",
            resistance_findings="not reported",
            key_claim="KRAS G12C occurs in 13% of NSCLC.",
            model_organism="not reported",
        )
        assert is_comparable(a, b) is False

    def test_not_comparable_same_paper(self):
        """A paper is not comparable with itself (same pmid)."""
        a = PaperContext(
            pmid="111", evidence_type="in vitro", layer=0,
            effect_direction="supports", cancer_type="NSCLC",
            intervention="sotorasib", primary_endpoint="IC50",
            effect_size="8nM", mechanism_described="ERK suppression",
            resistance_findings="not reported",
            key_claim="Sotorasib inhibits KRAS G12C in vitro.",
            model_organism="NCI-H358",
        )
        assert is_comparable(a, a) is False


# ── T3c: compute_all_edges — LLM failure returns [] ───────────────────────────

class TestComputeAllEdges:
    """
    AGENT-CTX: compute_all_edges() is the top-level entry point called by worker.py.
    It must never raise — all failures (LLM error, parse error, unexpected exception)
    must be caught and returned as an empty list so the job still completes.
    Tests here validate that contract using a monkeypatched classify_edges_via_llm.
    """

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_llm_failure(self, monkeypatch):
        """
        If classify_edges_via_llm raises RuntimeError, compute_all_edges returns []
        instead of propagating the exception — job must still complete.
        """
        async def failing_llm(*args, **kwargs):
            raise RuntimeError("Groq rate limit exceeded")

        monkeypatch.setattr(edges, "classify_edges_via_llm", failing_llm)

        result = await compute_all_edges(
            [MOCK_ITEM_CLINICAL, MOCK_ITEM_INVITRO],
            [MOCK_STRUCTURED_CLINICAL, MOCK_STRUCTURED_INVITRO],
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_items(self, monkeypatch):
        """Empty input produces empty output without calling the LLM."""
        call_count = 0

        async def should_not_be_called(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return []

        monkeypatch.setattr(edges, "classify_edges_via_llm", should_not_be_called)

        result = await compute_all_edges([], [])
        assert result == []
        assert call_count == 0  # LLM not called for empty input

    @pytest.mark.asyncio
    async def test_returns_edge_list_on_success(self, monkeypatch):
        """When classify_edges_via_llm returns edges, compute_all_edges returns them."""
        async def mock_llm(contexts):
            return [MOCK_EDGE]

        monkeypatch.setattr(edges, "classify_edges_via_llm", mock_llm)

        result = await compute_all_edges(
            [MOCK_ITEM_CLINICAL, MOCK_ITEM_INVITRO],
            [MOCK_STRUCTURED_CLINICAL, MOCK_STRUCTURED_INVITRO],
        )
        assert len(result) == 1
        assert result[0].edge_type == "translates"
        assert result[0].source_pmid == "22222222"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_comparable_pairs(self, monkeypatch):
        """
        If no pairs survive the is_comparable() filter, the LLM is not called
        and an empty list is returned.

        AGENT-CTX: This test verifies the short-circuit optimisation: when all
        papers are unrelated (no shared intervention, non-adjacent layers),
        compute_all_edges should skip the LLM call entirely. This saves a Groq
        API call and prevents unnecessary latency.
        """
        call_count = 0

        async def should_not_be_called(contexts):
            nonlocal call_count
            call_count += 1
            return []

        monkeypatch.setattr(edges, "classify_edges_via_llm", should_not_be_called)

        # Use items at layers 0 and 2 with "not reported" interventions — not comparable
        # AGENT-CTX: model_copy(update=...) is Pydantic v2's equivalent of dataclasses
        # replace() — creates a new instance with selected fields overridden.
        invitro_no_intervention = MOCK_STRUCTURED_INVITRO.model_copy(
            update={"intervention": "not reported"}
        )
        result = await compute_all_edges(
            [MOCK_ITEM_INVITRO, MOCK_ITEM_UNRELATED],
            [invitro_no_intervention, MOCK_STRUCTURED_UNRELATED],
        )
        # AGENT-CTX: If this assertion fails, it means the LLM was called even with
        # no comparable pairs — check the is_comparable() logic in edges.py.
        assert call_count == 0
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_on_unexpected_exception(self, monkeypatch):
        """
        Any unexpected exception from classify_edges_via_llm (not just RuntimeError)
        is caught and returns [] — worker process must not crash.
        """
        async def crashing_llm(*args, **kwargs):
            raise ValueError("Unexpected internal error")

        monkeypatch.setattr(edges, "classify_edges_via_llm", crashing_llm)

        result = await compute_all_edges(
            [MOCK_ITEM_CLINICAL, MOCK_ITEM_INVITRO],
            [MOCK_STRUCTURED_CLINICAL, MOCK_STRUCTURED_INVITRO],
        )
        assert result == []
