/**
 * Graph assembly utilities for the Evidence Chain view.
 *
 * AGENT-CTX §1 — Edge deferral:
 * buildEdges() is intentionally a STUB returning []. Semantic edge calculation
 * requires per-abstract LLM/embedding comparison which is deferred to a future
 * slice. The graph renders correctly without edges — nodes are positioned in
 * the layer grid and the absence of lines is visually acceptable for the
 * current milestone. When real edges are implemented, REPLACE buildEdges()
 * entirely (do not wrap it) and update buildChains() to split into multiple
 * chains based on edge connectivity.
 *
 * AGENT-CTX §2 — No @xyflow/react imports:
 * This file and the node components (EvidenceNode, GapNode, RootNode) must NOT
 * import from @xyflow/react. Keeping the boundary clean means Jest can test
 * graph logic without canvas mocks. The cast to React Flow's Node<T>/Edge<T>
 * types happens ONLY in EvidenceGraph.tsx at the ReactFlow boundary.
 */

import { ChainMeta, EvidenceItem, GraphEdgeData, GraphNodeData } from "../types";

// ── Layout constants ──────────────────────────────────────────────────────────

const LAYER_SPACING_PX  = 260; // horizontal distance between layers
const NODE_SPACING_PX   = 140; // vertical distance between nodes in the same layer
const ROOT_X            = -180; // root node sits left of layer 0

// AGENT-CTX: Layer names duplicated from backend/graph.py — kept in sync manually.
// If a layer is added/removed in graph.py, update this map too.
export const LAYER_NAMES: Record<number, string> = {
  "-1": "Review",
   0:   "In Vitro",
   1:   "Animal Model",
   2:   "Human Genetics",
   3:   "Clinical Trial",
};

export const CHAIN_LAYER_ORDER = [0, 1, 2, 3];

// AGENT-CTX: Chain colours — one per possible chain. Single chain today;
// additional colours needed when multi-chain is implemented.
const CHAIN_COLOURS = ["#1a6faf", "#6a3d9a", "#33a02c", "#b15928", "#e07c00"];

// ── Lightweight node/edge shapes (no @xyflow/react dependency) ────────────────

export interface GraphNode {
  id: string;
  type: "evidence" | "gap" | "root";
  position: { x: number; y: number };
  data: GraphNodeData;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  data: GraphEdgeData;
}

// ── Entry point ───────────────────────────────────────────────────────────────

export function buildGraphData(
  items: EvidenceItem[],
  query: string,
): { nodes: GraphNode[]; edges: GraphEdge[]; chains: ChainMeta[] } {
  const reviews     = items.filter((i) => i.layer === -1);
  const chainItems  = items.filter((i) => i.layer >= 0);

  const nodes  = buildNodes(chainItems, query);
  const edges  = buildEdges(nodes, "chain-0");
  const chains = buildChains(nodes, edges, reviews);
  assignPositions(nodes);

  return { nodes, edges, chains };
}

// ── Node builders ─────────────────────────────────────────────────────────────

function buildNodes(chainItems: EvidenceItem[], query: string): GraphNode[] {
  const nodes: GraphNode[] = [];

  // Root node — the search query anchor
  nodes.push({
    id:       "root",
    type:     "root",
    position: { x: ROOT_X, y: 0 }, // y updated by assignPositions
    data: {
      nodeType:  "root",
      layer:     -2,
      evidence:  null,
      layerName: query,
      chainIds:  ["chain-0"],
      grayedOut: false,
    },
  });

  // Evidence nodes — one per chain item
  for (const item of chainItems) {
    nodes.push({
      id:       `evidence-${item.pmid}`,
      type:     "evidence",
      position: { x: 0, y: 0 }, // assigned by assignPositions
      data: {
        nodeType:  "evidence",
        layer:     item.layer,
        evidence:  item,
        layerName: LAYER_NAMES[item.layer] ?? "Unknown",
        chainIds:  ["chain-0"],
        grayedOut: false,
      },
    });
  }

  // Gap nodes — one per layer that has no evidence
  const presentLayers = new Set(chainItems.map((i) => i.layer));
  for (const layer of CHAIN_LAYER_ORDER) {
    if (!presentLayers.has(layer)) {
      nodes.push({
        id:       `gap-${layer}`,
        type:     "gap",
        position: { x: 0, y: 0 },
        data: {
          nodeType:  "gap",
          layer,
          evidence:  null,
          layerName: LAYER_NAMES[layer] ?? "Unknown",
          chainIds:  [],
          grayedOut: false,
        },
      });
    }
  }

  return nodes;
}

