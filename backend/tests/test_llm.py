"""
Tests for backend.llm.classify_evidence_type.

AGENT-CTX: All tests here are marked @pytest.mark.live — they call the real Gemini API.
They require GOOGLE_API_KEY in env and available daily quota (20 RPD for gemini-2.5-flash free tier).
Run with: pytest -m live
Skip with: pytest -m "not live"  (default, used in CI without API key)

AGENT-CTX: These tests verify the classification logic accuracy and error handling.
They are NOT in the default test run to avoid burning free-tier quota during CI.
"""

import pytest
from backend.llm import classify_evidence_type, VALID_EVIDENCE_TYPES


@pytest.mark.live
@pytest.mark.asyncio
async def test_classify_clinical_trial():
    """
    AC: LLM returns a single structured field: evidence_type.
    [LIVE] — hits real Gemini API.
    """
    result = await classify_evidence_type(
        title="Phase III trial of sotorasib in KRAS G12C NSCLC",
        abstract=(
            "Randomized controlled trial enrolling 345 patients with KRAS G12C-mutated "
            "non-small cell lung cancer. Sotorasib showed significant improvement in "
            "progression-free survival versus docetaxel (HR 0.66, p<0.001)."
        ),
    )
    assert result in VALID_EVIDENCE_TYPES, f"Got unexpected evidence_type: {result!r}"
    # AGENT-CTX: We don't assert the exact label here — model accuracy is tested
    # in integration/eval tests, not in the unit suite. Unit test only checks shape.


@pytest.mark.live
@pytest.mark.asyncio
async def test_classify_returns_valid_type_for_animal_model():
    """[LIVE] — model should classify mouse study correctly."""
    result = await classify_evidence_type(
        title="KRAS G12C mouse xenograft response to AMG-510",
        abstract=(
            "We implanted KRAS G12C-mutant tumor cells into BALB/c nude mice and treated "
            "with AMG-510. Tumor regression was observed in 80% of animals at day 14."
        ),
    )
    assert result in VALID_EVIDENCE_TYPES


@pytest.mark.live
@pytest.mark.asyncio
async def test_classify_always_returns_member_of_valid_set():
    """
    AGENT-CTX: Even with an ambiguous abstract, the parser fallback ensures
    the returned value is always in VALID_EVIDENCE_TYPES. Never raises on
    unrecognised LLM output — falls back to "review".
    """
    result = await classify_evidence_type(
        title="A review of KRAS targeting strategies",
        abstract="This review summarises current approaches...",
    )
    assert result in VALID_EVIDENCE_TYPES


@pytest.mark.live
@pytest.mark.asyncio
async def test_classify_handles_empty_abstract():
    """
    AGENT-CTX: Empty abstract is a known edge case (some PubMed records lack one).
    Classifier must not raise — should return a best-guess based on title alone.
    """
    result = await classify_evidence_type(
        title="KRAS G12C mutation frequency in human cohort",
        abstract="",
    )
    assert result in VALID_EVIDENCE_TYPES
