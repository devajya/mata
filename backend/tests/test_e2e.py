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

AGENT-CTX: The deprecated GET /search endpoint was removed in v0.4.0. Tests that
previously verified /search (test_search_kras_g12c_returns_results, test_search_query_echo,
test_search_missing_query_returns_422, test_ac_checklist) were removed at that point.
E2E coverage for the async job pipeline (POST /jobs → GET /job/{id}) should be added here.
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
