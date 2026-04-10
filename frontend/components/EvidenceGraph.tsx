"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Edge,
  Node,
  NodeTypes,
  ReactFlow,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";

import { ChainMeta, EdgeResult, EvidenceItem, GraphNodeData } from "../types";
import { applyGrayOut, buildGraphData, CHAIN_LAYER_ORDER, GraphEdge, GraphNode, LAYER_NAMES } from "../lib/graphUtils";
import { ChainControls }      from "./ChainControls";
import { ChainPanel }         from "./ChainPanel";
import { NodeDrawer }         from "./NodeDrawer";
import { RelationshipLegend } from "./RelationshipLegend";
import { EvidenceNode }       from "./nodes/EvidenceNode";
import { GapNode }            from "./nodes/GapNode";
import { RootNode }           from "./nodes/RootNode";

// ── React Flow type aliases ────────────────────────────────────────────────────
// AGENT-CTX: These aliases pin the generic parameters at the library boundary so
// the rest of the component is typed against concrete types, not raw `any`.
// Record<string, unknown> satisfies Node/Edge's generic constraint while remaining
// compatible with GraphNodeData/GraphEdgeData (which are subsets of that shape).
type RFNode = Node<Record<string, unknown>>;
type RFEdge = Edge<Record<string, unknown>>;

// ── Adapter functions (boundary casts, isolated to one place each) ─────────────
// AGENT-CTX: graphUtils.ts intentionally avoids importing @xyflow/react so it
// stays Jest-testable without canvas mocks. These adapters are the single crossing
// point where our internal GraphNode/GraphEdge shapes become React Flow types.
// The double-cast (as unknown as) is accepted here because the shapes are
// structurally compatible — both have id, position, data — and isolating the cast
// means a future shape change only requires updating these three functions.
function asRFNodes(nodes: GraphNode[]): RFNode[] {
  return nodes as unknown as RFNode[];
}
function asRFEdges(edges: GraphEdge[]): RFEdge[] {
  return edges as unknown as RFEdge[];
}
function asGraphNodes(nodes: RFNode[]): GraphNode[] {
  return nodes as unknown as GraphNode[];
}

// AGENT-CTX: NodeTypes cast to `as NodeTypes` (not `as any`) — typed, not a
// blanket suppression. NodeTypes is `Record<string, ComponentType<NodeProps<any>>>`.
// Our node components accept `{ data: GraphNodeData; selected?: boolean }` which
// is structurally compatible but TypeScript cannot verify it across the library
// boundary due to ComponentType contravariance. `as NodeTypes` is the minimal
// cast that preserves compile-time identity checking on the keys ("evidence",
// "gap", "root") while accepting the known-safe data prop incompatibility.
const nodeTypes = {
  evidence: EvidenceNode,
  gap:      GapNode,
  root:     RootNode,
} as NodeTypes;

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

  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<RFNode>(asRFNodes(initialNodes));
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState<RFEdge>(asRFEdges(initialEdges));
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
    setRfNodes(asRFNodes(initialNodes));
    setRfEdges(asRFEdges(initialEdges));
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
    setRfNodes((prev) => asRFNodes(applyGrayOut(asGraphNodes(prev), reviewYear)));
  }, [selectedChainId, chains]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Node click handler ────────────────────────────────────────────────────
  // AGENT-CTX: Typed as (event, node: RFNode) so it satisfies NodeMouseHandler<RFNode>
  // and can be passed to ReactFlow's onNodeClick prop without casting. The data cast
  // to GraphNodeData is explicit and isolated here — the only place we cross from
  // Record<string, unknown> back to the known-typed shape.
  const onNodeClick = useCallback(
    (_event: React.MouseEvent, node: RFNode) => {
      const data = node.data as unknown as GraphNodeData;
      if (data.nodeType !== "evidence") return;
      // Mutual exclusion: opening NodeDrawer closes ChainPanel
      setSelectedChainId(null);
      setSelectedNodeId((prev) => (prev === node.id ? null : node.id));
    },
    []
  );

  // ── Derived values ────────────────────────────────────────────────────────
  const selectedEvidence = useMemo<EvidenceItem | null>(() => {
    if (!selectedNodeId) return null;
    const node = rfNodes.find((n) => n.id === selectedNodeId);
    // AGENT-CTX: node.data is Record<string, unknown> at the RFNode boundary.
    // Cast to GraphNodeData here — the only typed access point for node data.
    return (node?.data as unknown as GraphNodeData | undefined)?.evidence ?? null;
  }, [selectedNodeId, rfNodes]);

  const selectedChain = useMemo<ChainMeta | null>(
    () => chains.find((c) => c.id === selectedChainId) ?? null,
    [selectedChainId, chains]
  );

  // Only show edges belonging to visible chains
  const visibleEdges = useMemo(
    () =>
      rfEdges.filter((e) =>
        // AGENT-CTX: e.data is Record<string, unknown>; chainIds cast is the typed
        // access point for edge data — mirrors the GraphNodeData cast pattern above.
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
        onNodeClick={onNodeClick}
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
