"use client";

import { EdgeType } from "../types";
import { EDGE_TYPE_STYLES } from "../lib/graphUtils";

// AGENT-CTX: EDGE_TYPE_STYLES is the single source of truth, defined in graphUtils.ts
// so buildEdges() and this legend always stay in sync. Any future agent adding a new
// EdgeType must update: graphUtils.ts EDGE_TYPE_STYLES, backend models.py EdgeType
// Literal, edges.py _EDGE_SYSTEM_PROMPT, and frontend types.ts EdgeType.
const EDGE_STYLES = EDGE_TYPE_STYLES;

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
