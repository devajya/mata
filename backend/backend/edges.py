"""
Edge computation engine for the Evidence Chain graph.

AGENT-CTX: This module is responsible for discovering and classifying semantic
relationships (edges) between evidence papers in a single job result. It is called
by worker.py after all evidence items have been extracted and scored.

AGENT-CTX: Architecture — three-stage pipeline:
  1. build_paper_contexts() — maps EvidenceItem + StructuredEvidence → PaperContext
     (lightweight struct used for comparison; no API calls)
  2. is_comparable() — rule-based O(n²) pre-filter to select candidate pairs
     before any LLM call. Short-circuits classify_edges_via_llm when no
     comparable pairs exist (saves a Groq API call).
  3. classify_edges_via_llm() — single LLM batch call for all paper contexts,
     returns EdgeResult list. This is the ONLY place in this module that calls
     the LLM. It is a named module-level function so tests can monkeypatch it:
       monkeypatch.setattr(edges, "classify_edges_via_llm", mock_fn)

AGENT-CTX: compute_all_edges() is the public entry point (called by worker.py).
It never raises — all exceptions are caught and returned as an empty list so that
the parent job still completes with results even if edge computation fails.

AGENT-CTX: Groq client and provider constants (GROQ_MODEL, LLM_PROVIDER, OLLAMA_BASE_URL)
are imported from backend.llm_client — shared with llm.py so a model name change
propagates to both extraction and edge classification automatically.
max_tokens differs between the two call types (1500 here vs 500 for extraction)
so the individual call functions remain in their respective modules.

AGENT-CTX: Groq client for edge classification uses llama-3.1-8b-instant, same
model as extraction. max_tokens=1500 (vs 500 for extraction) — sized for ≤5
papers (PUBMED_LIMIT=5): ~10 comparable pairs × ~60 tokens each = ~600 tokens,
1500 gives comfortable headroom. Only comparable-pair papers are sent to the LLM
(see compute_all_edges), so the prompt is smaller than the full paper list.
Raise to 3000 if PUBMED_LIMIT returns to 10.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass

import httpx
from groq import APIError as GroqAPIError
from groq import RateLimitError as GroqRateLimitError
from pydantic import ValidationError

from backend.llm_client import GROQ_MODEL, LLM_PROVIDER, OLLAMA_BASE_URL, get_groq_client
from backend.models import (
    EdgeResult,
    EvidenceItem,
    StructuredEvidence,
    VALID_EDGE_TYPES,
)

logger = logging.getLogger(__name__)

# AGENT-CTX: GROQ_MODEL, LLM_PROVIDER, OLLAMA_BASE_URL, and get_groq_client() live in
# llm_client.py — imported above. Switching LLM_PROVIDER affects both extraction
# (llm.py) and edge calls (this module) automatically.


# ── Paper context ─────────────────────────────────────────────────────────────

@dataclass
class PaperContext:
    """
    Lightweight struct combining EvidenceItem + StructuredEvidence fields for
    pairwise comparison. Not stored in the DB — constructed transiently in
    build_paper_contexts() and passed to classify_edges_via_llm().

    AGENT-CTX: PaperContext is a dataclass (not Pydantic) because it is an
    internal computation struct, not an API model. Using dataclass avoids
    Pydantic validation overhead on the ~n² instantiations during is_comparable
    checks, and removes any ambiguity about whether it should be serialised.
    """

    pmid: str
    evidence_type: str
    layer: int
    effect_direction: str
    cancer_type: str
    intervention: str
    primary_endpoint: str
    effect_size: str
    mechanism_described: str
    resistance_findings: str
    key_claim: str
    model_organism: str


def build_paper_contexts(
    items: list[EvidenceItem],
    structured_list: list[StructuredEvidence],
) -> list[PaperContext]:
    """
    Combine EvidenceItem graph metadata with StructuredEvidence extraction fields
    into PaperContext structs for pairwise comparison.

    AGENT-CTX: layer comes from EvidenceItem (assigned by assign_layer() in graph.py),
    not from StructuredEvidence — layer is a derived/computed field, not LLM-extracted.
    All other comparison fields come from StructuredEvidence.

    AGENT-CTX: Assumes items and structured_list are parallel (same index = same paper).
    This invariant is established by worker.py which constructs both lists in lockstep
    via asyncio.gather. If the lists ever have different lengths, zip() silently truncates
    to the shorter — callers should ensure alignment.
    """
    return [
        PaperContext(
            pmid=item.pmid,
            evidence_type=structured.evidence_type,
            layer=item.layer,
            effect_direction=structured.effect_direction,
            cancer_type=structured.cancer_type,
            intervention=structured.intervention,
            primary_endpoint=structured.primary_endpoint,
            effect_size=structured.effect_size,
            mechanism_described=structured.mechanism_described,
            resistance_findings=structured.resistance_findings,
            key_claim=structured.key_claim,
            model_organism=structured.model_organism,
        )
        for item, structured in zip(items, structured_list)
    ]


# ── Comparability pre-filter ──────────────────────────────────────────────────

def is_comparable(a: PaperContext, b: PaperContext) -> bool:
    """
    Return True if papers A and B are candidates for edge classification.

    AGENT-CTX: This is a PRE-FILTER, not an edge classifier. It gates whether
    the LLM should consider a pair at all. False negatives (missing a real edge)
    are worse than false positives (sending an unrelated pair to the LLM), so
    the rules are intentionally permissive — the LLM does the precise classification.

    AGENT-CTX: Two comparability rules (either is sufficient):
      1. SAME INTERVENTION — both papers name the same drug/molecule/perturbation
         (neither is "not reported"). Same intervention is the strongest signal
         that two papers' findings bear on each other.
      2. ADJACENT LAYERS — layers within distance 1 in the evidence hierarchy
         (e.g. in vitro=0 and animal=1, animal=1 and human genetics=2).
         Catches TRANSLATES/FAILS_TO_TRANSLATE edges between papers that describe
         the same target mechanism across evidence levels even when the specific
         drug name was not extracted.

    AGENT-CTX: Self-comparisons (same pmid) are always False. This prevents
    spurious edges when the same paper appears twice (shouldn't happen, but guard
    added defensively).

    AGENT-CTX: Reviews (layer=-1) are excluded from adjacency comparisons. Review
    papers annotate chains but don't generate primary findings — edges from reviews
    to primary papers are weak at best and are better surfaced via the ChainMeta
    review annotation. If a future slice wants review→primary edges, add them here.
    """
    # Guard: never compare a paper with itself
    if a.pmid == b.pmid:
        return False

    # Rule 1: same named intervention (both non-sentinel)
    if (
        a.intervention != "not reported"
        and b.intervention != "not reported"
        and a.intervention.lower() == b.intervention.lower()
    ):
        return True

    # Rule 2: adjacent layers in the evidence hierarchy (excludes reviews at -1)
    if a.layer >= 0 and b.layer >= 0 and abs(a.layer - b.layer) <= 1:
        return True

    return False


def _has_comparable_pairs(contexts: list[PaperContext]) -> bool:
    """
    Return True if any pair in contexts passes is_comparable().
    Used by compute_all_edges to short-circuit the LLM call.

    AGENT-CTX: O(n²) check but n ≤ 10 in practice (PUBMED_RESULT_LIMIT default).
    At n=10 this is 45 checks — negligible. If the limit grows substantially,
    consider an early-exit optimisation.
    """
    for i, a in enumerate(contexts):
        for b in contexts[i + 1:]:
            if is_comparable(a, b):
                return True
    return False


# ── LLM edge classification ───────────────────────────────────────────────────

# AGENT-CTX: Edge taxonomy system prompt. Deliberately concise for the 8B model —
# the full design brief taxonomy is too long to reliably follow for llama-3.1-8b.
# Rule of thumb: the 8B model follows instructions better with 1-line definitions
# than with paragraph-length explanations. The 10 edge types are listed in priority
# order (most specific first) so the model assigns the most precise type available.
#
# AGENT-CTX: Confidence scoring in the prompt uses simple additive rules that mirror
# the design brief's table. These are guidelines for the LLM, not strict enforcement
# — _parse_edge_results() clamps the output to [0.1, 0.95] regardless of what the
# model returns.
#
# AGENT-CTX: Output must be {"edges": [...]} — the outermost key is required because
# response_format={"type":"json_object"} requires the response to be a JSON object
# (not a bare array). The "edges" wrapper key satisfies this constraint.
_EDGE_SYSTEM_PROMPT = """\
You are a biomedical evidence relationship extractor. Given structured data for \
N research papers on the same drug target or pathway, identify all meaningful \
scientific relationships between pairs of papers.

