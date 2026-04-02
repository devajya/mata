"""
Tests for the async job pipeline: POST /jobs, GET /job/{id}, GET /jobs, ARQ worker.

AGENT-CTX: Two test tiers:
  [ENDPOINT] — HTTP via AsyncClient. ARQ pool is mocked (no Redis). SQLite uses
               a temp file isolated per test via tmp_path + monkeypatch.setenv.
  [WORKER]   — Direct calls to run_search_job(). PubMed + Groq are mocked.
               Uses the same temp-file DB isolation.

AGENT-CTX: DB isolation strategy:
  monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test.db")) overrides
  _get_db_path() in both db/schema.py and worker.py (both read os.environ at
  call time, not at import time — see schema.py AGENT-CTX for why).

AGENT-CTX: Redis isolation strategy:
  create_pool is patched to return an AsyncMock pool. REDIS_URL is set so the
  lifespan enters the pool-creation branch and hits the mock. No real Redis
  connection is attempted.

AGENT-CTX: The existing tests in test_search_endpoint.py cover GET /search.
Those tests (and the endpoint itself) are marked deprecated — see main.py.
"""

from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
from httpx import ASGITransport, AsyncClient

from backend.db.models import JobStatus
from backend.db.schema import _create_tables, init_db
from backend.main import app
from backend.models import StructuredEvidence

# ── Shared fixtures ────────────────────────────────────────────────────────────

MOCK_STRUCTURED = StructuredEvidence(
    evidence_type="clinical trial",
    effect_direction="supports",
    model_organism="not reported",
    sample_size="not reported",
)

MOCK_RECORDS = [
    {"pmid": f"1234{i:04d}", "title": f"Study {i}", "abstract": f"Abstract {i}."}
    for i in range(10)
]


@pytest.fixture
async def job_client(tmp_path, monkeypatch):
    """
    AsyncClient with isolated SQLite DB and mocked ARQ pool.

    AGENT-CTX: httpx's ASGITransport does NOT trigger ASGI lifespan events — it
    only handles HTTP scope. We therefore manually call init_db() and set
    app.state.arq_pool ourselves instead of relying on the lifespan. This matches
    the pattern used by the existing tests in test_search_endpoint.py (which also
    bypass lifespan). The pool is cleared in teardown to avoid cross-test bleed.

    AGENT-CTX: SQLITE_DB_PATH is set before init_db() so the temp file is used.
    _get_db_path() reads from os.environ at call time — the monkeypatch override
    takes effect for all subsequent DB calls in this test.
    """
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "test_jobs.db"))

    mock_pool = AsyncMock()
    mock_pool.enqueue_job = AsyncMock(return_value=None)

    await init_db()
    app.state.arq_pool = mock_pool

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        ac.mock_pool = mock_pool  # expose for enqueue_job assertions
        yield ac

    app.state.arq_pool = None  # clean up so other test modules aren't affected


@pytest.fixture
async def worker_db_path(tmp_path, monkeypatch):
    """
    Temp SQLite DB path for worker tests.

    AGENT-CTX: Yields the path string (not a connection) so each test operation
    opens its own connection — avoids concurrent-write contention between the
    fixture connection and run_search_job's internal connection.
    """
    db_path = str(tmp_path / "test_worker.db")
    monkeypatch.setenv("SQLITE_DB_PATH", db_path)
    # Initialise tables so create_job / get_job work in tests.
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        await _create_tables(db)
    return db_path


# ── Endpoint tests [ENDPOINT] ──────────────────────────────────────────────────

async def test_submit_job_returns_202_with_job_id(job_client):
    """AC1: Submitting a query returns 202, a job_id, status=pending."""
    response = await job_client.post("/jobs", json={"query": "KRAS G12C"})
    assert response.status_code == 202
    data = response.json()
    assert "job_id" in data
    assert len(data["job_id"]) > 0
    assert data["status"] == "pending"
    assert data["query"] == "KRAS G12C"
    assert "created_at" in data


async def test_submit_job_empty_query_returns_422(job_client):
    """AC1 validation: empty query is rejected before job creation."""
    response = await job_client.post("/jobs", json={"query": ""})
    assert response.status_code == 422


