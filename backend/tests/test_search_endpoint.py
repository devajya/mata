"""
Tests for GET /search endpoint.

AGENT-CTX: Two tiers of tests:

  [MOCK] — patch fetch_abstracts + extract_structured_evidence. No network.
           Always runnable. These cover endpoint wiring, error mapping,
           response shape, and confidence tier derivation. Run in CI / make test.

  [LIVE] — hit real PubMed + Groq APIs. Require GROQ_API_KEY in env.
           Skip with: pytest -m "not live"
           Run with:  pytest -m live
           ⚠️ Burns ~10 Groq API calls per live test. Run sparingly.

AGENT-CTX: Mock tests patch extract_structured_evidence (not classify_evidence_type,
which was removed in T6/T7). The mock return value is a StructuredEvidence instance,
not a bare string. The endpoint's _engine.score() is NOT patched — it runs for real
against the mocked StructuredEvidence, which means confidence_tier assertions in
mock tests verify the full pipeline (extraction mock → engine → tier).

AGENT-CTX: ASGITransport is the correct httpx API — do not revert to the deprecated
app= shorthand (removed in httpx 0.24+).
"""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.models import StructuredEvidence

VALID_EVIDENCE_TYPES = {
    "animal model", "human genetics", "clinical trial", "in vitro", "review"
}
VALID_EFFECT_DIRECTIONS = {"supports", "contradicts", "neutral"}
VALID_CONFIDENCE_TIERS = {"high", "medium", "low"}

# ── Shared mock data ──────────────────────────────────────────────────────────

# AGENT-CTX: 10 records matches limit=10 in main.py search().
# If limit changes, update this list and the >=10 assertion below.
MOCK_RECORDS = [
    {
        "pmid": f"123456{i:02d}",
        "title": f"KRAS G12C study {i}",
        "abstract": f"Abstract text for study {i}.",
    }
    for i in range(10)
]

# AGENT-CTX: MOCK_STRUCTURED replaces the old MOCK_EVIDENCE_TYPE string.
# extract_structured_evidence() now returns a StructuredEvidence, not a bare string.
# evidence_type="clinical trial" → _engine.score() → confidence_tier="high".
# Tests that assert confidence_tier rely on the real engine running (not mocked),
# which validates the full extract → score → response pipeline end-to-end.
MOCK_STRUCTURED = StructuredEvidence(
    evidence_type="clinical trial",
    effect_direction="supports",
    model_organism="not reported",
    sample_size="not reported",
)


# ── Mock tests (no network required) ─────────────────────────────────────────

async def test_search_returns_200_with_mocked_deps():
    """
    AC: /search returns list with all structured fields per item.
    [MOCK] — patches fetch_abstracts and extract_structured_evidence.

    AGENT-CTX: Primary AC test for Milestone 1. Verifies:
      - endpoint returns 200
      - results list has >=10 items
      - each item has title, evidence_type, effect_direction, model_organism,
        sample_size, confidence_tier — all valid values
      - extract_structured_evidence is called once per record
    """
    # AGENT-CTX: Patch at the import site in main.py (backend.main namespace).
    # main.py does `from backend.llm import extract_structured_evidence` so the
    # name lives in backend.main — that's the correct patch target.
    with patch("backend.main.fetch_abstracts", return_value=MOCK_RECORDS) as mock_fetch, \
         patch("backend.main.extract_structured_evidence", return_value=MOCK_STRUCTURED) as mock_extract:

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/search?query=KRAS+G12C")

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()

    assert "results" in data
    assert len(data["results"]) >= 10, f"Expected >=10 results, got {len(data['results'])}"

    for item in data["results"]:
        assert "title" in item, f"Missing 'title' in {item}"
        assert "evidence_type" in item, f"Missing 'evidence_type' in {item}"
        assert item["evidence_type"] in VALID_EVIDENCE_TYPES, (
            f"Invalid evidence_type: {item['evidence_type']!r}"
        )
        assert "effect_direction" in item, f"Missing 'effect_direction' in {item}"
        assert item["effect_direction"] in VALID_EFFECT_DIRECTIONS, (
            f"Invalid effect_direction: {item['effect_direction']!r}"
        )
        assert "model_organism" in item, f"Missing 'model_organism' in {item}"
        assert isinstance(item["model_organism"], str)
        assert "sample_size" in item, f"Missing 'sample_size' in {item}"
        assert isinstance(item["sample_size"], str)
        assert "confidence_tier" in item, f"Missing 'confidence_tier' in {item}"
        assert item["confidence_tier"] in VALID_CONFIDENCE_TIERS, (
            f"Invalid confidence_tier: {item['confidence_tier']!r}"
        )

    # Verify wiring: fetch called once, extract called once per record.
    mock_fetch.assert_called_once_with("KRAS G12C", limit=10)
    assert mock_extract.call_count == len(MOCK_RECORDS)


