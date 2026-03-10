"""
Confidence scoring pipeline for evidence items.

AGENT-CTX: This module implements a pluggable, weighted factor pipeline for
computing a ConfidenceTier from a StructuredEvidence instance. The design
is intentionally extensible: new scoring signals (sample size, peer-review
status, publication year decay, etc.) are added by implementing the Factor
protocol and calling engine.register(NewFactor()). The caller interface —
engine.score(evidence) -> ConfidenceTier — never changes.

AGENT-CTX: Architecture rationale — why a pipeline and not a lookup table:
The original plan considered a static CONFIDENCE_TIER_MAP dict (evidence_type
→ tier). That was rejected in favour of this pipeline because:
  1. Study design is only one signal; future signals (sample size, year,
     replication consensus) would require expanding the dict into a function
     anyway.
  2. A weighted average is easy to reason about, audit, and test.
  3. Individual factors are independently testable — changes to one factor's
     scoring do not require understanding the others.
  4. The pipeline is discoverable via .register() calls at the instantiation
     site in main.py, making the scoring logic visible without reading this file.

AGENT-CTX: confidence_tier is NOT extracted by the LLM. It is computed here
from StructuredEvidence fields after extraction. This separation keeps the LLM
prompt focused on extraction (not scoring), and makes scoring logic auditable,
deterministic, and tuneable without changing the LLM call.

AGENT-CTX: The engine is NOT a singleton. main.py constructs a module-level
instance. Tests construct their own instances. Do not add global state here.
"""

from typing import Protocol, runtime_checkable

from backend.models import ConfidenceTier, StructuredEvidence

# ── Tier thresholds ────────────────────────────────────────────────────────────
#
# AGENT-CTX: Thresholds are module-level constants, not hardcoded in score().
# This allows threshold tuning (e.g. tightening the "high" boundary from 0.67
# to 0.75 as more factors are added) without touching the engine logic.
# The thresholds partition [0.0, 1.0] into three contiguous ranges:
#   score >= _TIER_HIGH_MIN   → "high"
#   score >= _TIER_MEDIUM_MIN → "medium"   (and < _TIER_HIGH_MIN)
#   score <  _TIER_MEDIUM_MIN → "low"
#
# Chosen values (first pass, single-factor calibration):
#   0.67 — sits between human genetics (0.9) and animal model (0.5),
#           capturing the "robust human evidence" boundary
#   0.33 — sits between animal model (0.5) and in vitro (0.2),
#           capturing the "some in vivo evidence" boundary
# Re-calibrate these when adding factors that shift the score distribution.

_TIER_HIGH_MIN: float = 0.67
_TIER_MEDIUM_MIN: float = 0.33


# ── Factor protocol ────────────────────────────────────────────────────────────

@runtime_checkable
class Factor(Protocol):
    """
    Protocol (structural interface) for all confidence scoring factors.

    AGENT-CTX: Uses typing.Protocol for structural subtyping — any class with
    a `weight` attribute and a `score(StructuredEvidence) -> float` method
    satisfies this protocol without inheriting from it. This keeps factor
    implementations simple and avoids ABC boilerplate.

    AGENT-CTX: runtime_checkable is included so that isinstance(f, Factor)
    works at runtime if needed for debugging or future engine validation logic.
    It does not add any overhead to production code paths.

    AGENT-CTX: Factor.score() invariant — must return a float in [0.0, 1.0].
    The engine does NOT clamp values; out-of-range scores will silently produce
    wrong tier mappings. Factor implementations are responsible for clamping.

    AGENT-CTX: Future factors that require fields not yet in StructuredEvidence
    (e.g. publication year, journal impact factor) should add those fields to
    StructuredEvidence first, then implement a Factor that reads them. Do NOT
    change this protocol signature to accept additional arguments — the engine
    calls score(evidence) uniformly across all registered factors.
    """

    weight: float

    def score(self, evidence: StructuredEvidence) -> float:
        """Return a confidence score in [0.0, 1.0] for the given evidence."""
        ...


# ── Engine ─────────────────────────────────────────────────────────────────────

