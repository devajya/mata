"""
Tests for backend.llm.extract_structured_evidence.

AGENT-CTX: Two tiers of tests:

  [MOCK] — monkeypatch _raw_llm_call to inject controlled responses. No network.
            Always runnable in `make test`. Tests parse/fallback logic in isolation.

  [LIVE] — call real Groq API. Require GROQ_API_KEY + available quota.
            Run with: pytest -m live
            Skip with: pytest -m "not live"  (default in CI and make test)
            ⚠️ Each live test consumes ~1 Groq API call — run sparingly.

AGENT-CTX: Live tests verify the full extraction pipeline including JSON mode
accuracy on representative abstracts. They assert on schema shape (always) and
on specific field values where the correct answer is unambiguous (e.g. a clearly
labelled RCT should always return evidence_type="clinical trial"). Accuracy on
ambiguous abstracts is left to the eval harness (test_eval.py, T5).
"""

import pytest

from backend.llm import extract_structured_evidence, _raw_llm_call
from backend.models import StructuredEvidence, VALID_EVIDENCE_TYPES


# ── Shared test data ──────────────────────────────────────────────────────────

_CLINICAL_TRIAL_ABSTRACT = (
    "Randomized controlled trial enrolling 345 patients with KRAS G12C-mutated "
    "non-small cell lung cancer. Sotorasib showed significant improvement in "
    "progression-free survival versus docetaxel (HR 0.66, p<0.001)."
)

_ANIMAL_MODEL_ABSTRACT = (
    "We implanted KRAS G12C-mutant tumor cells into BALB/c nude mice and treated "
    "with AMG-510. Tumor regression was observed in 80% of animals at day 14."
)


# ── Mock tests (no network) ───────────────────────────────────────────────────

async def test_extract_returns_defaults_on_malformed_json(monkeypatch):
    """
    When _raw_llm_call returns unparseable text, extract_structured_evidence
    must return safe defaults and never raise.

    AGENT-CTX: This is the core fallback invariant test. _raw_llm_call is
    monkeypatched (not the Groq client) because _raw_llm_call is the designated
    seam for test injection — see module docstring in llm.py.
    """
    async def _bad_call(prompt: str) -> str:
        return "this is not json at all"

    monkeypatch.setattr("backend.llm._raw_llm_call", _bad_call)

    result = await extract_structured_evidence("Any title", "Any abstract")

    assert isinstance(result, StructuredEvidence)
    assert result.evidence_type == "review"
    assert result.effect_direction == "neutral"
    assert result.model_organism == "not reported"
    assert result.sample_size == "not reported"


async def test_extract_returns_defaults_on_empty_llm_response(monkeypatch):
    """
    Empty string from LLM (e.g. Groq returns content=None → "") must fall back
    to safe defaults, not raise.
    """
    async def _empty_call(prompt: str) -> str:
        return ""

    monkeypatch.setattr("backend.llm._raw_llm_call", _empty_call)

    result = await extract_structured_evidence("Title", "Abstract")
    assert result.evidence_type == "review"
    assert result.effect_direction == "neutral"


async def test_extract_returns_defaults_on_invalid_enum_value(monkeypatch):
    """
    Valid JSON but with an evidence_type value not in the Literal — Pydantic
    ValidationError must trigger safe defaults, not an exception to the caller.
    """
    async def _bad_enum_call(prompt: str) -> str:
        return '{"evidence_type": "randomised controlled trial", "effect_direction": "supports", "model_organism": "not reported", "sample_size": "n=10"}'

    monkeypatch.setattr("backend.llm._raw_llm_call", _bad_enum_call)

    result = await extract_structured_evidence("Title", "Abstract")
    # Invalid evidence_type triggers full reset to safe defaults
    assert result.evidence_type == "review"
    assert result.effect_direction == "neutral"
    assert result.model_organism == "not reported"
    assert result.sample_size == "not reported"


async def test_extract_parses_valid_json_correctly(monkeypatch):
    """
    Well-formed JSON with valid enum values must parse into a StructuredEvidence
    with all fields set correctly — no fallback.
    """
    async def _good_call(prompt: str) -> str:
        return (
            '{"evidence_type": "clinical trial", "effect_direction": "supports", '
            '"model_organism": "not reported", "sample_size": "n=345"}'
        )

    monkeypatch.setattr("backend.llm._raw_llm_call", _good_call)

    result = await extract_structured_evidence(
        "Phase III sotorasib trial", _CLINICAL_TRIAL_ABSTRACT
    )
    assert result.evidence_type == "clinical trial"
    assert result.effect_direction == "supports"
    assert result.model_organism == "not reported"
    assert result.sample_size == "n=345"


