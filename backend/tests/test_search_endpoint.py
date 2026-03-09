"""
Tests for GET /search endpoint.

AGENT-CTX: Two tiers of tests:

  [MOCK] — patch fetch_abstracts + classify_evidence_type. No network. Always runnable.
           These cover endpoint wiring, error mapping, and response shape. Run in CI.

  [LIVE]  — hit real PubMed + Groq APIs. Require GROQ_API_KEY in env.
           Skip with: pytest -m "not live"
           Run with: pytest -m live

AGENT-CTX: The original AC said "tests pass with live OR mocked dependencies".
Mock tests satisfy the AC without burning free-tier Groq quota.
Live tests provide additional confidence but are deliberately separated.

Uses httpx.AsyncClient with ASGITransport (not app= shorthand, deprecated in httpx 0.24+).
AGENT-CTX: ASGITransport is the correct long-term API — do not revert to app= kwarg.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app

VALID_EVIDENCE_TYPES = {
    "animal model", "human genetics", "clinical trial", "in vitro", "review"
}

# ── Shared mock data ──────────────────────────────────────────────────────────

# AGENT-CTX: 10 records matches limit=10 in main.py search() — restored to original AC.
# If limit changes, update this list and the >=10 assertion in test_search_returns_200_with_mocked_deps.
MOCK_RECORDS = [
    {
        "pmid": f"123456{i:02d}",
        "title": f"KRAS G12C study {i}",
        "abstract": f"Abstract text for study {i}.",
    }
    for i in range(10)
]

MOCK_EVIDENCE_TYPE = "clinical trial"


# ── Mock tests (no network required) ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_returns_200_with_mocked_deps():
    """
    AC: /search returns list with title + evidence_type per item.
    [MOCK] — patches fetch_abstracts and classify_evidence_type.

    AGENT-CTX: This is the primary AC test. It verifies:
      - endpoint returns 200
      - results list is populated
      - each item has title and evidence_type
      - evidence_type is one of the 5 valid values
    """
    # AGENT-CTX: Patch at the import site in main.py, not in pubmed/llm modules.
    # main.py does `from backend.pubmed import fetch_abstracts` so the name
    # lives in backend.main's namespace — that's what must be patched.
    with patch("backend.main.fetch_abstracts", return_value=MOCK_RECORDS) as mock_fetch, \
         patch("backend.main.classify_evidence_type", return_value=MOCK_EVIDENCE_TYPE) as mock_classify:

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/search?query=KRAS+G12C")

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()

    assert "results" in data
    # AGENT-CTX: Assertion restored to >=10 — original AC value.
    # limit=10 is set in main.py. If you lower limit, lower this assertion too.
    assert len(data["results"]) >= 10, f"Expected >=10 results, got {len(data['results'])}"

    for item in data["results"]:
        assert "title" in item, f"Missing 'title' in {item}"
        assert "evidence_type" in item, f"Missing 'evidence_type' in {item}"
        assert item["evidence_type"] in VALID_EVIDENCE_TYPES, (
            f"Invalid evidence_type: {item['evidence_type']!r}"
        )

    # Verify wiring: fetch was called once with the query, classify was called per record.
    mock_fetch.assert_called_once_with("KRAS G12C", limit=10)
    assert mock_classify.call_count == len(MOCK_RECORDS)


@pytest.mark.asyncio
async def test_search_response_shape_with_mocked_deps():
    """
    AC: Response echoes back the query field.
    [MOCK] — verifies SearchResponse schema shape.
    """
    with patch("backend.main.fetch_abstracts", return_value=MOCK_RECORDS), \
         patch("backend.main.classify_evidence_type", return_value="in vitro"):

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/search?query=KRAS+G12C")

    data = response.json()
    assert data["query"] == "KRAS G12C"
    assert all(r["evidence_type"] == "in vitro" for r in data["results"])
    # AGENT-CTX: Verify pmid and abstract are also present (full EvidenceItem schema).
    assert all("pmid" in r and "abstract" in r for r in data["results"])


@pytest.mark.asyncio
async def test_search_returns_empty_list_when_pubmed_has_no_results():
    """
    [MOCK] — PubMed returns 0 results for an obscure query.
    Endpoint must return 200 with empty results list, not 404 or 500.
    """
    with patch("backend.main.fetch_abstracts", return_value=[]), \
         patch("backend.main.classify_evidence_type") as mock_classify:

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/search?query=xyzzy+nonexistent+target")

    assert response.status_code == 200
    assert response.json()["results"] == []
    # AGENT-CTX: classify must NOT be called when there are no records to classify.
    mock_classify.assert_not_called()


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_search_llm_failure_returns_502():
    """
    [MOCK] — LLM classification raises RuntimeError → endpoint must return 502.
    AGENT-CTX: 502 (Bad Gateway) signals the LLM dependency failed, not our code.
    """
    with patch("backend.main.fetch_abstracts", return_value=MOCK_RECORDS), \
         patch("backend.main.classify_evidence_type", side_effect=RuntimeError("Groq down")):

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/search?query=KRAS+G12C")

    assert response.status_code == 502
    assert "LLM" in response.json()["detail"]


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_search_empty_query_returns_422():
    """Empty string query must be rejected (min_length=1)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/search?query=")

    assert response.status_code == 422


@pytest.mark.asyncio
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
@pytest.mark.asyncio
async def test_search_returns_200_with_results():
    """
    AC: /search returns list with title + evidence_type per item (live APIs).
    [LIVE] — hits real PubMed + Groq APIs. Requires GROQ_API_KEY + available quota.
    Run with: pytest -m live

    AGENT-CTX: Restored to >=10 results — original AC value.
    Provider is Groq (30 RPM free tier) — 10 concurrent classify calls are within quota.
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
        assert "evidence_type" in item
        assert item["evidence_type"] in VALID_EVIDENCE_TYPES


@pytest.mark.live
@pytest.mark.asyncio
async def test_search_response_includes_query_echo():
    """[LIVE] Response must echo back the query field."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/search?query=BRAF+V600E")

    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "BRAF V600E"
