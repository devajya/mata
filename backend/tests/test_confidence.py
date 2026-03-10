"""
Tests for backend.confidence — ConfidenceEngine and Factor implementations.

AGENT-CTX: All tests here are pure unit tests — no network, no LLM, no filesystem.
Always included in `make test` (no @live marker needed).

AGENT-CTX: Test structure:
  1. SubjectTypeFactor — score values and weight override
  2. ConfidenceEngine — tier mapping, empty engine guard, weighted average,
     chaining, zero-weight guard
  3. Factor protocol — structural conformance of SubjectTypeFactor and
     ad-hoc FixedFactor (verifies Protocol is not accidentally too strict)
"""

import pytest

from backend.confidence import (
    ConfidenceEngine,
    Factor,
    SubjectTypeFactor,
    _TIER_HIGH_MIN,
    _TIER_MEDIUM_MIN,
)
from backend.models import StructuredEvidence


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ev(evidence_type: str, effect_direction: str = "neutral") -> StructuredEvidence:
    """Build a minimal StructuredEvidence for a given evidence_type."""
    return StructuredEvidence(
        evidence_type=evidence_type,  # type: ignore[arg-type]
        effect_direction=effect_direction,  # type: ignore[arg-type]
        model_organism="not reported",
        sample_size="not reported",
    )


class FixedFactor:
    """
    Test double: a Factor that always returns a fixed score regardless of evidence.
    Used to isolate weighted-average arithmetic from SubjectTypeFactor score values.

    AGENT-CTX: Satisfies the Factor protocol structurally (weight + score method)
    without inheriting from it — demonstrates that the Protocol is duck-typed.
    """
    def __init__(self, score_val: float, weight: float = 1.0) -> None:
        self.weight = weight
        self._score_val = score_val

    def score(self, evidence: StructuredEvidence) -> float:
        return self._score_val


# ── SubjectTypeFactor ─────────────────────────────────────────────────────────

def test_subject_type_factor_scores_all_types():
    """Each evidence_type maps to its documented score value."""
    f = SubjectTypeFactor()
    assert f.score(_ev("clinical trial")) == 1.0
    assert f.score(_ev("human genetics")) == 0.9
    assert f.score(_ev("animal model"))   == 0.5
    assert f.score(_ev("in vitro"))       == 0.2
    assert f.score(_ev("review"))         == 0.1


def test_subject_type_factor_default_weight_is_one():
    """Default weight is 1.0 when constructed without arguments."""
    f = SubjectTypeFactor()
    assert f.weight == 1.0


def test_subject_type_factor_weight_overridable():
    """weight can be overridden at instantiation for pipeline reweighting."""
    f = SubjectTypeFactor(weight=0.5)
    assert f.weight == 0.5
    # Score values are unaffected by weight change
    assert f.score(_ev("clinical trial")) == 1.0


def test_subject_type_factor_scores_are_in_unit_interval():
    """All scores are in [0.0, 1.0] — Factor protocol invariant."""
    f = SubjectTypeFactor()
    for et in ("animal model", "human genetics", "clinical trial", "in vitro", "review"):
        s = f.score(_ev(et))
        assert 0.0 <= s <= 1.0, f"Score for {et!r} out of range: {s}"


# ── ConfidenceEngine — tier mapping with SubjectTypeFactor ────────────────────

def test_engine_maps_clinical_trial_to_high():
    engine = ConfidenceEngine().register(SubjectTypeFactor())
    assert engine.score(_ev("clinical trial")) == "high"


def test_engine_maps_human_genetics_to_high():
    engine = ConfidenceEngine().register(SubjectTypeFactor())
    assert engine.score(_ev("human genetics")) == "high"


def test_engine_maps_animal_model_to_medium():
    engine = ConfidenceEngine().register(SubjectTypeFactor())
    ev = StructuredEvidence(
        evidence_type="animal model",
        effect_direction="supports",
        model_organism="mouse",
        sample_size="n=20",
    )
    assert engine.score(ev) == "medium"


def test_engine_maps_in_vitro_to_low():
    engine = ConfidenceEngine().register(SubjectTypeFactor())
    assert engine.score(_ev("in vitro")) == "low"


def test_engine_maps_review_to_low():
    engine = ConfidenceEngine().register(SubjectTypeFactor())
    assert engine.score(_ev("review")) == "low"


# ── ConfidenceEngine — structural and edge-case behaviour ─────────────────────

def test_engine_register_returns_self_for_chaining():
    """
    .register() must return the same ConfidenceEngine instance for fluent use.

    AGENT-CTX: The main.py usage pattern depends on this:
        _engine = ConfidenceEngine().register(SubjectTypeFactor()).register(NextFactor())
    If .register() returns a new instance, the chain would still work, but
    main.py's module-level assignment would hold the last-returned instance,
    which may not be the same object as the one built up by earlier .register()
    calls if they returned copies. Returning self avoids this footgun.
    """
    engine = ConfidenceEngine()
    result = engine.register(SubjectTypeFactor())
    assert result is engine, ".register() must return self, not a new instance"
    assert isinstance(result, ConfidenceEngine)


def test_engine_with_no_factors_returns_low():
    """
    Empty engine (no factors registered) must return "low", not crash.

    AGENT-CTX: "low" is the honest default when there is no scoring signal.
    See ConfidenceEngine.score() docstring for full rationale.
    """
    engine = ConfidenceEngine()
    assert engine.score(_ev("clinical trial")) == "low"


