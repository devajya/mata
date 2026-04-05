"use client";

// AGENT-CTX: No @xyflow/react import here — node components receive data via props
// from React Flow but do not import the library directly. This keeps them testable
// in Jest without mocking @xyflow/react. The Handle component IS imported because
// it renders the connection points that React Flow needs for edge routing.
import { Handle, Position } from "@xyflow/react";
import { GraphNodeData } from "../../types";

// AGENT-CTX: Border colour signals confidence tier — mirrors the badge colours
// in page.tsx CONFIDENCE_TIER_COLOUR. Must stay in sync if tiers change.
const TIER_BORDER: Record<string, string> = {
  high:   "#2d6a4f",
  medium: "#e07c00",
  low:    "#cccccc",
};

const BADGE_COLOUR: Record<string, string> = {
  "clinical trial": "#1a6faf",
  "animal model":   "#6a3d9a",
  "human genetics": "#33a02c",
  "in vitro":       "#b15928",
  "review":         "#888888",
};

interface Props {
  data: GraphNodeData;
  selected?: boolean;
}

export function EvidenceNode({ data, selected }: Props) {
  const { evidence, grayedOut } = data;
  if (!evidence) return null;

  const borderColor = TIER_BORDER[evidence.confidence_tier] ?? "#cccccc";

  return (
    <>
      {/* AGENT-CTX: Left handle receives edges from earlier-layer nodes / root. */}
      <Handle type="target" position={Position.Left} />

      <div
        style={{
          width: 200,
          padding: "0.6rem 0.75rem",
          borderRadius: 6,
          border: `2px solid ${selected ? "#1a6faf" : borderColor}`,
          backgroundColor: "#fff",
          boxShadow: selected ? "0 0 0 2px #1a6faf44" : "0 1px 3px rgba(0,0,0,0.08)",
          cursor: "pointer",
          opacity: grayedOut ? 0.35 : 1,
          transition: "opacity 0.2s ease",
        }}
      >
        {/* Evidence type badge */}
        <div style={{ marginBottom: "0.35rem" }}>
          <span
            style={{
              fontSize: "0.65rem",
              fontWeight: 700,
              padding: "0.1rem 0.4rem",
              borderRadius: 3,
              backgroundColor: BADGE_COLOUR[evidence.evidence_type] ?? "#888",
              color: "#fff",
              textTransform: "uppercase",
              letterSpacing: "0.03em",
            }}
          >
            {evidence.evidence_type}
          </span>
        </div>

        {/* Title — 2-line truncation */}
        <p
          style={{
            margin: "0 0 0.3rem 0",
            fontSize: "0.78rem",
            fontWeight: 500,
            lineHeight: 1.35,
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          {evidence.title}
        </p>

        {/* Confidence tier label */}
        <p
          style={{
            margin: 0,
            fontSize: "0.68rem",
            color: borderColor,
            fontWeight: 600,
          }}
        >
          {evidence.confidence_tier} confidence
          {evidence.publication_year ? ` · ${evidence.publication_year}` : ""}
        </p>
      </div>

      {/* AGENT-CTX: Right handle sends edges to later-layer nodes. */}
      <Handle type="source" position={Position.Right} />
    </>
  );
}
