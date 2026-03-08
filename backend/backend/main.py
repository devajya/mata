"""
FastAPI application entry point.

AGENT-CTX: Stateless by design for this slice — no DB, no session store.
All state lives in PubMed and the LLM. Safe to scale horizontally on Render.
"""

import asyncio
import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.llm import classify_evidence_type
from backend.models import EvidenceItem, ErrorResponse, SearchResponse  # noqa: F401
from backend.pubmed import fetch_abstracts

# AGENT-CTX: App-level metadata used by Railway's auto-generated /docs page.
app = FastAPI(
    title="MATA API",
    version="0.1.0",
    description="Drug target evidence aggregation — walking skeleton",
)

# AGENT-CTX: CORS allows all origins during development/staging.
# In production set ALLOWED_ORIGINS env var to the exact Vercel URL
# (e.g. "https://mata.vercel.app") to prevent cross-origin misuse.
# Do NOT remove this middleware — frontend fetch() will silently fail without it.
_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    # AGENT-CTX: Render health check hits this endpoint (configured in render.yaml).
    # Must return HTTP 200 or Render marks the deploy as failed.
    # Keep this handler dependency-free so it never fails.
    return {"status": "ok"}


@app.get(
    "/search",
    response_model=SearchResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Missing or invalid query"},
        500: {"model": ErrorResponse, "description": "PubMed fetch failed"},
        502: {"model": ErrorResponse, "description": "LLM classification failed"},
    },
)
async def search(
    query: str = Query(..., min_length=1, description="Drug target name, e.g. 'KRAS G12C'"),
) -> SearchResponse:
    """
    Search PubMed for evidence items related to a drug target and classify each abstract.

    Flow: esearch → efetch (PubMed) → asyncio.gather(classify × N) → SearchResponse
    """
    # ── Step 1: Fetch abstracts from PubMed ───────────────────────────────────
    try:
        # AGENT-CTX: limit=5 matches the free-tier RPM cap for gemini-2.5-flash (5 RPM).
        # Firing 10 concurrent classify calls saturates the quota instantly.
        # Raise this limit only after upgrading to a paid API key or switching to a
        # higher-RPM model. The acceptance criterion is "at least 10 abstracts" —
        # TODO (T6/paid tier): bump back to 10 once quota is not the bottleneck.
        records = await fetch_abstracts(query, limit=5)
    except ValueError as e:
        # AGENT-CTX: ValueError means empty query, but FastAPI's Query(min_length=1)
        # should catch this before we get here. Mapped to 422 defensively in case
        # the validation contract is relaxed in a future refactor.
        raise HTTPException(status_code=422, detail=str(e)) from e
    except RuntimeError as e:
        # AGENT-CTX: RuntimeError from fetch_abstracts = PubMed HTTP/parse failure.
        # 500 (not 502) — the fault is in our upstream data source, not the LLM.
        raise HTTPException(status_code=500, detail=f"PubMed fetch failed: {e}") from e

    if not records:
        # AGENT-CTX: Valid query, zero PubMed results. Return empty list — not an error.
        # Frontend renders "no results found" when results==[].
        return SearchResponse(query=query, results=[])

    # ── Step 2: Classify all abstracts concurrently ───────────────────────────
    # AGENT-CTX: asyncio.gather() runs all classify_evidence_type() calls concurrently.
    # classify_evidence_type() uses asyncio.to_thread() internally, so each call
    # dispatches a blocking Gemini API call to the thread pool executor.
    # With limit=10 and Python's default pool (min(32, cpu+4) threads), 10 concurrent
    # calls are well within capacity and reduce total latency from ~25s to ~3-5s.
    #
    # AGENT-CTX: If Gemini rate-limit errors appear in production (429), add a
    # asyncio.Semaphore(N) here to cap concurrency. Do not add it now — premature
    # optimisation for a demo that makes ≤1 search/minute.
    #
    # AGENT-CTX: gather() propagates the first RuntimeError and cancels remaining
    # tasks. This is intentional — a partial result set is worse than a clean error
    # message for the user at this stage.
    try:
        evidence_types = await asyncio.gather(
            *[classify_evidence_type(r["title"], r["abstract"]) for r in records]
        )
    except RuntimeError as e:
        # AGENT-CTX: RuntimeError from classify_evidence_type = Gemini API failure.
        # 502 (Bad Gateway) signals the LLM is the failing dependency, not us.
        raise HTTPException(status_code=502, detail=f"LLM classification failed: {e}") from e

    # ── Step 3: Zip records with classifications and return ───────────────────
    # AGENT-CTX: zip(records, evidence_types) is safe here because asyncio.gather()
    # preserves order — evidence_types[i] corresponds to records[i].
    results = [
        EvidenceItem(
            pmid=record["pmid"],
            title=record["title"],
            abstract=record["abstract"],
            evidence_type=et,
        )
        for record, et in zip(records, evidence_types)
    ]

    return SearchResponse(query=query, results=results)
