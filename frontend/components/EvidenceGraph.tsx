"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";

import { ChainMeta, EdgeResult, EvidenceItem, GraphNodeData } from "../types";
import { applyGrayOut, buildGraphData, CHAIN_LAYER_ORDER, LAYER_NAMES } from "../lib/graphUtils";
import { ChainControls }      from "./ChainControls";
import { ChainPanel }         from "./ChainPanel";
import { NodeDrawer }         from "./NodeDrawer";
import { RelationshipLegend } from "./RelationshipLegend";
import { EvidenceNode }       from "./nodes/EvidenceNode";
import { GapNode }            from "./nodes/GapNode";
import { RootNode }           from "./nodes/RootNode";

// AGENT-CTX: nodeTypes cast to `as any` is intentional and documented.
// React Flow's NodeTypes requires `Record<string, ComponentType<NodeProps<any>>>`,
// but our node components type their `data` prop as GraphNodeData (an interface).
// TypeScript cannot verify the structural compatibility here without the cast.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const nodeTypes = {
  evidence: EvidenceNode,
  gap:      GapNode,
  root:     RootNode,
} as any;

// AGENT-CTX: edges prop added in Chain Links milestone. Edges arrive pre-computed
// from the background job (compute_all_edges in backend/edges.py) and are passed
// down from page.tsx via the job result. The component no longer calculates edges
// itself — useEdgeCalculation and EdgeLoadingIndicator have been removed.
interface Props {
  items:  EvidenceItem[];
  edges:  EdgeResult[];
  query:  string;
}

