"""
Test stubs for GET /search endpoint.

AGENT-CTX: These tests are RED by design (T1 — scaffold phase).
/search currently returns 501 — all result-shape assertions will fail.
Tests will go green in T4 once pubmed.py + llm.py are wired into the endpoint.

Uses httpx.AsyncClient with ASGITransport (not app= shorthand, deprecated in httpx 0.24+).
AGENT-CTX: ASGITransport is the correct long-term API — do not revert to app= kwarg.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from backend.main import app

VALID_EVIDENCE_TYPES = {
    "animal model", "human genetics", "clinical trial", "in vitro", "review"
}


@pytest.mark.asyncio
async def test_search_returns_200_with_results():
    """
    AC: /search returns list with title + evidence_type per item.
    AC: At least 10 results returned.
    [LIVE] — hits real PubMed + Gemini APIs.
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
        assert "title" in item, f"Missing 'title' in {item}"
        assert "evidence_type" in item, f"Missing 'evidence_type' in {item}"
        assert item["evidence_type"] in VALID_EVIDENCE_TYPES, (
            f"Invalid evidence_type: {item['evidence_type']!r}"
        )


@pytest.mark.asyncio
async def test_search_response_includes_query_echo():
    """Response must echo back the query field (used by frontend for display)."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/search?query=BRAF+V600E")

    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "BRAF V600E"


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
