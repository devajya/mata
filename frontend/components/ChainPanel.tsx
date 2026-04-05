"use client";

import { ChainMeta } from "../types";

interface Props {
  chain: ChainMeta | null; // null = panel closed
  onClose: () => void;
}

/**
 * Fixed-position panel showing chain metadata, opened by clicking a chain label
 * in ChainControls.
 *
 * AGENT-CTX: Same fixed-position / scrim pattern as NodeDrawer.
 * Left border color = chain.color (vs NodeDrawer which uses confidence tier color).
 * Visual distinction: opening a ChainPanel tells you about the chain identity,
 * not an individual evidence item.
 *
 * AGENT-CTX: Gray-out explanation is shown when a review is present.
 * The actual gray-out is driven by EvidenceGraph.tsx (which calls applyGrayOut
 * when selectedChainId changes to a chain with a review). ChainPanel only
 * EXPLAINS the feature — it does not own the gray-out logic itself.
 *
 * AGENT-CTX: Known bug from previous session — verify that opening ChainPanel
 * for a chain with a review correctly triggers gray-out in EvidenceGraph.tsx.
 * The wiring: EvidenceGraph watches selectedChainId → finds chain → reads
 * chain.review?.publication_year → calls applyGrayOut(nodes, reviewYear).
 */
export function ChainPanel({ chain, onClose }: Props) {
  if (!chain) return null;

  return (
    <>
      {/* Scrim */}
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
        aria-label="Evidence chain detail"
        style={{
          position:        "fixed",
          top:             0,
          right:           0,
          width:           380,
          height:          "100vh",
          overflowY:       "auto",
          backgroundColor: "#fff",
          borderLeft:      `4px solid ${chain.color}`,
          boxShadow:       "-4px 0 16px rgba(0,0,0,0.12)",
          zIndex:          41,
          padding:         "1.25rem",
          display:         "flex",
          flexDirection:   "column",
          gap:             "0.75rem",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 600 }}>
            <span style={{ color: chain.color, marginRight: "0.4rem" }}>◉</span>
            {chain.label}
          </h2>
          <button
            onClick={onClose}
            aria-label="Close chain panel"
            style={{ border: "none", background: "none", cursor: "pointer", fontSize: "1.2rem", color: "#666" }}
          >
            ×
          </button>
        </div>

        <p style={{ margin: 0, fontSize: "0.82rem", color: "#555" }}>
          {chain.nodeIds.length} evidence node{chain.nodeIds.length !== 1 ? "s" : ""} in this chain.
        </p>

        {/* Review section */}
        {chain.review ? (
          <div
            style={{
              padding:      "0.75rem",
              borderRadius: 6,
              border:       "1px solid #e0e0e0",
              backgroundColor: "#fafafa",
              display:      "flex",
              flexDirection: "column",
              gap:          "0.4rem",
            }}
          >
            <p style={{ margin: 0, fontSize: "0.72rem", color: "#888", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em" }}>
              Associated Review
            </p>
            <p style={{ margin: 0, fontSize: "0.85rem", fontWeight: 500, lineHeight: 1.4 }}>
              {chain.review.title}
            </p>
            {chain.review.publication_year && (
              <p style={{ margin: 0, fontSize: "0.78rem", color: "#555" }}>
                <span
                  style={{
                    backgroundColor: "#1a6faf",
                    color: "#fff",
                    padding: "0.1rem 0.4rem",
                    borderRadius: 3,
                    fontSize: "0.68rem",
                    fontWeight: 600,
                    marginRight: "0.4rem",
                  }}
                >
                  {chain.review.publication_year}
                </span>
                Evidence published after {chain.review.publication_year} is grayed out.
              </p>
            )}
            <a
              href={`https://pubmed.ncbi.nlm.nih.gov/${chain.review.pmid}/`}
              target="_blank"
              rel="noopener noreferrer"
              style={{ fontSize: "0.78rem", color: "#1a6faf" }}
            >
              Open review in PubMed ↗
            </a>
          </div>
        ) : (
          <p style={{ margin: 0, fontSize: "0.82rem", color: "#888", fontStyle: "italic" }}>
            No review paper associated with this chain.
          </p>
        )}
      </aside>
    </>
  );
}
