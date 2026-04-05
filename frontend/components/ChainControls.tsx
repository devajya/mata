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
 * AGENT-CTX: Each row has:
 *   - Color dot (●) for visual chain identity
 *   - Label button → toggles ChainPanel open/close for that chain
 *   - Checkbox → toggles edge visibility for that chain
 * Selected row gets a subtle highlight (#f0f4ff background).
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
          margin:          "0 0 0.4rem 0",
          fontSize:        "0.65rem",
          fontWeight:      700,
          color:           "#888",
          textTransform:   "uppercase",
          letterSpacing:   "0.06em",
        }}
      >
        Evidence Chains
      </p>

      {chains.map((chain) => {
        const isSelected = chain.id === selectedChainId;
        const isVisible  = visibleChainIds.has(chain.id);

        return (
          <div
            key={chain.id}
            style={{
              display:         "flex",
              alignItems:      "center",
              gap:             "0.4rem",
              padding:         "0.25rem 0.35rem",
              borderRadius:    4,
              backgroundColor: isSelected ? "#f0f4ff" : "transparent",
              marginBottom:    2,
            }}
          >
            {/* Color dot */}
            <span style={{ color: chain.color, fontSize: "1rem", lineHeight: 1, flexShrink: 0 }}>
              ●
            </span>

            {/* Chain label button — opens/closes ChainPanel */}
            <button
              onClick={() => onSelectChain(isSelected ? null : chain.id)}
              aria-pressed={isSelected}
              style={{
                border:          "none",
                background:      "none",
                cursor:          "pointer",
                fontSize:        "0.78rem",
                fontWeight:      isSelected ? 600 : 400,
                color:           "#333",
                padding:         0,
                textAlign:       "left",
                flex:            1,
              }}
            >
              {chain.label}
            </button>

            {/* Visibility checkbox */}
            <input
              type="checkbox"
              checked={isVisible}
              onChange={() => onToggleChain(chain.id)}
              aria-label={`Toggle visibility of ${chain.label}`}
              style={{ cursor: "pointer", flexShrink: 0 }}
            />
          </div>
        );
      })}
    </div>
  );
}
