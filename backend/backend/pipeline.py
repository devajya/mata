"""
Search pipeline — canonical evidence extraction and scoring logic.

AGENT-CTX: This module owns the single authoritative implementation of the
search pipeline: fetch_abstracts → extract_structured_evidence → EvidenceItem
assembly → confidence scoring → edge computation → SearchResponse.

AGENT-CTX: Previously this logic lived as a private _run_pipeline() function
inside worker.py. Promoting it to a named module achieves three things:
  1. Seam — the pipeline is now independently importable and testable without
     a DB connection, ARQ ctx, or any job-state machinery.
  2. No duplication — any future second transport (sync API, webhooks, CLI)
     calls run_pipeline() directly rather than copy-pasting the pipeline.
  3. Discoverability — pipeline.py is the obvious place to add a new step
     (e.g. citation deduplication, result caching) without touching worker.py.

AGENT-CTX: _engine is a module-level instance, one per OS process. The web
process (main.py lifespan) and the ARQ worker (worker.py startup) are separate
processes — each gets its own copy of this module. Previously both defined
identical _engine instances independently; centralising here makes it
impossible for them to drift (adding a factor in main.py and forgetting worker.py).

AGENT-CTX: run_pipeline() accepts extraction_sem so the ARQ worker can pass its
provider-calibrated semaphore (Groq: 10, Ollama CPU: 1, Ollama GPU: 2). Callers
that do not need gating pass None and receive a permissive Semaphore(10).
"""

import asyncio
import logging

from backend.confidence import ConfidenceEngine, SubjectTypeFactor
from backend.edges import compute_all_edges
from backend.graph import assign_layer
from backend.llm import extract_structured_evidence
from backend.models import EvidenceItem, SearchResponse
from backend.pubmed import fetch_abstracts

logger = logging.getLogger(__name__)

# AGENT-CTX: Single factor registration point for both processes.
# Previously main.py and worker.py each registered factors independently;
# any edit required two identical changes. Now change it here only.
# Factor scoring is deterministic and stateless — a module-level instance
# is safe across concurrent asyncio tasks.
_engine = ConfidenceEngine().register(SubjectTypeFactor())


async def _extract_with_semaphore(
    sem: asyncio.Semaphore,
    title: str,
    abstract: str,
    max_tokens: int = 500,
):
    """
    Gate a single extract_structured_evidence() call behind a semaphore.

    AGENT-CTX: The semaphore value comes from provider.py's ProviderConfig
    (built once in worker startup(), stored in ARQ ctx). For Ollama CPU
    this is 1, making asyncio.gather() effectively sequential and preventing
    the connection-queue timeout described in worker.py's module docstring.
    For Groq this is 10 (fully concurrent within the free-tier rate limit).

    AGENT-CTX: max_tokens comes from ProviderConfig.max_tokens_extraction via
    run_pipeline(). Default 500 matches the registry value.

    AGENT-CTX: This remains a named module-level function (not inlined into
    run_pipeline) so that tests can monkeypatch extract_structured_evidence
    independently — the semaphore logic is the only concern here.
    """
    async with sem:
        return await extract_structured_evidence(title, abstract, max_tokens)


async def run_pipeline(
    query: str,
    limit: int = 10,
    extraction_sem: asyncio.Semaphore | None = None,
    max_tokens_extraction: int = 500,
    max_tokens_edge: int = 1500,
) -> SearchResponse:
    """
    Execute the full evidence search pipeline for a query.

    Args:
        query:                 Search string. Validated non-empty by the caller.
        limit:                 Number of PubMed abstracts to fetch. Defaults to 10.
                               The ARQ worker reads PUBMED_LIMIT from env and passes it.
        extraction_sem:        Semaphore controlling LLM extraction concurrency.
                               None → permissive asyncio.Semaphore(10).
                               Worker passes its provider-calibrated semaphore.
        max_tokens_extraction: Token budget for each extract_structured_evidence call.
                               Comes from ProviderConfig.max_tokens_extraction via worker.
        max_tokens_edge:       Token budget for the single classify_edges_via_llm call.
                               Comes from ProviderConfig.max_tokens_edge via worker.

    Returns:
        SearchResponse with results and edges populated.
        edges=[] when edge computation fails or no comparable pairs exist
        (compute_all_edges never raises).

    Raises:
        ValueError:   when PubMed returns no records for the query.
        RuntimeError: when the PubMed HTTP call or LLM API call fails.
    """
    sem = extraction_sem if extraction_sem is not None else asyncio.Semaphore(10)

    records = await fetch_abstracts(query, limit=limit)

    if not records:
        raise ValueError(
            f"PubMed returned no results for '{query}'. Try a broader search term."
        )

    # AGENT-CTX: _extract_with_semaphore enforces provider-appropriate concurrency.
    # For Ollama CPU (semaphore=1) this is effectively sequential. For Groq
    # (semaphore=10) it is fully concurrent. asyncio.gather() schedules all
    # coroutines; the semaphore gates how many enter the actual HTTP call at once.
    structured_results = await asyncio.gather(
        *[_extract_with_semaphore(sem, r["title"], r["abstract"], max_tokens_extraction)
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

    # AGENT-CTX: Edge computation runs after all EvidenceItems are built so
    # compute_all_edges() has access to both item.layer and StructuredEvidence
    # fields simultaneously. structured_results is a tuple from asyncio.gather;
    # convert to list for compute_all_edges() which expects list[StructuredEvidence].
    # compute_all_edges() never raises — all failures return [].
    edges = await compute_all_edges(results, list(structured_results), max_tokens_edge)

    return SearchResponse(query=query, results=results, edges=edges)