async def test_extract_parses_populated_organism_and_size(monkeypatch):
    """
    model_organism and sample_size are passed through verbatim when populated.
    """
    async def _animal_call(prompt: str) -> str:
        return (
            '{"evidence_type": "animal model", "effect_direction": "supports", '
            '"model_organism": "BALB/c nude mouse", "sample_size": "n=24 animals"}'
        )

    monkeypatch.setattr("backend.llm._raw_llm_call", _animal_call)

    result = await extract_structured_evidence("KRAS mouse xenograft", _ANIMAL_MODEL_ABSTRACT)
    assert result.evidence_type == "animal model"
    assert result.model_organism == "BALB/c nude mouse"
    assert result.sample_size == "n=24 animals"


async def test_extract_returns_defaults_on_missing_keys(monkeypatch):
    """
    JSON object with missing required keys triggers ValidationError → safe defaults.
    All fields reset, not just the missing one.
    """
    async def _incomplete_call(prompt: str) -> str:
        # Missing effect_direction and sample_size
        return '{"evidence_type": "in vitro", "model_organism": "not reported"}'

    monkeypatch.setattr("backend.llm._raw_llm_call", _incomplete_call)

    result = await extract_structured_evidence("Title", "Abstract")
    assert result.evidence_type == "review"
    assert result.effect_direction == "neutral"


# ── Live tests (require GROQ_API_KEY + quota) ─────────────────────────────────

@pytest.mark.live
async def test_extract_returns_structured_evidence_clinical_trial():
    """
    [LIVE] Unambiguous RCT abstract must return a valid StructuredEvidence with
    evidence_type="clinical trial".

    AGENT-CTX: We assert on evidence_type because the abstract contains "randomized
    controlled trial" — the correct answer is unambiguous. effect_direction and
    sample_size are asserted on type/membership only (model may phrase things differently).
    """
    result = await extract_structured_evidence(
        title="Phase III trial of sotorasib in KRAS G12C NSCLC",
        abstract=_CLINICAL_TRIAL_ABSTRACT,
    )
    assert isinstance(result, StructuredEvidence)
    assert result.evidence_type == "clinical trial", (
        f"Expected 'clinical trial' for an RCT abstract, got {result.evidence_type!r}"
    )
    assert result.effect_direction in {"supports", "contradicts", "neutral"}
    assert isinstance(result.model_organism, str)
    assert isinstance(result.sample_size, str)


@pytest.mark.live
async def test_extract_returns_structured_evidence_animal_model():
    """[LIVE] Clear mouse xenograft abstract must return evidence_type="animal model"."""
    result = await extract_structured_evidence(
        title="KRAS G12C mouse xenograft response to AMG-510",
        abstract=_ANIMAL_MODEL_ABSTRACT,
    )
    assert isinstance(result, StructuredEvidence)
    assert result.evidence_type == "animal model", (
        f"Expected 'animal model' for a mouse xenograft abstract, got {result.evidence_type!r}"
    )
    # AGENT-CTX: We assert model_organism is not "not reported" here because the
    # abstract explicitly mentions "BALB/c nude mice". If this assertion fails,
    # the model is ignoring the organism text — check the system prompt.
    assert result.model_organism != "not reported", (
        "model_organism should be extracted for an abstract explicitly mentioning mice"
    )


@pytest.mark.live
async def test_extract_always_returns_valid_evidence_type():
    """
    [LIVE] Even with an ambiguous/review abstract, evidence_type must be in
    VALID_EVIDENCE_TYPES. Tests the fallback chain under real LLM conditions.
    """
    result = await extract_structured_evidence(
        title="A review of KRAS targeting strategies",
        abstract="This review summarises current approaches to targeting KRAS G12C.",
    )
    assert isinstance(result, StructuredEvidence)
    assert result.evidence_type in VALID_EVIDENCE_TYPES
    assert result.effect_direction in {"supports", "contradicts", "neutral"}


@pytest.mark.live
async def test_extract_handles_empty_abstract():
    """
    [LIVE] Empty abstract is a known edge case (some PubMed records lack one).
    Must return a valid StructuredEvidence based on the title alone — never raise.
    """
    result = await extract_structured_evidence(
        title="KRAS G12C mutation frequency in human cohort study",
        abstract="",
    )
    assert isinstance(result, StructuredEvidence)
    assert result.evidence_type in VALID_EVIDENCE_TYPES
    assert result.effect_direction in {"supports", "contradicts", "neutral"}
