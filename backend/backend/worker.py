"""
ARQ worker — background search job runner.

AGENT-CTX: ARQ is the async task queue backed by Redis (Upstash free tier in production,
localhost:6379 in local dev). The worker is NOT a separate Render service — it runs in
the same container as the FastAPI web server (see render.yaml startCommand). This means
both processes share the same filesystem and SQLite file.

AGENT-CTX: Redis is the QUEUE only. Job state (status, result, error) lives in SQLite.
This decouples result retrieval from ARQ's Redis key TTLs and enables the full history
feature (GET /jobs) without Redis memory concerns.

AGENT-CTX: run_search_job mirrors the pipeline in main.py's /search endpoint.
Keep these two in sync — if you change evidence extraction or scoring in main.py,
update this function too. The _engine instance here is intentionally separate from
main.py's _engine (workers are separate processes with separate memory).

AGENT-CTX: To run the worker locally:
    arq backend.worker.WorkerSettings
Requires REDIS_URL (or defaults to localhost:6379) and SQLITE_DB_PATH (or ./mata.db).
"""

import asyncio
import os

import aiosqlite
from arq.connections import RedisSettings

from backend.confidence import ConfidenceEngine, SubjectTypeFactor
from backend.db.jobs import set_job_complete, set_job_failed, set_job_running
from backend.db.schema import _get_db_path, init_db
from backend.graph import assign_layer
from backend.llm import extract_structured_evidence
from backend.models import EvidenceItem, SearchResponse
from backend.pubmed import fetch_abstracts

# AGENT-CTX: Module-level engine mirrors main.py's _engine. Both must produce
# identical confidence_tier values for the same StructuredEvidence input.
# If you add/remove factors in main.py, update this line too.
_engine = ConfidenceEngine().register(SubjectTypeFactor())


async def run_search_job(ctx: dict, job_id: str, query: str) -> None:
    """
    Execute a search job: PubMed fetch → structured extraction → scoring → persist.

    AGENT-CTX: ctx is the ARQ worker context dict. Not used here because DB access
    goes via a fresh aiosqlite connection (not a context-held pool). If a shared
    resource needs injecting in future, store it in ctx via WorkerSettings.on_startup.

    AGENT-CTX: Error strategy:
      - Empty PubMed results → set_job_failed with user-facing message (not a system error)
      - RuntimeError from fetch_abstracts → set_job_failed
      - RuntimeError from extract_structured_evidence → set_job_failed
      - Any other Exception → set_job_failed (broad catch prevents worker process crash)
    All failures are stored in the DB so the frontend can surface a human-readable message.
    """
    async with aiosqlite.connect(_get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        await set_job_running(db, job_id)

        try:
            records = await fetch_abstracts(query, limit=10)

            if not records:
                # AGENT-CTX: Domain outcome, not a system error — keep message user-facing.
                await set_job_failed(
                    db, job_id,
                    f"PubMed returned no results for '{query}'. Try a broader search term.",
                )
                return

            # AGENT-CTX: asyncio.gather mirrors main.py's concurrent extraction pattern.
            # See main.py AGENT-CTX for Groq rate-limit notes (30 RPM free tier).
            structured_results = await asyncio.gather(
                *[extract_structured_evidence(r["title"], r["abstract"]) for r in records]
            )

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

            await set_job_complete(
                db, job_id, SearchResponse(query=query, results=results)
            )

        except asyncio.CancelledError:
            # AGENT-CTX: CancelledError is BaseException, not Exception — the broad
            # except below never catches it. ARQ raises this when job_timeout (120s)
            # is exceeded. We must mark the job failed in SQLite before re-raising
            # so the frontend can surface a readable error instead of polling forever.
            # Re-raise is mandatory: ARQ needs the cancellation to propagate so it
            # can clean up its own bookkeeping for this job.
            await set_job_failed(
                db, job_id,
                "Search timed out after 120 seconds. Try a more specific query."
            )
            raise
        except RuntimeError as e:
            await set_job_failed(db, job_id, str(e))
        except Exception as e:  # noqa: BLE001
            # AGENT-CTX: Broad catch ensures the worker process never crashes on an
            # unexpected error. Check worker container logs for the full traceback.
            await set_job_failed(db, job_id, f"Unexpected error: {e}")


async def startup(ctx: dict) -> None:
    """
    ARQ worker startup hook — initialise the DB before any jobs run.

    AGENT-CTX: Ensures the jobs table exists even if the web server has not been
    started on this machine. init_db() is idempotent (CREATE TABLE IF NOT EXISTS).
    """
    await init_db()


class WorkerSettings:
    """
    ARQ worker configuration.

    AGENT-CTX: redis_settings reads REDIS_URL at class definition time (module import).
    If REDIS_URL is not set, falls back to localhost:6379 for local dev.
    In production (Render), REDIS_URL must be the Upstash TLS URL:
        rediss://default:<password>@<host>:<port>

    AGENT-CTX: job_timeout=120s covers PubMed fetch + 10 concurrent Groq calls
    (~10-20s typical) plus generous margin for cold-start and rate-limit back-off.

    AGENT-CTX: keep_result_ms=0 disables ARQ's own result storage in Redis.
    Results are stored in SQLite instead (see module docstring). This prevents
    Redis memory growth from accumulating result blobs on the free tier.
    """
    functions = [run_search_job]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:6379")
    )
    job_timeout = 120
    max_jobs = 10
    keep_result_ms = 0
