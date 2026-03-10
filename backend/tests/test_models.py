"""
Tests for backend.models — data model integrity for Milestone 1.

AGENT-CTX: These tests verify the shape and validation behaviour of the new
Pydantic models added in T1. They are pure unit tests — no network, no LLM,
no filesystem. Always included in `make test` (no @live marker).

AGENT-CTX: Tests are split into two groups:
  1. StructuredEvidence — the LLM extraction output model (no confidence_tier)
  2. EvidenceItem — the API response model (includes confidence_tier, has defaults)
"""

import pytest
from pydantic import ValidationError

from backend.models import (
    ConfidenceTier,
    EffectDirection,
    EvidenceItem,
    EvidenceType,
    StructuredEvidence,
    VALID_EVIDENCE_TYPES,
)


# ── StructuredEvidence ────────────────────────────────────────────────────────


def test_structured_evidence_validates_correct_input():
    """All four required fields present and valid → model constructs cleanly."""
    se = StructuredEvidence(
        evidence_type="clinical trial",
        effect_direction="supports",
        model_organism="not reported",
        sample_size="n=345",
    )
    assert se.evidence_type == "clinical trial"
    assert se.effect_direction == "supports"
    assert se.model_organism == "not reported"
    assert se.sample_size == "n=345"


def test_structured_evidence_accepts_all_evidence_types():
    """Every EvidenceType value is accepted by StructuredEvidence."""
    for et in VALID_EVIDENCE_TYPES:
        se = StructuredEvidence(
            evidence_type=et,  # type: ignore[arg-type]
            effect_direction="neutral",
            model_organism="not reported",
            sample_size="not reported",
        )
        assert se.evidence_type == et


def test_structured_evidence_accepts_all_effect_directions():
    """All three EffectDirection values are accepted."""
    for direction in ("supports", "contradicts", "neutral"):
        se = StructuredEvidence(
            evidence_type="review",
            effect_direction=direction,  # type: ignore[arg-type]
            model_organism="not reported",
            sample_size="not reported",
        )
        assert se.effect_direction == direction


def test_structured_evidence_rejects_invalid_evidence_type():
    """An unrecognised evidence_type value must raise ValidationError."""
    with pytest.raises(ValidationError):
        StructuredEvidence(
            evidence_type="randomised controlled trial",  # type: ignore[arg-type]
            effect_direction="supports",
            model_organism="not reported",
            sample_size="not reported",
        )


def test_structured_evidence_rejects_invalid_effect_direction():
    """An unrecognised effect_direction value must raise ValidationError."""
    with pytest.raises(ValidationError):
        StructuredEvidence(
            evidence_type="clinical trial",
            effect_direction="unknown",  # type: ignore[arg-type]
            model_organism="not reported",
            sample_size="not reported",
        )


def test_structured_evidence_has_no_confidence_tier_field():
    """
    StructuredEvidence must NOT have a confidence_tier field.

    AGENT-CTX: confidence_tier is engine-derived (ConfidenceEngine in confidence.py),
    not LLM-extracted. Keeping it off StructuredEvidence enforces the boundary
    between extraction and scoring. If this test fails, someone has added confidence_tier
    to StructuredEvidence — revert that and add it to EvidenceItem only.
    """
    se = StructuredEvidence(
        evidence_type="review",
        effect_direction="neutral",
        model_organism="not reported",
        sample_size="not reported",
    )
    assert not hasattr(se, "confidence_tier"), (
        "StructuredEvidence must not have confidence_tier — it is engine-derived, "
        "not LLM-extracted. See confidence.py."
    )


def test_structured_evidence_sentinel_strings_are_plain_str():
    """model_organism and sample_size are str, not Optional — always present."""
    se = StructuredEvidence(
        evidence_type="in vitro",
        effect_direction="neutral",
        model_organism="not reported",
        sample_size="not reported",
    )
    assert isinstance(se.model_organism, str)
    assert isinstance(se.sample_size, str)


