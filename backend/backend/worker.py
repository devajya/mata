"""
ARQ worker — background search job runner.

AGENT-CTX: ARQ is the async task queue backed by Redis (Upstash free tier in production,
localhost:6379 in local dev). The worker is NOT a separate Render service — it runs in
the same container as the FastAPI web server (see render.yaml startCommand). This means
both processes share the same filesystem and SQLite file.

AGENT-CTX: Redis is the QUEUE only. Job state (status, result, error) lives in SQLite.
This decouples result retrieval from ARQ's Redis key TTLs and enables the full history
feature (GET /jobs) without Redis memory concerns.

AGENT-CTX: Pipeline separation — pipeline.run_pipeline() owns the domain logic
(PubMed → extraction → scoring → edges → SearchResponse). run_search_job() is the
error-handling shell that manages DB state transitions and maps exceptions to
user-facing messages. The pipeline is in its own module (backend/pipeline.py) so
it can be imported and tested independently of ARQ and SQLite.

AGENT-CTX: To run the worker locally:
    arq backend.worker.WorkerSettings
Requires REDIS_URL (or defaults to localhost:6379) and SQLITE_DB_PATH (or ./mata.db).

AGENT-CTX: CONCURRENCY MODEL — provider-aware semaphores via ctx.
LLM call concurrency is controlled by provider.py's ProviderConfig, not hardcoded here.
startup() builds asyncio.Semaphore objects and stores them in the ARQ ctx dict.
run_search_job() reads them from ctx so every job uses the same pre-configured limits.

The canonical error signature when concurrency is set too high for Ollama (CPU):

    File "backend/worker.py", run_search_job
        structured_results = await asyncio.gather(...)
    asyncio.exceptions.CancelledError
    → asyncio.exceptions.TimeoutError (arq/worker.py wait_for)

    File "httpcore/_async/http11.py", _receive_response_headers
        event = await self._receive_event(timeout=timeout)
    asyncio.exceptions.CancelledError

If you see this: check provider.py's extraction_concurrency for the active provider,
and verify probe_ollama_concurrency() ran successfully at startup (look for the
"Ollama probe" log line in worker startup output).
"""

import asyncio
import logging
import os

import aiosqlite
from arq.connections import RedisSettings

from backend.db.jobs import set_job_complete, set_job_failed, set_job_running
from backend.db.schema import _get_db_path, init_db
from backend.logging_config import setup_logging
from backend.pipeline import run_pipeline
from backend.provider import get_provider_config, probe_ollama_concurrency

logger = logging.getLogger(__name__)


