// AGENT-CTX: Canonical TypeScript types for this slice. Mirror backend/backend/models.py.
// If any Literal value changes in models.py it must be updated here and in page.tsx badge maps.
// Types are grouped: primitive enums first, then composed interfaces.

// AGENT-CTX: EvidenceType — 5 values, locked by the LLM prompt in backend/backend/llm.py.
// Do not add/remove values without updating: models.py, llm.py system prompt, page.tsx BADGE_COLOUR.
export type EvidenceType =
  | "animal model"
  | "human genetics"
  | "clinical trial"
  | "in vitro"
  | "review";

// AGENT-CTX: EffectDirection — 3 values, locked by the LLM prompt in backend/backend/llm.py.
// Mirrors backend EffectDirection Literal exactly. All three values must have a colour entry
// in page.tsx EFFECT_DIRECTION_COLOUR. Do not add values without updating the LLM system prompt.
export type EffectDirection =
  | "supports"
  | "contradicts"
  | "neutral";

// AGENT-CTX: ConfidenceTier — 3 values, derived server-side by ConfidenceEngine (backend/confidence.py).
// NOT extracted by the LLM — computed from a weighted factor pipeline after extraction.
// All three values must have a colour entry in page.tsx CONFIDENCE_TIER_COLOUR.
// Tier thresholds (high/medium/low boundaries) live in confidence.py — do not duplicate here.
export type ConfidenceTier =
  | "high"
  | "medium"
  | "low";

export interface EvidenceItem {
  pmid: string;
  title: string;
  // AGENT-CTX: abstract is included in the response payload but not rendered in the list view.
  // Retained for future detail-expansion UI without requiring an additional API call.
  abstract: string;
  evidence_type: EvidenceType;

  // AGENT-CTX: Four new fields added in Milestone 1 (Structured Evidence Extraction).
  // All fields are always present — backend never omits them (sentinel "not reported" used
  // instead of null/undefined for optional string fields). The frontend conditionally hides
  // rows where the value equals "not reported" rather than handling optional types.
  // See page.tsx for rendering logic.
  effect_direction: EffectDirection;
  // AGENT-CTX: model_organism and sample_size are plain string (not string | null).
  // Backend uses "not reported" as the sentinel. This keeps the JSON schema uniform:
  // every field is always present and always a string — no optional handling required.
  model_organism: string;
  sample_size: string;
  confidence_tier: ConfidenceTier;
}

// AGENT-CTX: SearchResponse is unchanged from the walking skeleton.
// query echoes back the user's search string; results is the ordered list of evidence items.
export interface SearchResponse {
  query: string;
  results: EvidenceItem[];
}

// AGENT-CTX: ApiError mirrors FastAPI's default HTTPException detail shape.
// Used when response.ok is false — read body.detail for the error message.
export interface ApiError {
  detail: string;
}

// ── Async job types (Milestone 3) ─────────────────────────────────────────────
// AGENT-CTX: Mirrors backend/backend/db/models.py exactly.
// If JobStatus values change there, update here and in Sidebar.tsx STATUS_CHIP_COLOUR.

export type JobStatus = "pending" | "running" | "complete" | "failed";

export interface JobSubmitResponse {
  job_id: string;
  query: string;
  status: JobStatus;
  created_at: string; // ISO datetime string from FastAPI
}

export interface JobStatusResponse {
  job_id: string;
  query: string;
  status: JobStatus;
  // AGENT-CTX: result is null until status=complete. Always check status before reading.
  result: SearchResponse | null;
  // AGENT-CTX: error is null for all non-failed states.
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobListItem {
  job_id: string;
  query: string;
  status: JobStatus;
  // AGENT-CTX: error is included in list items so the sidebar can show a failed
  // chip without a second fetch. null for non-failed jobs.
  error: string | null;
  created_at: string;
  updated_at: string;
}
