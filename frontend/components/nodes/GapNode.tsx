"use client";

import { GraphNodeData } from "../../types";

interface Props {
  data: GraphNodeData;
}

/**
 * Placeholder node shown when a layer has no evidence.
 *
 * AGENT-CTX: GapNode communicates "the evidence chain has a gap at this stage"
 * not an error. Dashed border (vs. EvidenceNode solid) makes the distinction
 * immediately visible. Gap nodes are never grayed out — they are always visible
 * regardless of ChainPanel review year selection.
 *
 * AGENT-CTX: Not clickable — cursor:default, no onClick. GapNodes have no
 * evidence to show in a NodeDrawer, so clicks would be dead UX.
 */
export function GapNode({ data }: Props) {
  return (
    <div
      style={{
        width: 200,
        padding: "0.6rem 0.75rem",
        borderRadius: 6,
        border: "2px dashed #cccccc",
        backgroundColor: "#f8f8f8",
        cursor: "default",
        userSelect: "none",
      }}
    >
      <p
        style={{
          margin: 0,
          fontSize: "0.78rem",
          color: "#999",
          fontStyle: "italic",
          lineHeight: 1.35,
          textAlign: "center",
        }}
      >
        No {data.layerName} evidence found
      </p>
    </div>
  );
}
