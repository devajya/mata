"use client";

import { EvidenceItem } from "../types";

const TIER_COLOUR: Record<string, string> = {
  high:   "#2d6a4f",
  medium: "#e07c00",
  low:    "#888888",
};

const EFFECT_COLOUR: Record<string, string> = {
  supports:    "#2d6a4f",
  contradicts: "#c00000",
  neutral:     "#666666",
};

interface Props {
  evidence: EvidenceItem | null; // null = drawer closed
  onClose: () => void;
}

/**
 * Fixed-position detail panel that opens when an EvidenceNode is clicked.
 *
 * AGENT-CTX: Uses position:fixed to escape React Flow's pan/zoom CSS transform.
 * If position:absolute were used, the drawer would move with the graph canvas
 * when the user pans. Fixed anchors it to the viewport.
 *
 * AGENT-CTX: NodeDrawer and ChainPanel are mutually exclusive — only one open
 * at a time. This exclusion is enforced in EvidenceGraph.tsx via selectedNodeId
 * and selectedChainId state: setting one clears the other.
 */
export function NodeDrawer({ evidence, onClose }: Props) {
  if (!evidence) return null;

  const tierColor = TIER_COLOUR[evidence.confidence_tier] ?? "#888";

  return (
    <>
      {/* Semi-transparent scrim — clicking it closes the drawer */}
      <div
        onClick={onClose}
        style={{
          position:        "fixed",
          inset:           0,
          backgroundColor: "rgba(0,0,0,0.15)",
          zIndex:          40,
        }}
      />

      <aside
        aria-label="Evidence detail"
        style={{
          position:        "fixed",
          top:             0,
          right:           0,
          width:           380,
          height:          "100vh",
          overflowY:       "auto",
          backgroundColor: "#fff",
          borderLeft:      `4px solid ${tierColor}`,
          boxShadow:       "-4px 0 16px rgba(0,0,0,0.12)",
          zIndex:          41,
          padding:         "1.25rem",
          display:         "flex",
          flexDirection:   "column",
          gap:             "0.75rem",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "0.5rem" }}>
          <h2 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 600, lineHeight: 1.4, flex: 1 }}>
            {evidence.title}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close detail panel"
            style={{
              border:          "none",
              background:      "none",
              cursor:          "pointer",
              fontSize:        "1.2rem",
              color:           "#666",
              padding:         "0 0.25rem",
              flexShrink:      0,
            }}
          >
            ×
          </button>
        </div>

        {/* Badge strip */}
        <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
          <Chip label={evidence.evidence_type} color="#1a6faf" />
          <Chip label={evidence.confidence_tier} color={tierColor} />
          {evidence.publication_year && (
            <Chip label={String(evidence.publication_year)} color="#555" />
          )}
        </div>

        {/* Effect direction */}
        <Row label="Direction">
          <span style={{ fontWeight: 600, color: EFFECT_COLOUR[evidence.effect_direction] ?? "#666" }}>
            {evidence.effect_direction}
          </span>
        </Row>

        {/* Conditional fields */}
        {evidence.model_organism && evidence.model_organism !== "not reported" && (
          <Row label="Organism">{evidence.model_organism}</Row>
        )}
        {evidence.sample_size && evidence.sample_size !== "not reported" && (
          <Row label="Sample">{evidence.sample_size}</Row>
        )}

        {/* Abstract preview */}
        <div>
          <p style={{ margin: "0 0 0.35rem 0", fontSize: "0.75rem", color: "#888", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>
            Abstract
          </p>
          <p style={{ margin: 0, fontSize: "0.82rem", color: "#333", lineHeight: 1.5 }}>
            {evidence.abstract.length > 500
              ? `${evidence.abstract.slice(0, 500)}…`
              : evidence.abstract || "No abstract available."}
          </p>
        </div>

        {/* PubMed link */}
        <a
          href={`https://pubmed.ncbi.nlm.nih.gov/${evidence.pmid}/`}
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display:         "inline-block",
            marginTop:       "0.25rem",
            padding:         "0.45rem 0.9rem",
            backgroundColor: "#1a6faf",
            color:           "#fff",
            borderRadius:    4,
            fontSize:        "0.82rem",
            fontWeight:      600,
            textDecoration:  "none",
            textAlign:       "center",
          }}
        >
          Open in PubMed ↗
        </a>
      </aside>
    </>
  );
}

function Chip({ label, color }: { label: string; color: string }) {
  return (
    <span
      style={{
        fontSize:        "0.68rem",
        fontWeight:      600,
        padding:         "0.15rem 0.45rem",
        borderRadius:    3,
        backgroundColor: color,
        color:           "#fff",
        textTransform:   "uppercase",
        letterSpacing:   "0.03em",
      }}
    >
      {label}
    </span>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <p style={{ margin: 0, fontSize: "0.82rem" }}>
      <span style={{ color: "#888", marginRight: "0.3rem" }}>{label}:</span>
      {children}
    </p>
  );
}