def test_engine_with_zero_weight_factor_returns_low():
    """
    A factor registered with weight=0.0 contributes nothing; total_weight=0
    must not cause ZeroDivisionError — falls back to "low".
    """
    engine = ConfidenceEngine().register(FixedFactor(score_val=1.0, weight=0.0))
    assert engine.score(_ev("clinical trial")) == "low"


def test_engine_two_equal_weight_factors_averaged():
    """
    Two factors of equal weight produce a simple average.
    FixedFactor(1.0) and FixedFactor(0.0) → avg=0.5 → "medium".
    """
    engine = (
        ConfidenceEngine()
        .register(FixedFactor(score_val=1.0, weight=1.0))
        .register(FixedFactor(score_val=0.0, weight=1.0))
    )
    # weighted_avg = (1*1.0 + 1*0.0) / 2 = 0.5 → medium
    assert engine.score(_ev("review")) == "medium"


def test_engine_two_unequal_weight_factors():
    """
    A heavier factor dominates the average proportionally.
    FixedFactor(1.0, w=3) + FixedFactor(0.0, w=1) → avg=0.75 → "high".
    """
    engine = (
        ConfidenceEngine()
        .register(FixedFactor(score_val=1.0, weight=3.0))
        .register(FixedFactor(score_val=0.0, weight=1.0))
    )
    # weighted_avg = (3*1.0 + 1*0.0) / 4 = 0.75 → high
    assert engine.score(_ev("review")) == "high"


def test_engine_single_fixed_factor_at_medium_boundary():
    """Score exactly at _TIER_MEDIUM_MIN maps to 'medium', not 'low'."""
    engine = ConfidenceEngine().register(FixedFactor(score_val=_TIER_MEDIUM_MIN))
    assert engine.score(_ev("review")) == "medium"


def test_engine_single_fixed_factor_at_high_boundary():
    """Score exactly at _TIER_HIGH_MIN maps to 'high', not 'medium'."""
    engine = ConfidenceEngine().register(FixedFactor(score_val=_TIER_HIGH_MIN))
    assert engine.score(_ev("review")) == "high"


def test_engine_score_below_medium_boundary():
    """Score just below _TIER_MEDIUM_MIN maps to 'low'."""
    engine = ConfidenceEngine().register(FixedFactor(score_val=_TIER_MEDIUM_MIN - 0.01))
    assert engine.score(_ev("review")) == "low"


def test_engine_multiple_registrations_all_evaluated():
    """
    All registered factors contribute to the weighted average — not just the
    first or last. Three factors: 1.0, 1.0, 0.1 → avg ≈ 0.7 → "high".
    """
    engine = (
        ConfidenceEngine()
        .register(FixedFactor(score_val=1.0))
        .register(FixedFactor(score_val=1.0))
        .register(FixedFactor(score_val=0.1))
    )
    # weighted_avg = (1.0 + 1.0 + 0.1) / 3 ≈ 0.7 → high
    result = engine.score(_ev("review"))
    assert result == "high", f"Expected 'high' for avg≈0.7, got {result!r}"


# ── Factor protocol conformance ───────────────────────────────────────────────

def test_subject_type_factor_satisfies_factor_protocol():
    """SubjectTypeFactor is a runtime-checkable instance of Factor."""
    assert isinstance(SubjectTypeFactor(), Factor)


def test_fixed_factor_satisfies_factor_protocol():
    """
    FixedFactor (a pure test double) also satisfies the Factor protocol,
    confirming the protocol is duck-typed and not accidentally too strict.
    """
    assert isinstance(FixedFactor(score_val=0.5), Factor)


# ── Tier threshold constants ──────────────────────────────────────────────────

def test_tier_thresholds_are_ordered():
    """_TIER_HIGH_MIN > _TIER_MEDIUM_MIN > 0 — thresholds partition [0,1]."""
    assert 0.0 < _TIER_MEDIUM_MIN < _TIER_HIGH_MIN < 1.0


def test_subject_type_scores_respect_tier_thresholds():
    """
    Verify that SubjectTypeFactor scores and tier thresholds are consistent.
    This test catches accidental threshold changes that would break the intended
    tier mapping for any evidence type.

    AGENT-CTX: If this test fails after a threshold change, the intended mapping
    documented in SubjectTypeFactor's docstring no longer holds. Either revert
    the threshold change or update the score values AND the docstring.
    """
    f = SubjectTypeFactor()

    # Must be HIGH
    for et in ("clinical trial", "human genetics"):
        assert f.score(_ev(et)) >= _TIER_HIGH_MIN, (
            f"{et!r} score {f.score(_ev(et))} fell below _TIER_HIGH_MIN {_TIER_HIGH_MIN}"
        )

    # Must be MEDIUM (between thresholds)
    for et in ("animal model",):
        s = f.score(_ev(et))
        assert _TIER_MEDIUM_MIN <= s < _TIER_HIGH_MIN, (
            f"{et!r} score {s} is not in medium range [{_TIER_MEDIUM_MIN}, {_TIER_HIGH_MIN})"
        )

    # Must be LOW
    for et in ("in vitro", "review"):
        assert f.score(_ev(et)) < _TIER_MEDIUM_MIN, (
            f"{et!r} score {f.score(_ev(et))} is not below _TIER_MEDIUM_MIN {_TIER_MEDIUM_MIN}"
        )
