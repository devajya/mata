"""
FastAPI application entry point.

AGENT-CTX: Stateless by design for this slice — no DB, no session store.
All state lives in PubMed and the LLM. Safe to scale horizontally on Railway.
"""

import os
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.models import SearchResponse, ErrorResponse  # noqa: F401

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
    # AGENT-CTX: Railway health check hits this endpoint.
    # Must return HTTP 200 or Railway restarts the container.
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
    Search PubMed for evidence items related to a drug target.

    AGENT-CTX: STUB — raises 501 until T4 wires pubmed.py + llm.py.
    The response_model and error shapes are locked — do not change them.
    Replace only the body in T4.
    """
    # AGENT-CTX: HTTPException 501 chosen over NotImplementedError so FastAPI
    # returns valid JSON instead of a 500 with an unhandled exception traceback.
    raise HTTPException(status_code=501, detail="search endpoint not yet implemented — see T4")
