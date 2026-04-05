"use client";

import { Handle, Position } from "@xyflow/react";
import { GraphNodeData } from "../../types";

interface Props {
  data: GraphNodeData;
}

/**
 * Root node — represents the search query, anchors the left side of the graph.
 *
 * AGENT-CTX: Pill shape (borderRadius 24) distinguishes root from evidence nodes.
 * Dark background signals it is the conceptual origin, not an evidence item.
 * Not clickable — it has no EvidenceItem to show in a drawer.
 *
 * AGENT-CTX: Source handle only (Position.Right). Chains flow left→right.
 * Root → Layer 0 (in vitro) → Layer 1 (animal) → ... edges will be added
 * when buildEdges() is implemented.
 */
export function RootNode({ data }: Props) {
  return (
    <>
      <div
        style={{
          padding: "0.5rem 1.25rem",
          borderRadius: 24,
          backgroundColor: "#1a1a2e",
          color: "#fff",
          fontSize: "0.82rem",
          fontWeight: 600,
          whiteSpace: "nowrap",
          userSelect: "none",
          cursor: "default",
        }}
      >
        {data.layerName}
      </div>
      <Handle type="source" position={Position.Right} />
    </>
  );
}