class ConfidenceEngine:
    """
    Pluggable weighted confidence scoring pipeline.

    AGENT-CTX: Typical usage (from main.py):
        _engine = (
            ConfidenceEngine()
            .register(SubjectTypeFactor())
        )
        tier = _engine.score(structured_evidence)

    AGENT-CTX: .register() returns self for fluent chaining. Factors are
    evaluated in registration order (though order does not affect the weighted
    average result). Each factor contributes proportionally to its weight.

    AGENT-CTX: The weighted average formula is:
        weighted_sum = sum(f.weight * f.score(ev) for f in factors)
        total_weight = sum(f.weight for f in factors)
        score = weighted_sum / total_weight

    A factor with weight=2.0 counts twice as much as one with weight=1.0.
    Negative weights are not supported and will produce undefined tier results.
    """

    def __init__(self) -> None:
        # AGENT-CTX: Private list — external code must use .register() to add
        # factors. Direct mutation of _factors would bypass the fluent API and
        # make the engine's state harder to reason about at the call site.
        self._factors: list[Factor] = []

    def register(self, factor: Factor) -> "ConfidenceEngine":
        """
        Add a factor to the pipeline and return self for chaining.

        AGENT-CTX: Returns self (not a new ConfidenceEngine) — the engine is
        mutated in place. This is safe because ConfidenceEngine instances are
        not shared across requests; main.py creates one at module load time.
        If the engine ever needs to be immutable (e.g. for thread safety with
        mutable factor state), switch to returning a copy here.
        """
        self._factors.append(factor)
        return self

    def score(self, evidence: StructuredEvidence) -> ConfidenceTier:
        """
        Compute a ConfidenceTier from all registered factors via weighted average.

        AGENT-CTX: Returns "low" when no factors are registered (total_weight=0).
        This is the safe default — "low" means "we have no scoring signal",
        which is more honest than returning "high" or crashing with ZeroDivisionError.
        An engine with no factors should never appear in production (main.py always
        registers at least SubjectTypeFactor), but the guard prevents a silent
        error if a future refactor accidentally constructs an empty engine.

        AGENT-CTX: Tier boundaries use module-level constants _TIER_HIGH_MIN and
        _TIER_MEDIUM_MIN. See their definition above for calibration rationale.

        AGENT-CTX: Factor scores are NOT clamped. The protocol requires each Factor
        to return a value in [0.0, 1.0] and the engine trusts this invariant. An
        out-of-range score (e.g. 1.2 from a buggy factor) will silently produce a
        wrong tier. When adding a new Factor, verify its score() always clamps to
        [0.0, 1.0] — see SubjectTypeFactor._SCORES for the established pattern.
        """
        if not self._factors:
            # AGENT-CTX: Empty engine guard — see docstring above.
            return "low"

        total_weight = sum(f.weight for f in self._factors)

        # AGENT-CTX: total_weight guard — prevents ZeroDivisionError if all
        # registered factors have weight=0.0. Treat as "no scoring signal" → "low".
        if total_weight == 0.0:
            return "low"

        weighted_sum = sum(f.weight * f.score(evidence) for f in self._factors)
        weighted_avg = weighted_sum / total_weight

        if weighted_avg >= _TIER_HIGH_MIN:
            return "high"
        if weighted_avg >= _TIER_MEDIUM_MIN:
            return "medium"
        return "low"


# ── Factors ────────────────────────────────────────────────────────────────────

class SubjectTypeFactor:
    """
    Confidence factor based on study design / evidence type.

    AGENT-CTX: First and currently only factor in the pipeline. Maps
    evidence_type to a score reflecting the epistemic weight of each study
    design in the context of drug target validation:

        clinical trial  → 1.0  (highest: direct human interventional evidence)
        human genetics  → 0.9  (strong: observational human evidence, causal
                                 inference via Mendelian randomisation etc.)
        animal model    → 0.5  (moderate: in vivo evidence, translation gap)
        in vitro        → 0.2  (weak: mechanistic evidence, many confounders)
        review          → 0.1  (lowest: no primary data, synthesis only)

    AGENT-CTX: These scores are calibrated so that with _TIER_HIGH_MIN=0.67
    and _TIER_MEDIUM_MIN=0.33, the tier mapping is:
        clinical trial  → high
        human genetics  → high
        animal model    → medium
        in vitro        → low
        review          → low
    Re-run test_subject_type_factor_scores() after any score change to catch
    unintended tier boundary crossings.

    AGENT-CTX: weight is a class-level default (1.0) that can be overridden
    per-instance via the constructor. This allows callers to downweight this
    factor when adding higher-information factors:
        engine.register(SubjectTypeFactor(weight=0.5))
        engine.register(SampleSizeFactor(weight=1.0))
    The class-level default ensures ConfidenceEngine().register(SubjectTypeFactor())
    works without arguments in the common case.
    """

    # AGENT-CTX: Scores are a class-level constant, not a method, so they are
    # readable at a glance and do not re-allocate on every call.
    _SCORES: dict[str, float] = {
        "clinical trial": 1.0,
        "human genetics": 0.9,
        "animal model":   0.5,
        "in vitro":       0.2,
        "review":         0.1,
    }

    def __init__(self, weight: float = 1.0) -> None:
        self.weight = weight

    def score(self, evidence: StructuredEvidence) -> float:
        """
        Return [0.0, 1.0] score based on the evidence's study design type.

        AGENT-CTX: Falls back to 0.1 (review score) for any evidence_type not
        in _SCORES. In practice this should never happen — StructuredEvidence
        validates evidence_type against the EvidenceType Literal — but the
        fallback prevents a KeyError if models.py gains a new value before this
        dict is updated.
        """
        return self._SCORES.get(evidence.evidence_type, 0.1)
