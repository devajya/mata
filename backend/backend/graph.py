"""
Layer assignment for the Evidence Chain graph.

AGENT-CTX: Layer assignment is DETERMINISTIC — a rules-based lookup table, not LLM-assigned.
The 1:1 mapping from EvidenceType to layer position adds no information that the LLM could
improve upon, and keeping it deterministic means the graph layout is stable across re-runs.

AGENT-CTX: Layer semantics (left-to-right progression in the DAG):
  -1  review         — chain metadata, NOT a graph node; drives gray-out logic
   0  in vitro       — earliest-stage mechanistic evidence
   1  animal model   — in vivo preclinical
   2  human genetics — GWAS/population genetics
   3  clinical trial — highest translational evidence

AGENT-CTX: assign_layer() returns -1 (not 0) for unknown types.
Returning 0 would silently misclassify unknowns as in-vitro evidence; -1 excludes
them from CHAIN_LAYER_ORDER and makes the misclassification visible as a gap node.

AGENT-CTX: CHAIN_LAYER_ORDER deliberately excludes -1. Reviews are attached to
ChainMeta.review and used for temporal gray-out, not rendered as graph nodes.
"""

from backend.models import EvidenceType

EVIDENCE_TYPE_TO_LAYER: dict[str, int] = {
    "in vitro":       0,
    "animal model":   1,
    "human genetics": 2,
    "clinical trial": 3,
    "review":        -1,
}

LAYER_NAMES: dict[int, str] = {
    -1: "Review",
     0: "In Vitro",
     1: "Animal Model",
     2: "Human Genetics",
     3: "Clinical Trial",
}

# AGENT-CTX: CHAIN_LAYER_ORDER defines the left-to-right rendering sequence.
# Reviews (layer -1) are intentionally absent — they annotate chains, not nodes.
CHAIN_LAYER_ORDER: list[int] = [0, 1, 2, 3]


def assign_layer(evidence_type: str) -> int:
    """
    Map an EvidenceType string to its graph layer index.

    Returns -1 for any unknown value — callers must handle -1 gracefully.
    Never raises; safe to call with arbitrary LLM output.
    """
    return EVIDENCE_TYPE_TO_LAYER.get(evidence_type, -1)
