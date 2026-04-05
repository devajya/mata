"""
PubMed Entrez E-utilities fetch module.

AGENT-CTX: Uses NCBI E-utilities (esearch → efetch) over XML.
Chosen over Biopython.Entrez to avoid a heavyweight dependency for a simple fetch.
stdlib xml.etree.ElementTree is sufficient for parsing flat abstract records.

Two-step fetch pattern:
  1. esearch  — POST to get a ranked list of PMIDs matching the query
  2. efetch   — GET full records (title + abstract) for those PMIDs by ID

Rate limits:
  - Without NCBI_API_KEY: 3 requests/second
  - With NCBI_API_KEY:    10 requests/second
  Both calls count toward the limit. For 1 search = 2 calls, safe at any pace.

AGENT-CTX: efetch retmode=xml chosen over retmode=json because the JSON variant
does not include the full abstract text — only the XML response is complete.
Do not switch to retmode=json for efetch.
"""

import os
import xml.etree.ElementTree as ET

import httpx

# AGENT-CTX: Entrez base URL is stable; do not version-pin it.
# NCBI has maintained this URL shape since at least 2002.
_ENTREZ_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# AGENT-CTX: Timeout of 30s for each individual HTTP call.
# PubMed can be slow under load; 10s is too tight and causes spurious failures.
# Both esearch and efetch are subject to this timeout independently.
_HTTP_TIMEOUT = 30.0


async def fetch_abstracts(query: str, limit: int = 10) -> list[dict]:
    """
    Fetch PubMed abstracts for a query via NCBI Entrez E-utilities.

    Args:
        query: Search string (e.g. "KRAS G12C"). Must be non-empty.
        limit: Number of records to fetch (default 10).

    Returns:
        List of dicts, each with keys: pmid (str), title (str), abstract (str),
        publication_year (int | None).
        Records with no abstract in PubMed have abstract="" (empty string, not None).
        publication_year is None when the year is absent or non-parseable.
        May return fewer than `limit` items if PubMed has fewer results.

    Raises:
        ValueError:    if query is empty or whitespace-only.
        RuntimeError:  if either Entrez HTTP call fails or XML cannot be parsed.

    AGENT-CTX: Invariant — returned dicts ALWAYS contain all four keys.
    AGENT-CTX: Invariant — abstract is ALWAYS a str, never None.
    These invariants are relied upon by the LLM classifier in llm.py.
    """
    # AGENT-CTX: Validate before touching the network so the error is fast and clear.
    # strip() catches whitespace-only queries like "   ".
    if not query or not query.strip():
        raise ValueError("query must not be empty or whitespace-only")

    raw_ncbi_key = os.environ.get("NCBI_API_KEY", "")
    # AGENT-CTX: Guard against the .env.example placeholder being copied verbatim.
    # PubMed returns HTTP 400 if a non-empty but invalid key is sent.
    # If the key looks like a placeholder, treat it as absent (no key → 3 req/s free tier).
    # Real NCBI API keys are 36-char alphanumeric strings with no spaces.
    api_key = raw_ncbi_key if (raw_ncbi_key and " " not in raw_ncbi_key and "your_" not in raw_ncbi_key) else None

    # AGENT-CTX: Single shared AsyncClient for both calls to reuse the TCP connection.
    # httpx.AsyncClient must be used (not httpx.Client) to stay on the async event loop
    # — this function is called from async FastAPI route handlers.
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        pmids = await _esearch(client, query, limit, api_key)

        if not pmids:
            # AGENT-CTX: Not an error — query simply has no PubMed results.
            # Return empty list; endpoint returns {"results": []} to frontend.
            return []

        xml_text = await _efetch(client, pmids, api_key)

    return _parse_pubmed_xml(xml_text)


# ─── Private helpers ──────────────────────────────────────────────────────────


async def _esearch(
    client: httpx.AsyncClient,
    query: str,
    limit: int,
    api_key: str | None,
) -> list[str]:
    """
    Run esearch and return list of PMID strings.

    AGENT-CTX: retmode=json for esearch is safe and simpler than XML.
    The JSON idlist contains PMIDs as strings, which is what efetch expects.
    """
    params: dict[str, str | int] = {
        "db": "pubmed",
        "term": query,
        "retmax": limit,
        "retmode": "json",
        # AGENT-CTX: usehistory=n (default) — we pass IDs directly to efetch.
        # usehistory=y (WebEnv/query_key) would be needed for >10k results,
        # which is out of scope for this slice.
    }
    if api_key:
        params["api_key"] = api_key

    try:
        response = await client.get(f"{_ENTREZ_BASE}/esearch.fcgi", params=params)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"PubMed esearch HTTP error {e.response.status_code}: {e.response.text[:200]}"
        ) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"PubMed esearch request failed: {e}") from e

    try:
        data = response.json()
        return data["esearchresult"]["idlist"]
    except (KeyError, ValueError) as e:
        raise RuntimeError(f"Unexpected PubMed esearch response shape: {e}") from e


