"""
PubMed Entrez E-utilities fetch module.

AGENT-CTX: Uses NCBI E-utilities (esearch → efetch) over XML.
Chosen over Biopython.Entrez to avoid a heavyweight dependency for a simple fetch.
stdlib xml.etree.ElementTree is sufficient for parsing flat abstract records.

Two-step fetch pattern:
  1. esearch  — get list of PMIDs matching query
  2. efetch   — retrieve full records (title + abstract) by PMID

Rate limits: 3 req/s without API key, 10 req/s with NCBI_API_KEY env var.
AGENT-CTX: TODO (T2) — add NCBI_API_KEY param to requests if env var present.
"""

# AGENT-CTX: STUB — raises NotImplementedError.
# Tests will ERROR (not FAIL) until T2 replaces this body.
# Do not remove the function signature — it is part of the locked interface.


async def fetch_abstracts(query: str, limit: int = 10) -> list[dict]:
    """
    Fetch PubMed abstracts for a query.

    Args:
        query: Search string (e.g. "KRAS G12C")
        limit: Number of records to fetch (default 10)

    Returns:
        List of dicts with keys: pmid (str), title (str), abstract (str)

    Raises:
        ValueError: if query is empty
        RuntimeError: if PubMed fetch fails

    AGENT-CTX: Invariant — returned dicts always contain pmid, title, abstract.
    Records with no abstract in PubMed get abstract="" (empty string, not None).
    Downstream LLM classifier must handle empty abstracts gracefully.
    """
    raise NotImplementedError("fetch_abstracts not yet implemented — see T2")
