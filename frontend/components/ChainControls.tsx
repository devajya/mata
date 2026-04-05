"use client";

import { ChainMeta } from "../types";

interface Props {
  chains: ChainMeta[];
  selectedChainId: string | null;
  visibleChainIds: Set<string>;
  onSelectChain: (chainId: string | null) => void;
  onToggleChain: (chainId: string) => void;
}

/**
 * Top-left overlay showing chain identity + visibility controls.
 *
 * AGENT-CTX: Exclusive visibility model (Chain Links milestone).
 * Previously each chain had an independent checkbox (additive multi-select).
 * Now clicking a chain row makes it the ONLY visible chain — radio-button UX.
 * The checkbox is removed; the entire row is a single clickable area that
 * calls both onToggleChain (visibility) and onSelectChain (panel) on click.
 *
 * AGENT-CTX: Visual indicator for the active (visible) chain:
 *   - Bold label when the chain is in visibleChainIds
 *   - Colored left border (chain.color) on the active row
 *   - Subtle blue background when ChainPanel is open (selectedChainId match)
 * The active chain and the selected chain are independent states — a chain can
 * be visible without its panel open, and vice versa (though toggling closes panel).
 *
 * AGENT-CTX: position:absolute puts this inside React Flow's container div,
 * which already has position:relative. z-index 5 places it above the canvas
 * but below the NodeDrawer/ChainPanel scrim (z-index 40).
 */
export function ChainControls({
  chains,
  selectedChainId,
  visibleChainIds,
  onSelectChain,
  onToggleChain,
}: Props) {
  if (chains.length === 0) return null;

  return (
    <div
      style={{
        position:        "absolute",
        top:             12,
        left:            12,
        zIndex:          5,
        backgroundColor: "#fff",
        border:          "1px solid #e0e0e0",
        borderRadius:    6,
        padding:         "0.5rem 0.6rem",
        minWidth:        170,
        boxShadow:       "0 1px 4px rgba(0,0,0,0.08)",
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
        Evidence Chains
      </p>

      {chains.map((chain) => {
        const isSelected = chain.id === selectedChainId;
        const isVisible  = visibleChainIds.has(chain.id);

        return (
          // AGENT-CTX: The entire row is a single button-like div to merge the old
          // "label click = open panel" + "checkbox click = toggle visibility" into
          // a single interaction: click row → show this chain exclusively + open panel.
          // This matches the "one chain at a time" exclusive-visibility spec.
          <div
            key={chain.id}
            role="button"
            tabIndex={0}
            onClick={() => {
              // AGENT-CTX: onToggleChain sets visibleChainIds = new Set([chainId])
              // in EvidenceGraph (exclusive mode). Calling it here ensures clicking
              // any chain in ChainControls activates that chain's edges/nodes.
              onToggleChain(chain.id);
              // Also toggle ChainPanel (open if different chain, close if same)
              onSelectChain(isSelected ? null : chain.id);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onToggleChain(chain.id);
                onSelectChain(isSelected ? null : chain.id);
              }
            }}
            aria-pressed={isVisible}
            aria-label={`Show ${chain.label}`}
            style={{
              display:         "flex",
              alignItems:      "center",
              gap:             "0.4rem",
              padding:         "0.25rem 0.35rem 0.25rem 0.5rem",
              borderRadius:    4,
              // AGENT-CTX: Colored left border on the active (visible) row gives
              // a persistent visual anchor for which chain is currently shown,
              // matching chain.color so it maps to the same color as the edges.
              borderLeft:      isVisible ? `3px solid ${chain.color}` : "3px solid transparent",
              backgroundColor: isSelected ? "#f0f4ff" : "transparent",
              marginBottom:    2,
              cursor:          "pointer",
              userSelect:      "none",
              transition:      "background-color 0.1s",
            }}
          >
            {/* Color dot */}
            <span style={{ color: chain.color, fontSize: "1rem", lineHeight: 1, flexShrink: 0 }}>
              ●
            </span>

            {/* Chain label — bold when active (visible) */}
            <span
              style={{
                fontSize:   "0.78rem",
                fontWeight: isVisible ? 600 : 400,
                color:      "#333",
                flex:       1,
              }}
            >
              {chain.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}
