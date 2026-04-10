"""
FastAPI application entry point.

AGENT-CTX: Milestone 3 — async job endpoints (POST /jobs, GET /job/{id}, GET /jobs)
with a lifespan that initialises SQLite + the ARQ Redis pool.

AGENT-CTX: CORS includes POST in allow_methods for /jobs and DELETE for /job/{id}.
"""

import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.logging_config import setup_logging
from backend.graph import CHAIN_LAYER_ORDER, EVIDENCE_TYPE_TO_LAYER, LAYER_NAMES
from backend.db.jobs import create_job, delete_job, get_job, get_job_filter, list_jobs
from backend.db.models import (
    JobFilter,
    JobListItem,
    JobStatusResponse,
    JobSubmitRequest,
    JobSubmitResponse,
)
from backend.db.schema import get_db, init_db
from backend.models import ErrorResponse


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
    setup_logging()
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
    version="0.4.0",
    description="Drug target evidence aggregation — async job pipeline",
    lifespan=lifespan,
)

# AGENT-CTX: allow_methods includes DELETE for the DELETE /job/{job_id} endpoint.
# Do NOT remove GET — health check and job polling all use GET.
_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# ── Rate limiting ──────────────────────────────────────────────────────────────
#
# AGENT-CTX: This is a lightweight in-process safety net to prevent accidental or
# malicious flooding of the job queue (which consumes Groq API quota and SQLite space).
#
# TODO: Move this to an API gateway (Cloudflare, AWS API GW, or similar) before
# scaling beyond a single instance. Limitations of this approach:
#   - State is in-memory and per-process — resets on restart, does not apply across
#     multiple instances if the service is ever horizontally scaled.
#   - The _ip_log dict grows unbounded with unique IPs over time (harmless at demo
#     traffic volumes; add periodic cleanup or use Redis for production).
#   - X-Forwarded-For is trusted as-is — can be spoofed by a caller that bypasses
#     Render's proxy layer. An API gateway handles this correctly.

_RATE_LIMIT_REQUESTS: int = int(os.environ.get("RATE_LIMIT_REQUESTS", "10"))
_RATE_LIMIT_WINDOW_S: int = int(os.environ.get("RATE_LIMIT_WINDOW_S", "60"))
# Maps client IP → deque of request timestamps within the current window
_ip_log: dict[str, deque[float]] = defaultdict(deque)


def _check_rate_limit(request: Request) -> None:
    """
    Raise HTTP 429 if the client IP has exceeded the per-window request limit.

    Uses a sliding window: only timestamps within the last RATE_LIMIT_WINDOW_S
    seconds are counted. Old entries are evicted in-place before each check.

    AGENT-CTX: Prefer X-Forwarded-For (set by Render's edge proxy) over the raw
    TCP client IP. Render always sets this header; request.client.host would give
    the proxy's internal IP instead of the real caller. Split on comma and take
    the leftmost value — that is the original client IP in standard proxy chains.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    ip = forwarded.split(",")[0].strip() if forwarded else (
        request.client.host if request.client else "unknown"
    )

    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW_S
    log = _ip_log[ip]

    # Evict timestamps that have aged out of the window
    while log and log[0] < window_start:
        log.popleft()

    if len(log) >= _RATE_LIMIT_REQUESTS:
        retry_after = int(log[0] + _RATE_LIMIT_WINDOW_S - now) + 1
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded: max {_RATE_LIMIT_REQUESTS} job submissions "
                f"per {_RATE_LIMIT_WINDOW_S}s. Retry after {retry_after}s."
            ),
        )

    log.append(now)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    # AGENT-CTX: Render health check. Must stay dependency-free. Do not add DB or
    # Redis checks here — if either is down the service should still return 200 so
    # Render does not mark the deploy as failed.
    return {"status": "ok"}


@app.get(
    "/health/worker",
    responses={
        503: {"model": ErrorResponse, "description": "Redis not configured or unreachable"},
    },
)
async def health_worker(request: Request) -> dict:
    """
    Deep health check for the job queue subsystem.

    Returns 200 only when the ARQ Redis pool is configured AND reachable.
    Use this endpoint to diagnose worker failures that are invisible to /health.

    AGENT-CTX: This endpoint is intentionally separate from /health. Render's
    healthCheckPath must point to /health (always 200) so a Redis outage does
    not cause Render to restart the web container in a loop. /health/worker is
    for operator use — call it manually, in a monitoring script, or from a
    separate uptime check that can tolerate 503 without triggering a redeploy.

    Status values:
      "ok"                  — pool configured and Redis responded to PING
      "redis_not_configured" — REDIS_URL was not set at startup (arq_pool is None)
      "redis_unreachable"   — pool exists but PING failed (Redis down or network error)
    """
    pool = getattr(request.app.state, "arq_pool", None)

    if pool is None:
        raise HTTPException(
            status_code=503,
            detail="redis_not_configured: REDIS_URL was not set at startup. "
                   "POST /jobs will return 503 — jobs cannot be enqueued.",
        )

    try:
        await pool.ping()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"redis_unreachable: Redis PING failed — {exc}",
        ) from exc

    return {"status": "ok"}


# ── Application metadata ──────────────────────────────────────────────────────

@app.get("/meta")
async def get_meta() -> dict:
    """
    Return static layer metadata so the frontend stays in sync with graph.py.

    layer_names keys are JSON strings — the frontend converts back to numbers.
    chain_layer_order is the authoritative evidence hierarchy sequence.
    """
    return {
        "layer_names": {str(k): v for k, v in LAYER_NAMES.items()},
        "chain_layer_order": CHAIN_LAYER_ORDER,
        "evidence_type_to_layer": EVIDENCE_TYPE_TO_LAYER,
    }


# ── Async job endpoints ────────────────────────────────────────────────────────

@app.post(
    "/jobs",
    response_model=JobSubmitResponse,
    status_code=202,
    responses={
        422: {"model": ErrorResponse, "description": "Missing or invalid query"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded — too many submissions"},
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
    _check_rate_limit(request)

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


@app.delete("/job/{job_id}", status_code=204)
async def delete_job_endpoint(job_id: str, db=Depends(get_db)) -> None:
    """Delete a job record. Returns 204 on success, 404 if not found."""
    deleted = await delete_job(db, job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Job not found")