// AGENT-CTX: buildEdges is a STUB — see module docstring §1.
// Returns [] until semantic edge calculation is implemented.
// Signature is intentionally simple: replace entirely when real edges arrive.
function buildEdges(_nodes: GraphNode[], _chainId: string): GraphEdge[] {
  return [];
}

// ── Chain builder ─────────────────────────────────────────────────────────────

function buildChains(
  nodes: GraphNode[],
  _edges: GraphEdge[],
  reviews: EvidenceItem[],
): ChainMeta[] {
  // AGENT-CTX: Single default chain until semantic edges enable multi-chain discovery.
  // All evidence nodes (not gap, not root) belong to chain-0.
  // When buildEdges() returns real edges, rebuild chains by tracing edge connectivity.
  const nodeIds = nodes
    .filter((n) => n.data.nodeType === "evidence")
    .map((n) => n.id);

  const review = reviews.length > 0 ? reviews[0] : null;

  return [
    {
      id:      "chain-0",
      label:   "Evidence Chain 1",
      color:   CHAIN_COLOURS[0],
      nodeIds,
      edgeIds: [],
      review,
    },
  ];
}

// ── Layout ────────────────────────────────────────────────────────────────────

export function assignPositions(nodes: GraphNode[]): void {
  // Group evidence + gap nodes by layer for vertical centering
  const byLayer: Record<number, GraphNode[]> = {};
  for (const node of nodes) {
    if (node.data.nodeType === "root") continue;
    const layer = node.data.layer;
    if (!byLayer[layer]) byLayer[layer] = [];
    byLayer[layer].push(node);
  }

  // Position each layer column
  for (const [layerStr, layerNodes] of Object.entries(byLayer)) {
    const layer = parseInt(layerStr, 10);
    const x = layer * LAYER_SPACING_PX;
    const totalHeight = (layerNodes.length - 1) * NODE_SPACING_PX;
    const startY = -totalHeight / 2;

    layerNodes.forEach((node, i) => {
      node.position = { x, y: startY + i * NODE_SPACING_PX };
    });
  }

  // Position root node: y aligned to layer-0 centroid (or 0 if no layer-0 nodes)
  const rootNode = nodes.find((n) => n.id === "root");
  if (rootNode) {
    const layer0Nodes = byLayer[0] ?? [];
    const centroidY =
      layer0Nodes.length > 0
        ? layer0Nodes.reduce((sum, n) => sum + n.position.y, 0) / layer0Nodes.length
        : 0;
    rootNode.position = { x: ROOT_X, y: centroidY };
  }
}

// ── Gray-out ──────────────────────────────────────────────────────────────────

/**
 * Return a new nodes array with grayedOut set based on reviewYear.
 * Items with publication_year > reviewYear are grayed.
 * Gap and root nodes are never grayed.
 *
 * AGENT-CTX: Returns the same array reference when nothing changes (React
 * optimization — avoids unnecessary re-renders when no nodes are grayed).
 */
export function applyGrayOut(
  nodes: GraphNode[],
  reviewYear: number | null,
): GraphNode[] {
  if (reviewYear === null) {
    // No review year → clear all gray-out
    if (nodes.every((n) => !n.data.grayedOut)) return nodes;
    return nodes.map((n) => ({ ...n, data: { ...n.data, grayedOut: false } }));
  }

  let changed = false;
  const updated = nodes.map((node) => {
    if (node.data.nodeType !== "evidence") return node;
    const year = node.data.evidence?.publication_year ?? null;
    const shouldGray = year !== null && year > reviewYear;
    if (shouldGray === node.data.grayedOut) return node;
    changed = true;
    return { ...node, data: { ...node.data, grayedOut: shouldGray } };
  });

  return changed ? updated : nodes;
}
