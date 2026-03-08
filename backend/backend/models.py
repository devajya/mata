from typing import Literal
from pydantic import BaseModel

# AGENT-CTX: EvidenceType is the canonical enum for this slice.
# All five values are locked by the acceptance criteria — do not add/remove
# without updating the LLM prompt in llm.py and the frontend badge styles.
EvidenceType = Literal[
    "animal model",
    "human genetics",
    "clinical trial",
    "in vitro",
    "review",
]


class EvidenceItem(BaseModel):
    pmid: str
    title: str
    # AGENT-CTX: abstract is included in the API response for this slice to
    # keep the response self-contained (no follow-up fetches from frontend).
    # Future slices may drop it if payload size becomes a concern.
    abstract: str
    evidence_type: EvidenceType


class SearchResponse(BaseModel):
    query: str
    results: list[EvidenceItem]


class ErrorResponse(BaseModel):
    # AGENT-CTX: Mirrors FastAPI's default HTTPException detail shape.
    # Kept explicit so the frontend can reliably read .detail on errors.
    detail: str
