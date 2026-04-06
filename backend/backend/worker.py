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

from backend.confidence import ConfidenceEngine, SubjectTypeFactor
from backend.db.jobs import set_job_complete, set_job_failed, set_job_running
from backend.db.schema import _get_db_path, init_db
from backend.edges import compute_all_edges
from backend.graph import assign_layer
from backend.llm import extract_structured_evidence
from backend.models import EvidenceItem, SearchResponse
from backend.provider import get_provider_config, probe_ollama_concurrency
from backend.pubmed import fetch_abstracts

logger = logging.getLogger(__name__)

# AGENT-CTX: Module-level engine mirrors main.py's _engine. Both must produce
# identical confidence_tier values for the same StructuredEvidence input.
# If you add/remove factors in main.py, update this line too.
_engine = ConfidenceEngine().register(SubjectTypeFactor())


async def _extract_with_semaphore(
    sem: asyncio.Semaphore,
    title: str,
    abstract: str,
):
    """
    Gate a single extract_structured_evidence() call behind a semaphore.

    AGENT-CTX: The semaphore value comes from provider.py's ProviderConfig
    (built once in startup(), stored in ctx). For Ollama CPU this is 1 —
    making asyncio.gather() effectively sequential and preventing the
    TimeoutError described in the module docstring. For Groq this is 10.
    This function is a thin wrapper so monkeypatching extract_structured_evidence
    in tests still works — only the semaphore logic lives here.
    """
    async with sem:
        return await extract_structured_evidence(title, abstract)


async def run_search_job(ctx: dict, job_id: str, query: str) -> None:
    """
    Execute a search job: PubMed fetch → structured extraction → scoring → edge computation → persist.

    AGENT-CTX: ctx carries the semaphores built in startup():
        ctx["extraction_semaphore"] — gates concurrent extract_structured_evidence calls
        ctx["provider_config"]      — ProviderConfig instance (for logging/debugging)
    If ctx is missing these keys (e.g. in unit tests that call run_search_job directly),
    the .get() calls fall back to a permissive Semaphore(10) so tests are not blocked.

    AGENT-CTX: Error strategy:
      - Empty PubMed results → set_job_failed with user-facing message (not a system error)
      - RuntimeError from fetch_abstracts → set_job_failed
      - RuntimeError from extract_structured_evidence → set_job_failed
      - Any other Exception → set_job_failed (broad catch prevents worker process crash)
      - Edge computation failures are caught INSIDE compute_all_edges() — they never
        propagate here. A job with failed edges still completes with edges=[].
    All failures are stored in the DB so the frontend can surface a human-readable message.
    """
    # AGENT-CTX: Fall back to Semaphore(10) if ctx lacks the key — keeps unit tests
    # that call run_search_job() directly without a full startup() working correctly.
    extraction_sem: asyncio.Semaphore = ctx.get(
        "extraction_semaphore", asyncio.Semaphore(10)
    )

    async with aiosqlite.connect(_get_db_path()) as db:
        db.row_factory = aiosqlite.Row
        await set_job_running(db, job_id)

        try:
            # AGENT-CTX: PUBMED_LIMIT defaults to 10 (production). Set to 5 in
            # .env.local for Ollama CPU dev — halves extraction time without losing
            # enough papers to prevent edge formation between different evidence types.
            # Do not lower below 5: fewer papers reduces edge diversity significantly.
            limit = int(os.environ.get("PUBMED_LIMIT", "10"))
            records = await fetch_abstracts(query, limit=limit)

            if not records:
                # AGENT-CTX: Domain outcome, not a system error — keep message user-facing.
                await set_job_failed(
                    db, job_id,
                    f"PubMed returned no results for '{query}'. Try a broader search term.",
                )
                return

            # AGENT-CTX: _extract_with_semaphore enforces provider-appropriate concurrency.
            # For Ollama CPU (semaphore=1) this is effectively sequential — only one HTTP
            # call is live at a time, preventing the connection-queue timeout described in
            # the module docstring. For Groq (semaphore=10) it is fully concurrent.
            # asyncio.gather() still owns coroutine scheduling; the semaphore only gates
            # how many coroutines enter the actual HTTP call simultaneously.
            structured_results = await asyncio.gather(
                *[_extract_with_semaphore(extraction_sem, r["title"], r["abstract"])
                  for r in records]
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

            # AGENT-CTX: Edge computation runs AFTER all items are built so that
            # compute_all_edges() has access to both EvidenceItem.layer (graph metadata,
            # needed for adjacency comparisons) and StructuredEvidence fields (intervention,
            # key_claim, etc.). The two lists are parallel: same index = same paper.
            #
            # AGENT-CTX: compute_all_edges() never raises — all failures return [].
            # A job that produces 0 edges is still marked complete (not failed).
            # The frontend renders the graph without connection lines in that case.
            #
            # AGENT-CTX: structured_results is a tuple from asyncio.gather — convert
            # to list for compute_all_edges() which expects list[StructuredEvidence].
            edges = await compute_all_edges(results, list(structured_results))

            await set_job_complete(
                db, job_id, SearchResponse(query=query, results=results, edges=edges)
            )

        except asyncio.CancelledError:
            # AGENT-CTX: CancelledError is BaseException, not Exception — the broad
            # except below never catches it. ARQ raises this when job_timeout (300s)
            # is exceeded. We must mark the job failed in SQLite before re-raising
            # so the frontend can surface a readable error instead of polling forever.
            # Re-raise is mandatory: ARQ needs the cancellation to propagate so it
            # can clean up its own bookkeeping for this job.
            await set_job_failed(
                db, job_id,
                "Search timed out after 900 seconds. Try a more specific query."
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