export function EvidenceGraph({ items, edges, query }: Props) {
  // ── Build initial graph data from items + pre-computed edges ─────────────
  const { nodes: initialNodes, edges: initialEdges, chains: initialChains } =
    useMemo(() => buildGraphData(items, edges, query), [items, edges, query]);

  const [rfNodes, setRfNodes, onNodesChange] = useNodesState(initialNodes as any[]);
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(initialEdges as any[]);
  const [chains,  setChains]                 = useState<ChainMeta[]>(initialChains);

  // ── UI state ─────────────────────────────────────────────────────────────
  const [selectedNodeId,   setSelectedNodeId]   = useState<string | null>(null);
  const [selectedChainId,  setSelectedChainId]  = useState<string | null>(null);

  // AGENT-CTX: Exclusive visibility — only one chain visible at a time.
  // Initialised to the first chain (chains[0]) so the richest evidence chain
  // (sorted by BFS component size) is shown on load. Uses optional chaining
  // because chains may be [] when items is empty.
  const [visibleChainIds, setVisibleChainIds] = useState<Set<string>>(
    () => new Set(initialChains[0] ? [initialChains[0].id] : [])
  );

  // ── Reset when query/items/edges change ──────────────────────────────────
  // AGENT-CTX: All three props are in the dep array so that navigating to a new
  // job result (different query) fully resets the graph state. edges is included
  // because it is now part of the graph identity — a re-run of the same query
  // may produce different edges.
  useEffect(() => {
    setRfNodes(initialNodes as any[]);
    setRfEdges(initialEdges as any[]);
    setChains(initialChains);
    // AGENT-CTX: Reset visible chain to the first chain of the new result.
    // Without this, visibleChainIds could still reference stale chain IDs
    // from the previous query, hiding all nodes.
    setVisibleChainIds(new Set(initialChains[0] ? [initialChains[0].id] : []));
    setSelectedNodeId(null);
    setSelectedChainId(null);
  }, [query, items, edges]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Gray-out: apply when selectedChain has a review ──────────────────────
  // AGENT-CTX: When the user selects a chain that has a review, nodes published
  // AFTER the review year are grayed out. Deselecting the chain clears gray-out.
  useEffect(() => {
    const chain = chains.find((c) => c.id === selectedChainId);
    const reviewYear = chain?.review?.publication_year ?? null;
    setRfNodes((prev) => applyGrayOut(prev as any, reviewYear) as any[]);
  }, [selectedChainId, chains]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Node click handler ────────────────────────────────────────────────────
  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: { id: string; data: GraphNodeData }) => {
      if (node.data.nodeType !== "evidence") return;
      // Mutual exclusion: opening NodeDrawer closes ChainPanel
      setSelectedChainId(null);
      setSelectedNodeId((prev) => (prev === node.id ? null : node.id));
    },
    []
  );

  // ── Derived values ────────────────────────────────────────────────────────
  const selectedEvidence = useMemo<EvidenceItem | null>(() => {
    if (!selectedNodeId) return null;
    const node = rfNodes.find((n: any) => n.id === selectedNodeId);
    return (node?.data as GraphNodeData | undefined)?.evidence ?? null;
  }, [selectedNodeId, rfNodes]);

  const selectedChain = useMemo<ChainMeta | null>(
    () => chains.find((c) => c.id === selectedChainId) ?? null,
    [selectedChainId, chains]
  );

  // Only show edges belonging to visible chains
  const visibleEdges = useMemo(
    () =>
      (rfEdges as any[]).filter((e: any) =>
        (e.data?.chainIds as string[] | undefined)?.some((id) => visibleChainIds.has(id)) ?? true
      ),
    [rfEdges, visibleChainIds]
  );

  // ── Chain control handlers ────────────────────────────────────────────────
  const handleSelectChain = useCallback((chainId: string | null) => {
    // Mutual exclusion: opening ChainPanel closes NodeDrawer
    setSelectedNodeId(null);
    setSelectedChainId(chainId);
  }, []);

  // AGENT-CTX: Exclusive toggle — clicking a chain shows ONLY that chain.
  // Previously this was additive (checkbox multi-select). The new UX matches
  // the brief: "one chain visible at a time, toggleable through the legend".
  // ChainControls.tsx is updated to reflect this (no checkbox, radio-style).
  const handleToggleChain = useCallback((chainId: string) => {
    setVisibleChainIds(new Set([chainId]));
  }, []);

  // ── Gap layer legend (outside canvas) ────────────────────────────────────
  const gapLayers = useMemo(() => {
    const presentLayers = new Set(items.map((i) => i.layer));
    return CHAIN_LAYER_ORDER.filter((l) => !presentLayers.has(l));
  }, [items]);

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <ReactFlow
        nodes={rfNodes}
        edges={visibleEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick as any}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={2}
      >
        <Background gap={20} color="#f0f0f0" />
        <Controls />

        {/* Top-left: chain visibility + selection */}
        <ChainControls
          chains={chains}
          selectedChainId={selectedChainId}
          visibleChainIds={visibleChainIds}
          onSelectChain={handleSelectChain}
          onToggleChain={handleToggleChain}
        />

        {/* Bottom-right: edge type legend */}
        <RelationshipLegend visible={visibleEdges.length > 0} />
      </ReactFlow>

      {/* Gap layer legend — outside the React Flow transform */}
      {gapLayers.length > 0 && (
        <div
          style={{
            position:        "absolute",
            bottom:          12,
            left:            "50%",
            transform:       "translateX(-50%)",
            fontSize:        "0.72rem",
            color:           "#999",
            backgroundColor: "#fff",
            border:          "1px solid #e0e0e0",
            borderRadius:    4,
            padding:         "0.2rem 0.6rem",
            zIndex:          5,
          }}
        >
          Gap layers: {gapLayers.map((l) => LAYER_NAMES[l]).join(", ")}
        </div>
      )}

      {/* Fixed-position drawers — escape React Flow's transform */}
      <NodeDrawer
        evidence={selectedEvidence}
        onClose={() => setSelectedNodeId(null)}
      />
      <ChainPanel
        chain={selectedChain}
        onClose={() => setSelectedChainId(null)}
      />
    </div>
  );
}
