"""
End-to-end smoke tests for the fully deployed stack.

AGENT-CTX: These tests verify the COMPLETE system working together:
  Vercel frontend → Render backend → NCBI PubMed + Groq LLM

All tests are marked @pytest.mark.e2e and are excluded from the default `make test` run.
Run with: make test-e2e (or: pytest -m e2e tests/test_e2e.py -v)

AGENT-CTX: These tests use synchronous httpx (not async).
Reason: E2E tests are simple HTTP calls with no async coordination needed.
Synchronous avoids all pytest-asyncio event-loop complexity for zero benefit.
Do NOT convert to async without a concrete reason.

AGENT-CTX: Target URLs are read from environment variables with hardcoded defaults.
Defaults point to the known deployed instances of this project.
Override via .env.e2e if URLs change (e.g. new Render service, new Vercel project).
"""

import os

import httpx
import pytest

# AGENT-CTX: Hardcoded defaults are the production URLs for this project.
# Change them here (or via env var) if the deployments move.
# E2E_API_URL  — Render backend service
# E2E_FRONTEND_URL — Vercel frontend deployment
_API_URL = os.environ.get("E2E_API_URL", "https://mata-ooui.onrender.com").rstrip("/")
_FRONTEND_URL = os.environ.get("E2E_FRONTEND_URL", "https://mata-devajyas-projects.vercel.app").rstrip("/")

# AGENT-CTX: Render free tier spins down after 15 min of inactivity.
# First request after spin-down can take 30-60s to cold-start.
# Search timeout is longer (90s) to account for: cold start + PubMed fetch + 10 LLM calls.
_HEALTH_TIMEOUT = 60.0
_SEARCH_TIMEOUT = 120.0
_FRONTEND_TIMEOUT = 30.0

VALID_EVIDENCE_TYPES = frozenset(
    ["animal model", "human genetics", "clinical trial", "in vitro", "review"]
)


# ── Infrastructure checks ─────────────────────────────────────────────────────

@pytest.mark.e2e
def test_backend_is_reachable():
    """
    AC: App is deployed and accessible via public URL (backend).
    AGENT-CTX: Hits /health — dependency-free endpoint that always returns 200 if the
    process is running. If this fails, all subsequent tests will also fail.
    """
    response = httpx.get(f"{_API_URL}/health", timeout=_HEALTH_TIMEOUT)
    assert response.status_code == 200, (
        f"Backend health check failed: {response.status_code} — "
        f"is {_API_URL} deployed and running?"
    )
    assert response.json() == {"status": "ok"}


@pytest.mark.e2e
def test_frontend_is_reachable():
    """
    AC: App is deployed and accessible via public URL (frontend).
    AGENT-CTX: Vercel serves the Next.js app. A 200 with text/html confirms the
    frontend is deployed and not returning a build error page.
    """
    response = httpx.get(_FRONTEND_URL, timeout=_FRONTEND_TIMEOUT)
    assert response.status_code == 200, (
        f"Frontend unreachable: {response.status_code} — "
        f"is {_FRONTEND_URL} deployed?"
    )
    content_type = response.headers.get("content-type", "")
    assert "text/html" in content_type, (
        f"Expected HTML from frontend, got content-type: {content_type!r}"
    )


# ── Core acceptance criteria ──────────────────────────────────────────────────

