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

  // AGENT-CTX: Milestone 2 fields. layer is assigned by assign_layer() in graph.py —
  // never by the LLM. -1 = review (excluded from graph nodes). 0-3 = chain layers.
  // publication_year is null when PubMed XML does not include a parseable year;
  // items with null year are never grayed out by ChainPanel's temporal filter.
  layer: number;
  publication_year: number | null;
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

// ── Graph view types (Milestone 2) ────────────────────────────────────────────
// AGENT-CTX: ChainMeta lives in types.ts (not graphUtils.ts) so ChainPanel and
// ChainControls can import it without transitively importing @xyflow/react.
// Keeping @xyflow/react imports isolated to EvidenceGraph.tsx + node components
// allows graphUtils.ts and the panel components to be Jest-tested without canvas mocks.

export interface ChainMeta {
  id: string;
  label: string;       // e.g. "Evidence Chain 1"
  color: string;       // hex color, used for edges and left border accent
  nodeIds: string[];   // pmid-based node IDs that belong to this chain
  edgeIds: string[];   // edge IDs that belong to this chain
  // AGENT-CTX: review is null when no review paper is in the result set.
  // When non-null, ChainPanel shows the review title/year and ChainControls
  // uses review.publication_year to drive gray-out via applyGrayOut().
  review: EvidenceItem | null;
}

// AGENT-CTX: GraphNodeData is the data payload on React Flow nodes. It does NOT
// import from @xyflow/react — it is cast to Node<GraphNodeData> at the ReactFlow
// boundary in EvidenceGraph.tsx. This keeps graphUtils.ts and node components
// testable in Jest without needing to mock the React Flow canvas.
export interface GraphNodeData {
  nodeType: "evidence" | "gap" | "root";
  layer: number;                    // -1 to 3
  evidence: EvidenceItem | null;    // null for gap and root nodes
  layerName: string;                // human-readable (e.g. "In Vitro")
  chainIds: string[];               // which chains this node belongs to
  grayedOut: boolean;               // set by applyGrayOut() in EvidenceGraph
}

// AGENT-CTX: RelationshipType — 4 semantic edge categories.
// These describe the logical relationship between two evidence nodes.
// buildEdges() is currently a stub returning [] — this type is used by
// mockData.ts and will be used by the real edge calculation when implemented.
export type RelationshipType =
  | "supports"        // downstream evidence confirms the upstream finding
  | "extends"         // builds upon the upstream mechanism
  | "replicates"      // independent confirmation of the same finding
  | "contextualizes"; // provides mechanistic context for the upstream node

export interface GraphEdgeData {
  chainIds: string[];
  relationshipType: RelationshipType;
}
