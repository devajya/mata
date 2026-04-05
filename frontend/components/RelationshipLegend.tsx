"use client";

import { RELATIONSHIP_STYLES } from "../lib/mockData";
import { RelationshipType } from "../types";

interface Props {
  visible: boolean;
}

const RELATIONSHIP_TYPES: RelationshipType[] = [
  "supports",
  "extends",
  "replicates",
  "contextualizes",
];

/**
 * Visual key for edge relationship types. Shown when edges are present (visible=true).
 *
 * AGENT-CTX: position:absolute, bottom-right, above EdgeLoadingIndicator (72px vs 40px).
 * Rendered null when visible=false to avoid showing a legend for an empty graph.
 */
export function RelationshipLegend({ visible }: Props) {
  if (!visible) return null;

  return (
    <div
      style={{
        position:        "absolute",
        bottom:          72,
        right:           12,
        zIndex:          6,
        backgroundColor: "#fff",
        border:          "1px solid #e0e0e0",
        borderRadius:    6,
        padding:         "0.5rem 0.7rem",
        boxShadow:       "0 1px 4px rgba(0,0,0,0.08)",
        minWidth:        160,
      }}
    >
      <p style={{ margin: "0 0 0.4rem 0", fontSize: "0.65rem", fontWeight: 700, color: "#888", textTransform: "uppercase", letterSpacing: "0.06em" }}>
        Connections
      </p>
      {RELATIONSHIP_TYPES.map((type) => {
        const style = RELATIONSHIP_STYLES[type];
        return (
          <div key={type} style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: 4 }}>
            {/* Line preview */}
            <div
              style={{
                width:       28,
                height:      0,
                borderTop:   `2px ${style.dash === "none" ? "solid" : "dashed"} ${style.color}`,
                flexShrink:  0,
              }}
            />
            <span style={{ fontSize: "0.72rem", color: "#444" }}>{style.label}</span>
          </div>
        );
      })}
    </div>
  );
}