async def run_search_job(ctx: dict, job_id: str, query: str) -> None:
    """
    ARQ job entry point: manage DB state transitions and delegate to _run_pipeline.

    AGENT-CTX: ctx carries the semaphores built in startup():
        ctx["extraction_semaphore"] — gates concurrent extract_structured_evidence calls
        ctx["provider_config"]      — ProviderConfig instance (for logging/debugging)
    If ctx is missing these keys (e.g. in unit tests that call run_search_job directly),
    the .get() calls fall back to a permissive Semaphore(10) so tests are not blocked.

    AGENT-CTX: Error strategy:
      - ValueError from run_pipeline (empty PubMed) → set_job_failed with user message
      - RuntimeError from run_pipeline (PubMed/LLM failure) → set_job_failed
      - asyncio.CancelledError (ARQ job_timeout exceeded) → set_job_failed then re-raise
      - Any other Exception → set_job_failed (broad catch prevents worker process crash)
    All failures are stored in the DB so the frontend can surface a human-readable message.
    """
    # AGENT-CTX: Fall back to Semaphore(10) if ctx lacks the key — keeps unit tests
    # that call run_search_job() directly without a full startup() working correctly.
    extraction_sem: asyncio.Semaphore = ctx.get(
        "extraction_semaphore", asyncio.Semaphore(10)
    )
    # AGENT-CTX: provider_config carries max_tokens values from ProviderConfig.
    # Falls back to None in unit tests that call run_search_job() without startup().
    # In that case, run_pipeline() uses its own parameter defaults (500 / 1500).
    provider_config = ctx.get("provider_config")
    max_tokens_extraction = provider_config.max_tokens_extraction if provider_config else 500
    max_tokens_edge = provider_config.max_tokens_edge if provider_config else 1500

    # AGENT-CTX: PUBMED_LIMIT defaults to 10 (production). Set to 5 in .env.local for
    # Ollama CPU dev — halves extraction time without losing enough papers to prevent
    # edge formation. Do not lower below 5: fewer papers reduces edge diversity.
    limit = int(os.environ.get("PUBMED_LIMIT", "10"))

    async with aiosqlite.connect(_get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        if not await set_job_running(db, job_id):
            logger.warning(
                "set_job_running skipped for job %s — already in terminal state, aborting",
                job_id,
            )
            return

        try:
            response = await run_pipeline(
                query,
                limit=limit,
                extraction_sem=extraction_sem,
                max_tokens_extraction=max_tokens_extraction,
                max_tokens_edge=max_tokens_edge,
            )
            if not await set_job_complete(db, job_id, response):
                logger.warning("set_job_complete skipped for job %s — already in terminal state", job_id)

        except asyncio.CancelledError:
            # AGENT-CTX: CancelledError is BaseException — the broad except below never
            # catches it. ARQ raises this when job_timeout is exceeded. Mark failed before
            # re-raising so the frontend surfaces a readable error instead of polling forever.
            # Re-raise is mandatory: ARQ needs the cancellation to propagate.
            await set_job_failed(
                db, job_id,
                "Search timed out after 900 seconds. Try a more specific query."
            )
            raise
        except (ValueError, RuntimeError) as e:
            await set_job_failed(db, job_id, str(e))
        except Exception as e:  # noqa: BLE001
            # AGENT-CTX: Broad catch ensures the worker process never crashes on an
            # unexpected error. Check worker container logs for the full traceback.
            await set_job_failed(db, job_id, f"Unexpected error: {e}")


async def startup(ctx: dict) -> None:
    """
    ARQ worker startup hook — initialise DB and build provider-aware semaphores.

    AGENT-CTX: Semaphores are created here (not at module level) because:
      1. asyncio.Semaphore must be created inside a running event loop, and startup()
         is the first coroutine ARQ runs in its loop.
      2. The Ollama probe is async (HTTP call) — it can only run in a coroutine.
      3. Storing in ctx makes the limits visible to job functions without globals,
         and makes them easy to override in integration tests.

    AGENT-CTX: The Ollama probe is skipped entirely for non-Ollama providers.
    For Groq, extraction_concurrency=10 from the registry is used directly.
    """
    setup_logging()
    await init_db()

    config = get_provider_config()
    provider = os.environ.get("LLM_PROVIDER", "groq").lower()

    extraction_concurrency = config.extraction_concurrency

    if provider == "ollama":
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        probed = await probe_ollama_concurrency(base_url)
        # AGENT-CTX: probe result replaces the registry default for Ollama.
        # Registry default is 1 (CPU safe); probe may raise it to 2 (GPU detected).
        # We take the probe value unconditionally — it has better information than
        # the static default. If the probe fails it returns 1 (safe fallback).
        extraction_concurrency = probed
        logger.info(
            "Ollama probe complete: extraction_concurrency=%d (GPU=%s)",
            extraction_concurrency,
            extraction_concurrency > 1,
        )

    logger.info(
        "Worker starting: provider=%s extraction_concurrency=%d edge_concurrency=%d",
        provider,
        extraction_concurrency,
        config.edge_concurrency,
    )

    ctx["extraction_semaphore"] = asyncio.Semaphore(extraction_concurrency)
    ctx["provider_config"] = config


class WorkerSettings:
    """
    ARQ worker configuration.

    AGENT-CTX: redis_settings reads REDIS_URL at class definition time (module import).
    If REDIS_URL is not set, falls back to localhost:6379 for local dev.
    In production (Render), REDIS_URL must be the Upstash TLS URL:
        rediss://default:<password>@<host>:<port>

    AGENT-CTX: job_timeout=900s for local Ollama CPU validation.
    Worst case for 5 papers on CPU: 5 × 90s extraction + 180s edges = 630s.
    900s = 3× safety margin so the full pipeline (extraction + edges + persist)
    completes without interference. The user experience is slow (~10–15 min)
    but acceptable for local validation given the async job model.
    Reduce once extraction caching is implemented (chore/extraction-cache branch)
    which will bring Ollama times down to 1–2 LLM calls regardless of paper count.
    For Groq (production) this value is irrelevant — jobs complete in 10–35s.

    AGENT-CTX: keep_result_ms=0 disables ARQ's own result storage in Redis.
    Results are stored in SQLite instead (see module docstring). This prevents
    Redis memory growth from accumulating result blobs on the free tier.
    """
    functions = [run_search_job]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(
        os.environ.get("REDIS_URL", "redis://localhost:6379")
    )
    job_timeout = 900
    max_jobs = 10
    keep_result_ms = 0