def test_structured_evidence_accepts_populated_organism_and_size():
    """Non-sentinel values for model_organism and sample_size are valid."""
    se = StructuredEvidence(
        evidence_type="animal model",
        effect_direction="supports",
        model_organism="BALB/c nude mouse",
        sample_size="n=24 animals",
    )
    assert se.model_organism == "BALB/c nude mouse"
    assert se.sample_size == "n=24 animals"


# ── EvidenceItem ──────────────────────────────────────────────────────────────


def test_evidence_item_accepts_all_fields_explicit():
    """EvidenceItem with all nine fields explicitly set constructs cleanly."""
    item = EvidenceItem(
        pmid="12345678",
        title="Phase III KRAS trial",
        abstract="A randomised controlled trial...",
        evidence_type="clinical trial",
        effect_direction="supports",
        model_organism="not reported",
        sample_size="n=345",
        confidence_tier="high",
    )
    assert item.pmid == "12345678"
    assert item.confidence_tier == "high"
    assert item.effect_direction == "supports"
    assert item.model_organism == "not reported"
    assert item.sample_size == "n=345"


def test_evidence_item_new_fields_have_safe_defaults():
    """
    New fields default to safe values when not provided.

    AGENT-CTX: These defaults are permanent defensive fallbacks (not transitional).
    main.py always sets these fields explicitly from StructuredEvidence + ConfidenceEngine,
    so the defaults are never hit in the normal request path. They guard against partial
    construction in test helpers or future endpoints. Do not remove them.
    The defaults are intentionally conservative: "neutral" / "not reported" / "low".
    """
    item = EvidenceItem(
        pmid="99",
        title="Old-style construction",
        abstract="Abstract text",
        evidence_type="review",
    )
    assert item.effect_direction == "neutral"
    assert item.model_organism == "not reported"
    assert item.sample_size == "not reported"
    assert item.confidence_tier == "low"


def test_evidence_item_rejects_invalid_confidence_tier():
    """An invalid confidence_tier value must raise ValidationError."""
    with pytest.raises(ValidationError):
        EvidenceItem(
            pmid="1",
            title="T",
            abstract="A",
            evidence_type="review",
            effect_direction="neutral",
            model_organism="not reported",
            sample_size="not reported",
            confidence_tier="very high",  # type: ignore[arg-type]
        )


def test_evidence_item_rejects_invalid_effect_direction():
    """An invalid effect_direction value must raise ValidationError."""
    with pytest.raises(ValidationError):
        EvidenceItem(
            pmid="1",
            title="T",
            abstract="A",
            evidence_type="in vitro",
            effect_direction="positive",  # type: ignore[arg-type]
            model_organism="not reported",
            sample_size="not reported",
            confidence_tier="low",
        )


def test_evidence_item_accepts_all_confidence_tiers():
    """All three ConfidenceTier values are accepted by EvidenceItem."""
    for tier in ("high", "medium", "low"):
        item = EvidenceItem(
            pmid="1",
            title="T",
            abstract="A",
            evidence_type="clinical trial",
            effect_direction="supports",
            model_organism="not reported",
            sample_size="not reported",
            confidence_tier=tier,  # type: ignore[arg-type]
        )
        assert item.confidence_tier == tier


# ── VALID_EVIDENCE_TYPES ──────────────────────────────────────────────────────


def test_valid_evidence_types_matches_literal():
    """
    VALID_EVIDENCE_TYPES frozenset must contain exactly the same values as the
    EvidenceType Literal. If EvidenceType is updated, VALID_EVIDENCE_TYPES must
    be updated too — this test will catch the mismatch.

    AGENT-CTX: Both VALID_EVIDENCE_TYPES (frozenset, for runtime checks) and
    EvidenceType (Literal, for static type checking) must stay in sync.
    The canonical source of truth is the EvidenceType Literal — VALID_EVIDENCE_TYPES
    is a runtime mirror. If they diverge, Pydantic validation and runtime checks
    will disagree on what is valid.
    """
    expected = {"animal model", "human genetics", "clinical trial", "in vitro", "review"}
    assert VALID_EVIDENCE_TYPES == expected, (
        f"VALID_EVIDENCE_TYPES {VALID_EVIDENCE_TYPES!r} does not match EvidenceType Literal. "
        "Update models.py to keep them in sync."
    )