Output: {"edges": [...]} — a JSON object with an "edges" array. \
Each edge object must have exactly these keys:
  "source_pmid": PMID of the first paper
  "target_pmid": PMID of the second paper
  "edge_type": one of the 10 types below
  "direction": "A→B" where A=source, B=target
  "confidence": float 0.1–0.95
  "rationale": one sentence explaining the relationship using both papers' specific contexts
  "confidence_factors": list of strings like ["+0.20 same intervention", "-0.15 different species"]
  "flag": null, or a string if confidence < 0.4 explaining why

Edge types — assign the MOST SPECIFIC applicable type:
  "resistance_link": B identifies resistance mutations or bypass mechanisms limiting A's efficacy
  "fails_to_translate": A (lower evidence) shows positive finding; B (higher evidence) does NOT confirm it
  "translates": A (lower evidence) finding is confirmed at higher evidence level in B
  "contradicts": A and B test the same intervention in comparable contexts; opposite effect directions
  "contradicts_methodological": A and B appear to contradict but the conflict is methodological (dose, assay type, timepoint)
  "qualifies": B identifies a subgroup, co-mutation, or condition under which A's finding holds or does not
  "mechanistically_extends": B's mechanism explains A's observation, or A's mechanism predicts B's finding
  "combination_context": A tests intervention as monotherapy; B tests the same intervention in combination (or vice versa)
  "supports": A and B test the same intervention; same effect direction; different model systems
  "replicates": A and B test the same intervention in the same model system from independent labs or datasets

