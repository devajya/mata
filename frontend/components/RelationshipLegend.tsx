"use client";

import { EdgeType } from "../types";

// AGENT-CTX: EDGE_STYLES moved here from mockData.ts (deleted in Chain Links milestone).
// Defined inline in this file so RelationshipLegend has no external style dependency.
// Any future agent adding a new EdgeType must add a corresponding entry here AND
// update backend EdgeType Literal in models.py, edges.py _EDGE_SYSTEM_PROMPT,
// and frontend EdgeType in types.ts. All four locations must stay in sync.
const EDGE_STYLES: Record<EdgeType, { color: string; dash: string; label: string }> = {
  supports:                   { color: "#2d6a4f", dash: "none",      label: "Supports" },
  contradicts:                { color: "#c0392b", dash: "none",      label: "Contradicts" },
  contradicts_methodological: { color: "#e67e22", dash: "4,2",      label: "Contradicts (method)" },
  translates:                 { color: "#1a6faf", dash: "none",      label: "Translates" },
  fails_to_translate:         { color: "#8e44ad", dash: "8,3",      label: "Fails to Translate" },
  mechanistically_extends:    { color: "#16a085", dash: "6,3",      label: "Extends Mechanism" },
  qualifies:                  { color: "#d4ac0d", dash: "4,2",      label: "Qualifies" },
  combination_context:        { color: "#2980b9", dash: "2,2",      label: "Combination" },
  resistance_link:            { color: "#c0392b", dash: "8,4,2,4", label: "Resistance" },
  replicates:                 { color: "#6a3d9a", dash: "2,2",      label: "Replicates" },
};

interface Props {
  visible: boolean;
}

/**
 * Bottom-right overlay showing the edge type legend.
 *
 * AGENT-CTX: Legend is hidden (returns null) when no edges are visible in the graph.
 * This avoids showing a legend before the job result arrives or when the result has
 * no edges (compute_all_edges returned []). Controlled by the visible prop passed
 * from EvidenceGraph.tsx based on visibleEdges.length > 0.
 *
 * AGENT-CTX: Dash patterns are SVG stroke-dasharray values (e.g. "4,2").
 * Rendered using a short <svg> line in each legend row — not as CSS borders —
 * so the pattern accurately previews what React Flow renders on the canvas.
 */
export function RelationshipLegend({ visible }: Props) {
  if (!visible) return null;

  return (
    <div
      style={{
        position:        "absolute",
        bottom:          12,
        right:           12,
        zIndex:          5,
        backgroundColor: "#fff",
        border:          "1px solid #e0e0e0",
        borderRadius:    6,
        padding:         "0.5rem 0.75rem",
        boxShadow:       "0 1px 4px rgba(0,0,0,0.08)",
        maxWidth:        200,
      }}
    >
      <p
        style={{
          margin:        "0 0 0.4rem 0",
          fontSize:      "0.65rem",
          fontWeight:    700,
          color:         "#888",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
        }}
      >
        Edge Types
      </p>

      {(Object.entries(EDGE_STYLES) as [EdgeType, (typeof EDGE_STYLES)[EdgeType]][]).map(
        ([edgeType, style]) => (
          <div
            key={edgeType}
            style={{
              display:      "flex",
              alignItems:   "center",
              gap:          "0.5rem",
              marginBottom: 3,
            }}
          >
            {/* AGENT-CTX: SVG line preview matches React Flow's edge stroke rendering.
                strokeDasharray "none" renders as a solid line (undefined = omit attr). */}
            <svg width={28} height={10} style={{ flexShrink: 0 }}>
              <line
                x1={0} y1={5} x2={28} y2={5}
                stroke={style.color}
                strokeWidth={2}
                strokeDasharray={style.dash === "none" ? undefined : style.dash}
              />
            </svg>
            <span style={{ fontSize: "0.72rem", color: "#333" }}>{style.label}</span>
          </div>
        )
      )}
    </div>
  );
}
