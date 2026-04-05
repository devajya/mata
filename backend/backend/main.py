"""
FastAPI application entry point.

AGENT-CTX: Milestone 3 adds async job endpoints (POST /jobs, GET /job/{id}, GET /jobs)
and a lifespan that initialises SQLite + the ARQ Redis pool. GET /search is deprecated
(see DEPRECATED comment below).

AGENT-CTX: CORS now includes POST in allow_methods to support the new /jobs endpoint.
"""

import asyncio
import os
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.confidence import ConfidenceEngine, SubjectTypeFactor
from backend.db.jobs import create_job, get_job, get_job_filter, list_jobs
from backend.graph import assign_layer
from backend.db.models import (
    JobFilter,
    JobListItem,
    JobStatusResponse,
    JobSubmitRequest,
    JobSubmitResponse,
)
from backend.db.schema import get_db, init_db
from backend.llm import extract_structured_evidence
from backend.models import EvidenceItem, ErrorResponse, SearchResponse
from backend.pubmed import fetch_abstracts


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup / shutdown lifecycle.

    AGENT-CTX: Startup order matters:
      1. init_db() — creates SQLite tables (idempotent, safe on every start).
      2. create_pool() — connects to Redis (Upstash in production). Only attempted
         when REDIS_URL is set. Without it, arq_pool=None and POST /jobs returns 503.
         This lets GET /health, GET /jobs, GET /job/{id} work without Redis configured,
         which is useful in local dev before Redis is set up.

    AGENT-CTX: Shutdown closes the ARQ pool gracefully. getattr guard handles the
    edge case where startup raised before pool creation (arq_pool attribute absent).
    """
    await init_db()

    redis_url = os.environ.get("REDIS_URL")
    if redis_url:
        app.state.arq_pool = await create_pool(RedisSettings.from_dsn(redis_url))
    else:
        # AGENT-CTX: arq_pool=None is a deliberate "not configured" sentinel.
        # Assigning it here (not just leaving it absent) avoids AttributeError in
        # the POST /jobs handler when REDIS_URL is unset.
        app.state.arq_pool = None

    yield

    pool = getattr(app.state, "arq_pool", None)
    if pool is not None:
        await pool.close()


app = FastAPI(
    title="MATA API",
    version="0.3.0",
    description="Drug target evidence aggregation — async job pipeline",
    lifespan=lifespan,
)

# AGENT-CTX: allow_methods now includes POST for /jobs endpoint.
# Do NOT remove GET — health check, search, and job polling all use GET.
_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# AGENT-CTX: Module-level ConfidenceEngine instance — see original main.py docstring.
_engine = (
    ConfidenceEngine()
    .register(SubjectTypeFactor())
)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    # AGENT-CTX: Render health check. Must stay dependency-free. Do not add DB or
    # Redis checks here — if either is down the service should still return 200 so
    # Render does not mark the deploy as failed.
    return {"status": "ok"}


# ── Async job endpoints ────────────────────────────────────────────────────────

@app.post(
    "/jobs",
    response_model=JobSubmitResponse,
    status_code=202,
    responses={
        422: {"model": ErrorResponse, "description": "Missing or invalid query"},
        503: {"model": ErrorResponse, "description": "Job queue not configured (REDIS_URL unset)"},
    },
)
async def submit_job(
    body: JobSubmitRequest,
    request: Request,
    db=Depends(get_db),
    job_filter: JobFilter = Depends(get_job_filter),
) -> JobSubmitResponse:
    """
    Submit a search query as a background job. Returns a job_id immediately.

    Poll GET /job/{job_id} every 3 seconds to check status.

    AGENT-CTX: user_id comes from job_filter — the auth extension point.
    Today it is always None. When auth middleware is wired, job_filter.user_id
    equals the JWT subject and the job is stored against that user.
    """
    if request.app.state.arq_pool is None:
        raise HTTPException(
            status_code=503,
            detail="Job queue not configured. Set the REDIS_URL environment variable.",
        )
    record = await create_job(db, body.query, user_id=job_filter.user_id)
    # AGENT-CTX: enqueue_job args match run_search_job(ctx, job_id, query).
    # ctx is injected by ARQ — do not pass it here.
    await request.app.state.arq_pool.enqueue_job(
        "run_search_job", record.job_id, body.query
    )
    return record


@app.get(
    "/job/{job_id}",
    response_model=JobStatusResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Job not found"},
    },
)
async def get_job_status(
    job_id: str,
    db=Depends(get_db),
) -> JobStatusResponse:
    """
    Poll job status. Returns the full SearchResponse inline when status=complete.

    AGENT-CTX: Frontend should stop polling when status is "complete" or "failed".
    Both are terminal states — they will never transition to another state.
    """
    record = await get_job(db, job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return record


@app.get(
    "/jobs",
    response_model=list[JobListItem],
)
async def list_all_jobs(
    db=Depends(get_db),
    job_filter: JobFilter = Depends(get_job_filter),
) -> list[JobListItem]:
    """
    List all jobs for the sidebar history panel, newest first.

    AGENT-CTX: job_filter controls user scoping — today returns all jobs (no auth).
    When auth is wired, only the authenticated user's jobs are returned.
    See db/jobs.py get_job_filter() for the override instructions.
    """
    return await list_jobs(db, job_filter)


# ── Deprecated synchronous search ─────────────────────────────────────────────

# AGENT-CTX: DEPRECATED — GET /search is superseded by POST /jobs + GET /job/{id}.
# This endpoint will be removed in a future slice once the async pipeline is
# confirmed stable in production.
# To remove:
#   1. Delete this handler and the fetch_abstracts / extract_structured_evidence imports.
#   2. Remove the associated tests in backend/tests/test_search_endpoint.py.
#   3. Bump the API version in app metadata above.
@app.get(
    "/search",
    response_model=SearchResponse,
    deprecated=True,
    responses={
        422: {"model": ErrorResponse, "description": "Missing or invalid query"},
        500: {"model": ErrorResponse, "description": "PubMed fetch failed"},
        502: {"model": ErrorResponse, "description": "LLM extraction failed"},
    },
)
async def search(
    query: str = Query(..., min_length=1, description="Drug target name, e.g. 'KRAS G12C'"),
) -> SearchResponse:
    """[DEPRECATED] Synchronous search. Use POST /jobs + GET /job/{id} instead."""
    try:
        records = await fetch_abstracts(query, limit=10)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"PubMed fetch failed: {e}") from e

    if not records:
        return SearchResponse(query=query, results=[])

    try:
        structured_results = await asyncio.gather(
            *[extract_structured_evidence(r["title"], r["abstract"]) for r in records]
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"LLM extraction failed: {e}") from e

    results = [
        EvidenceItem(
            pmid=record["pmid"],
            title=record["title"],
            abstract=record["abstract"],
            evidence_type=structured.evidence_type,
            effect_direction=structured.effect_direction,
            model_organism=structured.model_organism,
            sample_size=structured.sample_size,
            confidence_tier=_engine.score(structured),
            layer=assign_layer(structured.evidence_type),
            publication_year=record.get("publication_year"),
        )
        for record, structured in zip(records, structured_results)
    ]

    return SearchResponse(query=query, results=results)