Evidence hierarchy (lower → higher): in_vitro(0) → animal_model(1) → human_genetics(2) → clinical_trial(3)

Confidence guidelines — start at 0.5 and adjust:
  +0.20 same cancer_type; +0.20 same intervention; +0.15 same model_organism
  +0.10 same primary_endpoint; -0.15 cross-species comparison; -0.10 effect_size not reported in one paper
  Floor 0.1, cap 0.95.

Rules:
  - Only create an edge when one paper's finding directly bears on the other's
  - Do not create edges based on shared keywords or topic alone
  - Do not create edges between review papers and primary papers (skip review pairs entirely)
  - For CONTRADICTS: verify experimental contexts are genuinely comparable before assigning
  - Return an empty edges array if no meaningful relationships exist

Return only the JSON object — no explanation, no preamble, no markdown fences."""


def _format_contexts_for_prompt(contexts: list[PaperContext]) -> str:
    """
    Format PaperContext list as a JSON array for the LLM user prompt.

    AGENT-CTX: We send all paper contexts to the LLM (not just comparable pairs).
    Having the full picture lets the model make better MECHANISTICALLY_EXTENDS and
    QUALIFIES decisions where the indirect relationship is only visible across all
    papers. The is_comparable() pre-filter only gates whether to call the LLM at all.

    AGENT-CTX: "not reported" values are included as-is — the LLM is instructed to
    skip edges it cannot support with the available information. Omitting fields would
    require the model to infer absence, which is more error-prone.
    """
    papers = [
        {
            "pmid": ctx.pmid,
            "evidence_type": ctx.evidence_type,
            "layer": ctx.layer,
            "cancer_type": ctx.cancer_type,
            "intervention": ctx.intervention,
            "primary_endpoint": ctx.primary_endpoint,
            "effect_direction": ctx.effect_direction,
            "effect_size": ctx.effect_size,
            "mechanism_described": ctx.mechanism_described,
            "resistance_findings": ctx.resistance_findings,
            "model_organism": ctx.model_organism,
            "key_claim": ctx.key_claim,
        }
        for ctx in contexts
    ]
    return json.dumps(papers, indent=2)


async def _groq_edge_call(prompt: str, max_tokens: int = 1500) -> str:
    """
    Call Groq for edge classification. Returns raw JSON string.

    AGENT-CTX: max_tokens comes from the caller (classify_edges_via_llm), which
    receives it from ProviderConfig via worker.py. Default 1500 matches the
    ProviderConfig registry value, sized for ≤5 papers (PUBMED_LIMIT=5):
    ~10 comparable pairs × ~60 tokens each = ~600 tokens; 1500 gives headroom.
    Change it in provider.py, not here.

    AGENT-CTX: Same asyncio.to_thread() pattern as llm.py — sync Groq client in
    thread pool. See llm.py module docstring for why AsyncGroq is not used.
    """
    client = get_groq_client()
    try:
        completion = await asyncio.to_thread(
            client.chat.completions.create,
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": _EDGE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
            temperature=0,
        )
    except GroqRateLimitError as e:
        raise RuntimeError(f"Groq rate limit exceeded during edge classification: {e}") from e
    except GroqAPIError as e:
        raise RuntimeError(f"Groq API error during edge classification: {e}") from e
    except Exception as e:
        raise RuntimeError(f"Unexpected error during edge classification: {e}") from e
    return completion.choices[0].message.content or ""



async def _ollama_edge_call(prompt: str, max_tokens: int = 1500) -> str:
    """
    Call Ollama for edge classification via httpx. Returns raw JSON string.

    AGENT-CTX: Parity with llm.py's _ollama_call — same endpoint, same
    response_format. max_tokens comes from caller — see _groq_edge_call docstring.
    timeout=600.0 because Ollama serialises requests on CPU — see llm.py
    _ollama_call docstring for the full reasoning.
    """
    url = f"{OLLAMA_BASE_URL}/v1/chat/completions"
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": _EDGE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"] or ""
    except Exception as e:
        raise RuntimeError(f"Ollama edge request failed: {e}") from e


def _parse_edge_results(raw: str) -> list[EdgeResult]:
    """
    Parse the raw LLM JSON string into a list of validated EdgeResult objects.

    AGENT-CTX: Unlike _parse_structured() in llm.py, there is no meaningful
    "safe default" for an edge — we cannot fabricate a relationship if parsing fails.
    Instead, individual invalid edges are skipped and logged; the function returns
    as many valid edges as it can extract. On total failure, returns [].

    AGENT-CTX: Confidence is clamped to [0.1, 0.95] here regardless of what the
    LLM returns. This enforces the invariant documented in EdgeResult even if the
    model outputs 0.0, 1.0, or a value outside the range.

    AGENT-CTX: Unknown edge_type values are skipped (not coerced) — the Pydantic
    ValidationError is caught per-edge. This is intentional: if the LLM hallucinates
    an edge type like "proves", silently treating it as "supports" would be worse
    than skipping it. Skipped edges are logged with their raw content for debugging.
    """
    if not raw:
        logger.warning("Empty LLM response — no edges produced")
        return []

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("JSON decode error: %r | raw=%r", e, raw[:200])
        return []

    raw_edges = parsed.get("edges", [])
    if not isinstance(raw_edges, list):
        logger.warning("'edges' field is not a list: %s", type(raw_edges))
        return []

    results: list[EdgeResult] = []
    for i, raw_edge in enumerate(raw_edges):
        try:
            # AGENT-CTX: Clamp confidence before Pydantic validation so that
            # out-of-range floats (0.0, 1.0, negative) don't pass through.
            # Pydantic does not enforce float ranges by default without a validator.
            if isinstance(raw_edge.get("confidence"), (int, float)):
                raw_edge["confidence"] = max(0.1, min(0.95, float(raw_edge["confidence"])))

            edge = EdgeResult.model_validate(raw_edge)
            results.append(edge)
        except (ValidationError, Exception) as e:
            logger.warning("Skipping edge %d: %r | raw=%r", i, e, str(raw_edge)[:200])

    return results


async def classify_edges_via_llm(
    contexts: list[PaperContext],
    max_tokens: int = 1500,
) -> list[EdgeResult]:
    """
    Make a single batched LLM call to classify all edges between the given papers.

    AGENT-CTX: This is a named module-level async function so tests can monkeypatch it:
        monkeypatch.setattr(edges, "classify_edges_via_llm", async_mock_fn)
    compute_all_edges() calls this by name (via module globals), so the monkeypatch
    correctly intercepts the call. Do NOT inline this into compute_all_edges().
    Test mocks must accept a max_tokens parameter (with a default) to match this
    signature: `async def mock(contexts, max_tokens: int = 1500) -> list[EdgeResult]: ...`

    AGENT-CTX: Raises RuntimeError on LLM API failure (rate limit, auth, network).
    compute_all_edges() catches this and returns [] — the job still completes.
    Parse errors are handled internally by _parse_edge_results() and return [].

    Args:
        contexts:   Paper contexts to classify (pre-filtered by compute_all_edges).
        max_tokens: Token budget for the LLM response. Comes from ProviderConfig
                    via worker.py. Default 1500 matches the registry value.

    Returns:
        list[EdgeResult] — may be empty if no relationships found or parse failed.
    """
    prompt = (
        "Here are the research papers to analyse:\n\n"
        + _format_contexts_for_prompt(contexts)
        + "\n\nIdentify all meaningful scientific relationships between these papers."
    )

    if LLM_PROVIDER == "ollama":
        raw = await _ollama_edge_call(prompt, max_tokens)
    else:
        raw = await _groq_edge_call(prompt, max_tokens)

    return _parse_edge_results(raw)


# ── Public entry point ────────────────────────────────────────────────────────

async def compute_all_edges(
    items: list[EvidenceItem],
    structured_list: list[StructuredEvidence],
    max_tokens: int = 1500,
) -> list[EdgeResult]:
    """
    Compute all semantic edges between evidence papers for a single job.

    This is the only function that worker.py calls. All LLM interaction and
    parsing is encapsulated here. Never raises — all failures return [].

    AGENT-CTX: Three-stage pipeline:
      1. Build PaperContexts from items + structured_list
      2. Check if any comparable pairs exist (short-circuit if not)
      3. Call classify_edges_via_llm with all contexts

    AGENT-CTX: The broad except clause is intentional. Edge computation must
    not crash the worker — if it fails, the job completes with edges=[] rather
    than status=failed. LLM failures (RuntimeError), parse failures (already
    handled in _parse_edge_results), and any unexpected exceptions are all caught.
    Check worker container logs for "[edges.py]" prefix to diagnose failures.

    Args:
        items: EvidenceItem list from the completed extraction step.
               Must be parallel with structured_list (same index = same paper).
        structured_list: StructuredEvidence list from the extraction step.

    Returns:
        list[EdgeResult] — empty list on any failure or when no comparable pairs exist.
    """
    if not items or not structured_list:
        return []

    try:
        contexts = build_paper_contexts(items, structured_list)

        # AGENT-CTX: Single O(n²) pass — find all PMIDs that appear in at least
        # one comparable pair. Papers with no comparable partner are excluded from
        # the LLM prompt, shrinking it substantially (e.g. 5 papers → often 3-4
        # sent). This replaces the old two-pass approach (_has_comparable_pairs
        # then classify_edges_via_llm(all contexts)) with one pass that both
        # short-circuits and filters. Same asymptotic complexity; fewer LLM tokens.
        pmids_in_pairs: set[str] = set()
        for i, a in enumerate(contexts):
            for b in contexts[i + 1:]:
                if is_comparable(a, b):
                    pmids_in_pairs.add(a.pmid)
                    pmids_in_pairs.add(b.pmid)

        if not pmids_in_pairs:
            return []

        filtered_contexts = [c for c in contexts if c.pmid in pmids_in_pairs]
        return await classify_edges_via_llm(filtered_contexts, max_tokens)

    except Exception as e:  # noqa: BLE001
        # AGENT-CTX: Broad catch — see docstring. Check logs for diagnosis.
        logger.error("compute_all_edges failed: %r — returning empty edges", e)
        return []
