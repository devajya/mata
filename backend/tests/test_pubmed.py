"""
Test stubs for backend.pubmed.fetch_abstracts.

AGENT-CTX: These tests are RED by design (T1 — scaffold phase).
They will ERROR with NotImplementedError until T2 implements fetch_abstracts.
Tests marked with [LIVE] hit the real PubMed API — run with --live flag in CI.
Tests without [LIVE] must be runnable offline via mocks after T2.
"""

import pytest
from backend.pubmed import fetch_abstracts

# AGENT-CTX: Required keys in every returned record (locked interface contract).
REQUIRED_KEYS = {"pmid", "title", "abstract"}


@pytest.mark.asyncio
async def test_fetch_returns_at_least_10_abstracts():
    """
    AC: Backend fetches at least 10 abstracts from PubMed.
    [LIVE] — hits real PubMed API.
    """
    results = await fetch_abstracts("KRAS G12C", limit=10)
    assert len(results) >= 10, f"Expected >=10 results, got {len(results)}"
    for r in results:
        assert REQUIRED_KEYS.issubset(r.keys()), f"Record missing keys: {r.keys()}"


@pytest.mark.asyncio
async def test_fetch_returns_correct_types():
    """All returned values must be strings (pmid, title, abstract)."""
    results = await fetch_abstracts("KRAS G12C", limit=10)
    for r in results:
        assert isinstance(r["pmid"], str), "pmid must be str"
        assert isinstance(r["title"], str), "title must be str"
        assert isinstance(r["abstract"], str), "abstract must be str (empty string allowed)"


@pytest.mark.asyncio
async def test_fetch_handles_empty_abstract_gracefully():
    """
    AGENT-CTX: Some PubMed records have no abstract. fetch_abstracts must
    return abstract="" (not None, not raise) for such records.
    This is a documented invariant in pubmed.py.
    """
    # AGENT-CTX: Uses a query known to return records with sparse abstracts.
    # If this flakes, swap query for one with confirmed abstract-less records.
    results = await fetch_abstracts("KRAS G12C", limit=10)
    for r in results:
        assert r["abstract"] is not None, "abstract must never be None"


@pytest.mark.asyncio
async def test_fetch_raises_on_empty_query():
    """Empty query must raise ValueError before hitting the network."""
    with pytest.raises((ValueError, RuntimeError)):
        await fetch_abstracts("", limit=10)
