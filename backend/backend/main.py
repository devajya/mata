"""
FastAPI application entry point.

AGENT-CTX: Stateless by design for this slice — no DB, no session store.
All state lives in PubMed and the LLM. Safe to scale horizontally on Render.

AGENT-CTX: Milestone 1 change — extract_structured_evidence() replaces the
old classify_evidence_type(). The LLM now returns a StructuredEvidence object
(four fields) instead of a bare string. The ConfidenceEngine converts that
into a ConfidenceTier and all fields are assembled into EvidenceItem for the
API response. See confidence.py for the scoring pipeline and llm.py for the
extraction function.
"""

import asyncio
import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from backend.confidence import ConfidenceEngine, SubjectTypeFactor
from backend.llm import extract_structured_evidence
from backend.models import EvidenceItem, ErrorResponse, SearchResponse
from backend.pubmed import fetch_abstracts

# AGENT-CTX: App-level metadata used by Render's auto-generated /docs page.
app = FastAPI(
    title="MATA API",
    version="0.2.0",
    description="Drug target evidence aggregation — structured evidence extraction",
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

# AGENT-CTX: Module-level ConfidenceEngine instance, constructed once at startup.
# Registers SubjectTypeFactor as the sole scoring signal for this slice.
# To add future factors (SampleSizeFactor, StudyDesignFactor, etc.) extend this
# chain — no other code needs to change. See confidence.py for the Factor protocol.
# Not a singleton by pattern, but effectively singleton by placement here.
# If the engine ever needs runtime reconfiguration (e.g. per-request weights),
# move construction inside the search handler — the engine.score() call is cheap.
_engine = (
    ConfidenceEngine()
    .register(SubjectTypeFactor())
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
        502: {"model": ErrorResponse, "description": "LLM extraction failed"},
    },
)
async def search(
    query: str = Query(..., min_length=1, description="Drug target name, e.g. 'KRAS G12C'"),
) -> SearchResponse:
    """
    Search PubMed for evidence items related to a drug target and extract
    structured evidence fields from each abstract.

    Flow: esearch → efetch (PubMed) → asyncio.gather(extract × N) → score → SearchResponse
    """
    # ── Step 1: Fetch abstracts from PubMed ───────────────────────────────────
    try:
        # AGENT-CTX: limit=10 matches the original AC ("at least 10 abstracts").
        # Groq free tier is 30 RPM — 10 concurrent extraction calls are within quota.
        # Do NOT lower this below 10 without updating the AC and E2E test assertion.
        records = await fetch_abstracts(query, limit=10)
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
        # Frontend renders "no results found" when results == [].
        return SearchResponse(query=query, results=[])

    # ── Step 2: Extract structured evidence from all abstracts concurrently ────
    # AGENT-CTX: asyncio.gather() runs all extract_structured_evidence() calls
    # concurrently. extract_structured_evidence() uses asyncio.to_thread() internally
    # (Groq SDK sync call), so each call dispatches to the thread pool executor.
    # With limit=10 and Python's default pool (min(32, cpu+4) threads), 10 concurrent
    # calls are well within capacity and reduce total latency from ~20s to ~3-5s.
    # Groq free tier is 30 RPM — 10 concurrent calls are safe.
    #
    # AGENT-CTX: If rate-limit errors (429) appear in production, add an
    # asyncio.Semaphore(N) here to cap concurrency. Do not add it now — premature
    # optimisation for a demo that makes ≤1 search/minute.
    #
    # AGENT-CTX: When one coroutine raises, gather() immediately raises that exception
    # to the caller — but the remaining in-flight tasks are NOT cancelled. They continue
    # running unobserved in the thread pool until they complete or fail silently.
    # For 10 short-lived Groq calls this is acceptable — they will finish within seconds
    # and waste at most 9 quota tokens.
    try:
        structured_results = await asyncio.gather(
            *[extract_structured_evidence(r["title"], r["abstract"]) for r in records]
        )
    except RuntimeError as e:
        # AGENT-CTX: RuntimeError from extract_structured_evidence = Groq API failure.
        # 502 (Bad Gateway) signals the LLM is the failing dependency, not us.
        # Note: parse failures inside extract_structured_evidence return safe defaults
        # rather than raising — only actual API errors reach this handler.
        raise HTTPException(status_code=502, detail=f"LLM extraction failed: {e}") from e

    # ── Step 3: Score confidence and assemble response items ──────────────────
    # AGENT-CTX: zip(records, structured_results) is safe here because asyncio.gather()
    # preserves input order — structured_results[i] corresponds to records[i].
    #
    # AGENT-CTX: _engine.score(structured) is synchronous and cheap (weighted average
    # of factor scores). It runs in the event loop thread — no need for to_thread().
    # The result is confidence_tier: ConfidenceTier ("high" | "medium" | "low").
    results = [
        EvidenceItem(
            pmid=record["pmid"],
            title=record["title"],
            abstract=record["abstract"],
            # AGENT-CTX: All four LLM-extracted fields copied directly from StructuredEvidence.
            # No transformation — the Pydantic model already validated them.
            evidence_type=structured.evidence_type,
            effect_direction=structured.effect_direction,
            model_organism=structured.model_organism,
            sample_size=structured.sample_size,
            # AGENT-CTX: confidence_tier is engine-derived, not LLM-extracted.
            # _engine.score() applies the registered factor pipeline to produce
            # a ConfidenceTier bucket. See confidence.py for scoring logic.
            confidence_tier=_engine.score(structured),
        )
        for record, structured in zip(records, structured_results)
    ]

    return SearchResponse(query=query, results=results)