async def _efetch(
    client: httpx.AsyncClient,
    pmids: list[str],
    api_key: str | None,
) -> str:
    """
    Run efetch for a list of PMIDs and return raw XML text.

    AGENT-CTX: rettype=abstract, retmode=xml is the only efetch mode that
    reliably includes both title and full abstract text.
    Do NOT change to retmode=json — the JSON efetch response omits abstract text.
    """
    params: dict[str, str] = {
        "db": "pubmed",
        # AGENT-CTX: Comma-joined PMID string is the correct format for efetch batch fetch.
        # Maximum safe batch size is ~200 PMIDs; we fetch at most `limit` (default 10).
        "id": ",".join(pmids),
        "rettype": "abstract",
        "retmode": "xml",
    }
    if api_key:
        params["api_key"] = api_key

    try:
        response = await client.get(f"{_ENTREZ_BASE}/efetch.fcgi", params=params)
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise RuntimeError(
            f"PubMed efetch HTTP error {e.response.status_code}: {e.response.text[:200]}"
        ) from e
    except httpx.RequestError as e:
        raise RuntimeError(f"PubMed efetch request failed: {e}") from e

    return response.text


def _parse_pubmed_xml(xml_text: str) -> list[dict]:
    """
    Parse PubmedArticleSet XML and extract pmid, title, abstract per article.

    AGENT-CTX: XPath expressions use .// (descendant search) to be resilient to
    minor PubMed XML schema variations across article types. The DTD version can
    differ between records; descendant search avoids brittle absolute paths.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise RuntimeError(f"Failed to parse PubMed XML response: {e}") from e

    results = []

    for article in root.findall(".//PubmedArticle"):
        pmid = _extract_pmid(article)
        title = _extract_title(article)
        abstract = _extract_abstract(article)
        publication_year = _extract_publication_year(article)

        results.append({
            "pmid": pmid,
            "title": title,
            # AGENT-CTX: abstract is always str here — _extract_abstract never returns None.
            "abstract": abstract,
            "publication_year": publication_year,
        })

    return results


def _extract_pmid(article: ET.Element) -> str:
    """
    AGENT-CTX: PMID Version="1" is the canonical identifier.
    findall returns all PMID elements (some records have multiple versions);
    we take the first, which is always the primary PMID.
    """
    el = article.find(".//PMID")
    return el.text.strip() if el is not None and el.text else ""


def _extract_title(article: ET.Element) -> str:
    """
    AGENT-CTX: ArticleTitle can contain inline XML formatting tags such as
    <i>, <b>, <sup>, <sub>. Using _inner_text() (itertext) concatenates all
    text nodes including those inside child elements, giving clean plain text.
    Example: "KRAS <sup>G12C</sup> inhibitors" → "KRAS G12C inhibitors"
    """
    el = article.find(".//ArticleTitle")
    return _inner_text(el) if el is not None else ""


def _extract_abstract(article: ET.Element) -> str:
    """
    Handle three abstract structures found in PubMed XML:

    1. No abstract — editorial, letter, comment records often lack one.
       → Return "".

    2. Simple abstract — single <AbstractText> with plain text.
       → Return the text directly.

    3. Structured abstract — multiple <AbstractText Label="BACKGROUND"> etc.
       → Join sections as "LABEL: text" separated by spaces.

    AGENT-CTX: Structured abstracts are common in clinical trial papers.
    Joining them preserves section context for the LLM classifier without
    requiring the classifier to handle XML structure.

    AGENT-CTX: OtherAbstract elements (non-English translations) are excluded.
    findall(".//Abstract/AbstractText") scopes to the primary Abstract element;
    OtherAbstract uses a different parent path and is not matched.
    """
    abstract_els = article.findall(".//Abstract/AbstractText")

    if not abstract_els:
        # AGENT-CTX: Invariant — return "" not None. Caller and LLM rely on str type.
        return ""

    if len(abstract_els) == 1:
        return _inner_text(abstract_els[0])

    # AGENT-CTX: Structured abstract — join sections.
    # Label attribute is present on structured abstracts (e.g. "BACKGROUND").
    # If Label is absent on a section, include text without a prefix.
    parts = []
    for el in abstract_els:
        text = _inner_text(el)
        if not text:
            continue
        label = el.get("Label", "")
        parts.append(f"{label}: {text}" if label else text)

    return " ".join(parts)


def _extract_publication_year(article: ET.Element) -> int | None:
    """
    Extract the publication year from a PubmedArticle XML element.

    AGENT-CTX: Two XPath paths tried in order of reliability:
      1. .//JournalIssue/PubDate/Year — standard journal publication date; present
         in the vast majority of indexed articles.
      2. .//ArticleDate/Year — electronic publication date; fallback for epub-only
         records where JournalIssue/PubDate contains MedlineDate instead of Year.

    AGENT-CTX: MedlineDate is deliberately NOT parsed. MedlineDate is a free-text
    field (e.g. "2021 Jan-Feb", "2020 Spring") that requires regex to extract a year.
    Parsing it would add fragility for rare cases; returning None is safer. Items
    with publication_year=None are simply never grayed out by ChainPanel's filter.

    Returns int (year) or None — never raises.
    """
    for xpath in (".//JournalIssue/PubDate/Year", ".//ArticleDate/Year"):
        el = article.find(xpath)
        if el is not None and el.text:
            try:
                return int(el.text.strip())
            except ValueError:
                pass
    return None


def _inner_text(el: ET.Element) -> str:
    """
    Concatenate all text content within an element, including mixed-content children.

    AGENT-CTX: ET.Element.text only captures text before the first child element.
    itertext() walks the full subtree and yields all text nodes in document order,
    which is necessary for elements like <ArticleTitle> that contain inline tags.
    """
    return "".join(el.itertext()).strip()