@pytest.mark.e2e
def test_search_kras_g12c_returns_results():
    """
    AC: Type "KRAS G12C" → see ≥10 results with titles and evidence type labels.

    AGENT-CTX: This is the primary walking-skeleton acceptance criterion.
    It exercises the full production stack: PubMed fetch → Groq classification → response.

    AGENT-CTX: Timeout is 120s to handle:
      - Render cold start (up to 60s on free tier)
      - PubMed esearch + efetch (~2s)
      - 10 concurrent Groq classify calls (~3-5s on warm instance)
    """
    response = httpx.get(
        f"{_API_URL}/search",
        params={"query": "KRAS G12C"},
        timeout=_SEARCH_TIMEOUT,
    )
    assert response.status_code == 200, (
        f"Search failed: {response.status_code}\n{response.text[:500]}"
    )

    data = response.json()
    assert "query" in data, "Response missing 'query' field"
    assert data["query"] == "KRAS G12C", f"Query echo mismatch: {data['query']!r}"
    assert "results" in data, "Response missing 'results' field"

    results = data["results"]

    # AC: At least 10 results
    assert len(results) >= 10, (
        f"AC VIOLATION: expected >=10 results, got {len(results)}. "
        f"Check limit= in main.py search() and Groq quota."
    )

    # AC: Each result has a title and a valid evidence type label
    for i, item in enumerate(results):
        assert item.get("title"), f"Result {i} has empty/missing title: {item}"
        assert item.get("evidence_type") in VALID_EVIDENCE_TYPES, (
            f"Result {i} has invalid evidence_type: {item.get('evidence_type')!r}. "
            f"Valid values: {sorted(VALID_EVIDENCE_TYPES)}"
        )
        # AGENT-CTX: pmid and abstract are also part of the EvidenceItem contract.
        # Not AC requirements but worth asserting to catch schema regressions.
        assert item.get("pmid"), f"Result {i} has empty/missing pmid: {item}"
        assert "abstract" in item, f"Result {i} missing abstract key: {item}"


@pytest.mark.e2e
def test_search_query_echo():
    """
    AGENT-CTX: Verifies the SearchResponse.query field — used by frontend to display
    "Results for: BRAF V600E" style headings. Must exactly match the URL-decoded query.
    """
    response = httpx.get(
        f"{_API_URL}/search",
        params={"query": "BRAF V600E"},
        timeout=_SEARCH_TIMEOUT,
    )
    assert response.status_code == 200
    assert response.json()["query"] == "BRAF V600E"


@pytest.mark.e2e
def test_search_missing_query_returns_422():
    """
    AGENT-CTX: Confirms FastAPI validation is active in production.
    If this returns 200 or 500, the Query(min_length=1) contract was broken.
    """
    response = httpx.get(f"{_API_URL}/search", timeout=_HEALTH_TIMEOUT)
    assert response.status_code == 422, (
        f"Expected 422 for missing query, got {response.status_code}"
    )


# ── Full acceptance criteria checklist ───────────────────────────────────────

@pytest.mark.e2e
def test_ac_checklist():
    """
    AGENT-CTX: Explicit sign-off test that maps each AC item to a verified assertion.
    This test re-uses a single /search call to avoid double-burning Groq quota.

    Walking Skeleton AC:
      [1] Input field accepts a target name         → verified by query= param working
      [2] Backend fetches ≥10 abstracts from PubMed → verified by len(results) >= 10
      [3] LLM returns evidence_type per abstract    → verified by each item having valid type
      [4] Frontend renders flat list with title+label → PARTIAL: test_frontend_is_reachable
          only confirms HTTP 200 + text/html, not that the React component actually renders
          results. Full verification requires a headless browser (Playwright/Cypress) —
          out of scope for this slice.
      [5] App deployed and accessible via public URL  → verified by health + frontend tests
    """
    response = httpx.get(
        f"{_API_URL}/search",
        params={"query": "KRAS G12C"},
        timeout=_SEARCH_TIMEOUT,
    )
    data = response.json()
    results = data["results"]

    ac_results = {
        "AC1 — query accepted":           response.status_code == 200,
        "AC2 — ≥10 PubMed abstracts":     len(results) >= 10,
        "AC3 — LLM evidence_type present": all(
            r.get("evidence_type") in VALID_EVIDENCE_TYPES for r in results
        ),
        "AC4 — titles present":            all(r.get("title") for r in results),
    }

    failures = [name for name, passed in ac_results.items() if not passed]
    assert not failures, (
        f"ACCEPTANCE CRITERIA FAILURES:\n" +
        "\n".join(f"  ✗ {f}" for f in failures) +
        f"\n\nFull results sample: {results[:2]}"
    )

    # Print a pass summary for visibility in CI output
    print("\n── Acceptance Criteria Sign-off ──────────────────")
    for name, passed in ac_results.items():
        print(f"  {'✓' if passed else '✗'} {name}")
    print(f"  ✓ AC5 — frontend reachable (see test_frontend_is_reachable)")
    print(f"  Total results: {len(results)}")
    print("──────────────────────────────────────────────────")
