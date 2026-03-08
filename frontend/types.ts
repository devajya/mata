// AGENT-CTX: Canonical TypeScript types for this slice. Mirror backend/models.py.
// If EvidenceType values change in models.py, update here too (and the badge styles in page.tsx).
// These are the ONLY valid evidence type strings — do not add values without updating the LLM prompt.

export type EvidenceType =
  | "animal model"
  | "human genetics"
  | "clinical trial"
  | "in vitro"
  | "review";

export interface EvidenceItem {
  pmid: string;
  title: string;
  // AGENT-CTX: abstract is included in response payload for this slice.
  // Not rendered in the list view but available for future detail expansion.
  abstract: string;
  evidence_type: EvidenceType;
}

export interface SearchResponse {
  query: string;
  results: EvidenceItem[];
}

export interface ApiError {
  // AGENT-CTX: Mirrors FastAPI's default HTTPException detail shape.
  detail: string;
}