async def test_confidence_tier_derived_from_evidence_type():
    """
    AC: confidence_tier is engine-derived from evidence_type, not LLM-extracted.
    MOCK_STRUCTURED has evidence_type="clinical trial" → engine scores 1.0 → "high".

    AGENT-CTX: This test intentionally does NOT mock the ConfidenceEngine.
    Running the real engine against a mocked StructuredEvidence validates the
    full extract → score pipeline. If this test fails after a threshold change
    in confidence.py, verify that clinical trial still maps to "high".
    """
    with patch("backend.main.fetch_abstracts", return_value=MOCK_RECORDS), \
         patch("backend.main.extract_structured_evidence", return_value=MOCK_STRUCTURED):

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/search?query=KRAS+G12C")

    assert response.status_code == 200
    for item in response.json()["results"]:
        assert item["confidence_tier"] == "high", (
            f"Expected 'high' for clinical trial evidence, got {item['confidence_tier']!r}"
        )


async def test_confidence_tier_low_for_review():
    """
    MOCK_STRUCTURED variant with evidence_type="review" → engine scores 0.1 → "low".
    Validates that the engine correctly maps review-type evidence to the lowest tier.
    """
    review_structured = StructuredEvidence(
        evidence_type="review",
        effect_direction="neutral",
        model_organism="not reported",
        sample_size="not reported",
    )
    with patch("backend.main.fetch_abstracts", return_value=MOCK_RECORDS), \
         patch("backend.main.extract_structured_evidence", return_value=review_structured):

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/search?query=KRAS+G12C")

    assert response.status_code == 200
    for item in response.json()["results"]:
        assert item["confidence_tier"] == "low"


async def test_search_response_shape_with_mocked_deps():
    """
    AC: Response echoes back the query field and all EvidenceItem fields are present.
    [MOCK] — verifies full SearchResponse schema shape including new Milestone 1 fields.

    AGENT-CTX: Uses a separate StructuredEvidence with evidence_type="in vitro"
    to verify the field is passed through correctly, independent of MOCK_STRUCTURED.
    """
    in_vitro_structured = StructuredEvidence(
        evidence_type="in vitro",
        effect_direction="neutral",
        model_organism="not reported",
        sample_size="not reported",
    )
    with patch("backend.main.fetch_abstracts", return_value=MOCK_RECORDS), \
         patch("backend.main.extract_structured_evidence", return_value=in_vitro_structured):

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/search?query=KRAS+G12C")

    data = response.json()
    assert data["query"] == "KRAS G12C"
    assert all(r["evidence_type"] == "in vitro" for r in data["results"])
    assert all(r["effect_direction"] == "neutral" for r in data["results"])
    # AGENT-CTX: Verify pmid and abstract are present (full EvidenceItem schema).
    assert all("pmid" in r and "abstract" in r for r in data["results"])
    # confidence_tier for "in vitro" is "low" (engine score 0.2 < threshold 0.33)
    assert all(r["confidence_tier"] == "low" for r in data["results"])