async def test_submit_job_missing_query_returns_422(job_client):
    """AC1 validation: missing query field returns 422."""
    response = await job_client.post("/jobs", json={})
    assert response.status_code == 422


async def test_submit_job_enqueues_to_arq(job_client):
    """
    AC1: Submitting calls enqueue_job with the correct job_id and query.

    AGENT-CTX: Verifies the HTTP → ARQ bridge. If this test fails, POST /jobs
    is not dispatching to the worker queue.
    """
    response = await job_client.post("/jobs", json={"query": "BRAF V600E"})
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    job_client.mock_pool.enqueue_job.assert_called_once_with(
        "run_search_job", job_id, "BRAF V600E"
    )


async def test_poll_pending_job_returns_pending_with_null_result(job_client):
    """AC2: Polling a newly submitted job returns status=pending, result=null."""
    submit = await job_client.post("/jobs", json={"query": "KRAS G12C"})
    job_id = submit.json()["job_id"]

    response = await job_client.get(f"/job/{job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["result"] is None
    assert data["error"] is None
    assert data["job_id"] == job_id


async def test_poll_nonexistent_job_returns_404(job_client):
    """AC2: Polling a job_id that does not exist returns 404."""
    response = await job_client.get("/job/does-not-exist-xxxx")
    assert response.status_code == 404


async def test_list_jobs_returns_all_submitted_newest_first(job_client):
    """AC5: GET /jobs returns all submitted jobs, newest first."""
    await job_client.post("/jobs", json={"query": "KRAS G12C"})
    await job_client.post("/jobs", json={"query": "BRAF V600E"})

    response = await job_client.get("/jobs")
    assert response.status_code == 200
    jobs = response.json()
    assert len(jobs) == 2
    # Newest first: BRAF was submitted second
    assert jobs[0]["query"] == "BRAF V600E"
    assert jobs[1]["query"] == "KRAS G12C"


async def test_list_jobs_empty_when_none_submitted(job_client):
    """GET /jobs returns empty list when no jobs exist."""
    response = await job_client.get("/jobs")
    assert response.status_code == 200
    assert response.json() == []


async def test_job_persists_in_db_after_submission(job_client):
    """
    AC4: Job is retrievable from SQLite immediately after submission.

    AGENT-CTX: Confirms persistence (not just in-process state). The job_id
    returned by POST /jobs must resolve via GET /job/{id} in the same process.
    """
    submit = await job_client.post("/jobs", json={"query": "TP53 R175H"})
    job_id = submit.json()["job_id"]

    response = await job_client.get(f"/job/{job_id}")
    assert response.status_code == 200
    assert response.json()["job_id"] == job_id


async def test_job_filter_user_id_none_returns_all_jobs(job_client):
    """
    AC5 auth extensibility baseline: JobFilter(user_id=None) returns all jobs.

    AGENT-CTX: Verifies the no-auth default. When auth is added, user_id-scoped
    queries are tested by overriding get_job_filter in a separate fixture.
    """
    await job_client.post("/jobs", json={"query": "KRAS G12C"})
    await job_client.post("/jobs", json={"query": "EGFR T790M"})

    response = await job_client.get("/jobs")
    assert len(response.json()) == 2


# ── Worker tests [WORKER] ──────────────────────────────────────────────────────

async def test_worker_marks_job_complete_on_success(worker_db_path):
    """AC2: Worker transitions job to complete and stores a full SearchResponse."""
    from backend.db.jobs import create_job, get_job
    from backend.worker import run_search_job

    async with aiosqlite.connect(worker_db_path) as db:
        db.row_factory = aiosqlite.Row
        record = await create_job(db, "KRAS G12C")
        job_id = record.job_id

    with patch("backend.worker.fetch_abstracts", return_value=MOCK_RECORDS), \
         patch("backend.worker.extract_structured_evidence", return_value=MOCK_STRUCTURED):
        await run_search_job({}, job_id, "KRAS G12C")

    async with aiosqlite.connect(worker_db_path) as db:
        db.row_factory = aiosqlite.Row
        result = await get_job(db, job_id)

    assert result is not None
    assert result.status == JobStatus.complete
    assert result.result is not None
    assert len(result.result.results) == 10
    assert result.error is None


async def test_worker_marks_job_failed_on_pubmed_no_results(worker_db_path):
    """AC3: Zero PubMed results → job failed with human-readable message."""
    from backend.db.jobs import create_job, get_job
    from backend.worker import run_search_job

    async with aiosqlite.connect(worker_db_path) as db:
        db.row_factory = aiosqlite.Row
        record = await create_job(db, "xyzzy nonexistent target")
        job_id = record.job_id

    with patch("backend.worker.fetch_abstracts", return_value=[]):
        await run_search_job({}, job_id, "xyzzy nonexistent target")

    async with aiosqlite.connect(worker_db_path) as db:
        db.row_factory = aiosqlite.Row
        result = await get_job(db, job_id)

    assert result.status == JobStatus.failed
    assert result.error is not None
    # AGENT-CTX: Message must be user-facing. Assert on query string inclusion to
    # verify the message is specific to this search (not a generic error string).
    assert "xyzzy nonexistent target" in result.error
    assert result.result is None


async def test_worker_marks_job_failed_on_llm_failure(worker_db_path):
    """AC3: LLM RuntimeError → job failed with the exception message preserved."""
    from backend.db.jobs import create_job, get_job
    from backend.worker import run_search_job

    async with aiosqlite.connect(worker_db_path) as db:
        db.row_factory = aiosqlite.Row
        record = await create_job(db, "KRAS G12C")
        job_id = record.job_id

    with patch("backend.worker.fetch_abstracts", return_value=MOCK_RECORDS), \
         patch("backend.worker.extract_structured_evidence",
               side_effect=RuntimeError("Groq quota exceeded")):
        await run_search_job({}, job_id, "KRAS G12C")

    async with aiosqlite.connect(worker_db_path) as db:
        db.row_factory = aiosqlite.Row
        result = await get_job(db, job_id)

    assert result.status == JobStatus.failed
    assert "Groq quota exceeded" in result.error


async def test_worker_transitions_through_running_state(worker_db_path):
    """
    AC2: Worker sets status=running before completing.

    AGENT-CTX: Captures the status mid-execution to confirm the running state
    is reachable. This ensures the frontend's 'running' chip is not dead code.
    """
    from backend.db.jobs import create_job, get_job, set_job_running
    from backend.worker import run_search_job

    observed_states: list[str] = []

    original = set_job_running

    async def capturing(db, jid):
        await original(db, jid)
        row = await get_job(db, jid)
        if row:
            observed_states.append(row.status.value)

    async with aiosqlite.connect(worker_db_path) as db:
        db.row_factory = aiosqlite.Row
        record = await create_job(db, "KRAS G12C")
        job_id = record.job_id

    with patch("backend.worker.set_job_running", side_effect=capturing), \
         patch("backend.worker.fetch_abstracts", return_value=MOCK_RECORDS), \
         patch("backend.worker.extract_structured_evidence", return_value=MOCK_STRUCTURED):
        await run_search_job({}, job_id, "KRAS G12C")

    assert "running" in observed_states


# ── Live worker tests [LIVE] ───────────────────────────────────────────────────
# AGENT-CTX: These three tests exercise the full job pipeline end-to-end:
#   run_search_job() → real PubMed fetch → real LLM classification → SQLite persistence
# No Redis or running server is needed — the worker function is called directly.
# Run with: make test-local (uses Ollama) or make test-live (uses Groq).
# Requires: ollama serve + llama-3.1-8b-instant alias (for make test-local),
#           or GROQ_API_KEY in backend/.env (for make test-live).

VALID_EVIDENCE_TYPES = {
    "clinical trial", "animal model", "human genetics", "in vitro", "review"
}
VALID_EFFECT_DIRECTIONS = {"supports", "contradicts", "neutral"}
VALID_CONFIDENCE_TIERS = {"high", "medium", "low"}


@pytest.mark.live
async def test_worker_completes_real_job_via_pubmed_and_llm(worker_db_path):
    """
    [LIVE] Full pipeline: real PubMed fetch + real LLM → job transitions to complete.

    AGENT-CTX: Uses "KRAS G12C NSCLC" — a well-studied target with abundant PubMed
    literature. If PubMed rate-limits or LLM quota is exceeded, this test will fail
    with a descriptive error from the worker (not a silent hang). The test does NOT
    mock anything — it exercises the exact same code path as production.
    """
    from backend.db.jobs import create_job, get_job
    from backend.worker import run_search_job

    async with aiosqlite.connect(worker_db_path) as db:
        db.row_factory = aiosqlite.Row
        record = await create_job(db, "KRAS G12C NSCLC")
        job_id = record.job_id

    await run_search_job({}, job_id, "KRAS G12C NSCLC")

    async with aiosqlite.connect(worker_db_path) as db:
        db.row_factory = aiosqlite.Row
        result = await get_job(db, job_id)

    assert result is not None
    assert result.status == JobStatus.complete, (
        f"Expected complete, got {result.status}. Worker error: {result.error}"
    )
    assert result.result is not None
    assert len(result.result.results) >= 1
    assert result.error is None


@pytest.mark.live
async def test_worker_fails_gracefully_on_no_pubmed_results(worker_db_path):
    """
    [LIVE] Gibberish query → PubMed returns zero hits → job transitions to failed
    with a human-readable error (not an unhandled exception).

    AGENT-CTX: "xyzzyquux91827364 notarealprotein" is intentionally nonsensical.
    The worker's empty-result branch catches this and calls set_job_failed() with
    a message containing the query string. This test validates AC3 end-to-end
    against real PubMed (not a mock that might diverge from the real API behaviour).
    """
    from backend.db.jobs import create_job, get_job
    from backend.worker import run_search_job

    async with aiosqlite.connect(worker_db_path) as db:
        db.row_factory = aiosqlite.Row
        record = await create_job(db, "xyzzyquux91827364 notarealprotein")
        job_id = record.job_id

    await run_search_job({}, job_id, "xyzzyquux91827364 notarealprotein")

    async with aiosqlite.connect(worker_db_path) as db:
        db.row_factory = aiosqlite.Row
        result = await get_job(db, job_id)

    assert result.status == JobStatus.failed
    assert result.error is not None
    assert "xyzzyquux91827364 notarealprotein" in result.error
    assert result.result is None


@pytest.mark.live
async def test_worker_result_has_valid_structured_evidence_fields(worker_db_path):
    """
    [LIVE] Structured evidence fields produced by the LLM are valid members of
    their respective enums/literal sets — not arbitrary strings.

    AGENT-CTX: This test validates the full classification chain for a different
    known target (BRAF V600E) so coverage isn't artificially concentrated on
    one query. It also confirms that extract_structured_evidence() returns
    evidence_type / effect_direction / confidence_tier within the locked interface
    defined in models.py — any prompt regression that produces out-of-range values
    will surface here rather than silently corrupting the DB.
    """
    from backend.db.jobs import create_job, get_job
    from backend.worker import run_search_job

    async with aiosqlite.connect(worker_db_path) as db:
        db.row_factory = aiosqlite.Row
        record = await create_job(db, "BRAF V600E melanoma")
        job_id = record.job_id

    await run_search_job({}, job_id, "BRAF V600E melanoma")

    async with aiosqlite.connect(worker_db_path) as db:
        db.row_factory = aiosqlite.Row
        result = await get_job(db, job_id)

    assert result.status == JobStatus.complete, (
        f"Expected complete, got {result.status}. Worker error: {result.error}"
    )
    for item in result.result.results:
        assert item.evidence_type in VALID_EVIDENCE_TYPES, (
            f"Invalid evidence_type: {item.evidence_type!r}"
        )
        assert item.effect_direction in VALID_EFFECT_DIRECTIONS, (
            f"Invalid effect_direction: {item.effect_direction!r}"
        )
        assert item.confidence_tier in VALID_CONFIDENCE_TIERS, (
            f"Invalid confidence_tier: {item.confidence_tier!r}"
        )