async def test_search_response_includes_all_structured_fields():
    """
    AC: Every EvidenceItem in the response includes all four Milestone 1 fields.
    [MOCK] — structural completeness check independent of specific values.
    """
    with patch("backend.main.fetch_abstracts", return_value=MOCK_RECORDS), \
         patch("backend.main.extract_structured_evidence", return_value=MOCK_STRUCTURED):

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/search?query=KRAS+G12C")

    assert response.status_code == 200
    for item in response.json()["results"]:
        assert item["effect_direction"] in VALID_EFFECT_DIRECTIONS
        assert isinstance(item["model_organism"], str)
        assert isinstance(item["sample_size"], str)
        assert item["confidence_tier"] in VALID_CONFIDENCE_TIERS


async def test_search_returns_empty_list_when_pubmed_has_no_results():
    """
    [MOCK] — PubMed returns 0 results for an obscure query.
    Endpoint must return 200 with empty results list, not 404 or 500.
    """
    with patch("backend.main.fetch_abstracts", return_value=[]), \
         patch("backend.main.extract_structured_evidence") as mock_extract:

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/search?query=xyzzy+nonexistent+target")

    assert response.status_code == 200
    assert response.json()["results"] == []
    # AGENT-CTX: extract must NOT be called when there are no records to extract from.
    mock_extract.assert_not_called()


async def test_search_pubmed_failure_returns_500():
    """
    [MOCK] — PubMed fetch raises RuntimeError → endpoint must return 500.
    AGENT-CTX: 500 signals a data-source failure (PubMed), distinct from 502 (LLM).
    """
    with patch("backend.main.fetch_abstracts", side_effect=RuntimeError("PubMed down")):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/search?query=KRAS+G12C")

    assert response.status_code == 500
    assert "PubMed" in response.json()["detail"]


async def test_search_llm_failure_returns_502():
    """
    [MOCK] — LLM extraction raises RuntimeError → endpoint must return 502.
    AGENT-CTX: 502 (Bad Gateway) signals the LLM dependency failed, not our code.
    Note: parse errors inside extract_structured_evidence return safe defaults
    (not raise) — only genuine API failures (network, auth, rate limit) raise
    RuntimeError and trigger this 502 path.
    """
    with patch("backend.main.fetch_abstracts", return_value=MOCK_RECORDS), \
         patch("backend.main.extract_structured_evidence", side_effect=RuntimeError("Groq down")):

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/search?query=KRAS+G12C")

    assert response.status_code == 502
    assert "LLM" in response.json()["detail"]


async def test_search_missing_query_returns_422():
    """
    AC: query param is required — omitting it must return 422 Unprocessable Entity.
    AGENT-CTX: FastAPI auto-validates Query(...) — this test confirms the contract
    is not accidentally relaxed (e.g. by adding a default value to the param).
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/search")

    assert response.status_code == 422


async def test_search_empty_query_returns_422():
    """Empty string query must be rejected (min_length=1)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/search?query=")

    assert response.status_code == 422


async def test_health_endpoint():
    """Health check must always return 200 regardless of other state."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ── Live tests (require network + quota) ─────────────────────────────────────

@pytest.mark.live
async def test_search_returns_200_with_results():
    """
    AC: /search returns list with all structured fields per item (live APIs).
    [LIVE] — hits real PubMed + Groq APIs. Requires GROQ_API_KEY + available quota.
    Run with: pytest -m live
    ⚠️ Burns ~10 Groq API calls.

    AGENT-CTX: Asserts all Milestone 1 fields are present and valid in the live
    response. This is the end-to-end integration test for the full extraction
    + scoring pipeline against real data.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/search?query=KRAS+G12C")

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert "results" in data
    assert len(data["results"]) >= 10, f"Expected >=10 results, got {len(data['results'])}"

    for item in data["results"]:
        assert "title" in item
        assert item["evidence_type"] in VALID_EVIDENCE_TYPES
        assert item["effect_direction"] in VALID_EFFECT_DIRECTIONS
        assert isinstance(item["model_organism"], str)
        assert isinstance(item["sample_size"], str)
        assert item["confidence_tier"] in VALID_CONFIDENCE_TIERS


@pytest.mark.live
async def test_search_response_includes_query_echo():
    """[LIVE] Response must echo back the query field."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/search?query=BRAF+V600E")

    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "BRAF V600E"
