/**
 * Graph assembly utilities for the Evidence Chain view.
 *
 * AGENT-CTX §1 — Real edge computation (Chain Links milestone):
 * buildEdges() now maps backend EdgeResult objects to GraphEdge objects.
 * The old stub returning [] has been replaced. Edges arrive pre-computed
 * from the background worker (compute_all_edges in backend/edges.py) and
 * are passed in via buildGraphData(items, edgeResults, query).
 *
 * AGENT-CTX §2 — No @xyflow/react imports:
 * This file and node components must NOT import from @xyflow/react.
 * Jest-testable without canvas mocks. The cast to React Flow's Node<T>/Edge<T>
 * types happens ONLY in EvidenceGraph.tsx at the ReactFlow boundary.
 *
 * AGENT-CTX §3 — Multi-chain via BFS:
 * buildChains() discovers connected components in the evidence graph using BFS.
 * Each connected component = one ChainMeta. Isolated nodes each get their own
 * chain. Chains are sorted: most nodes first, then highest max-layer first.
 * The root node belongs to ALL chains so it stays visible regardless of which
 * chain is active (exclusive-visibility toggle in EvidenceGraph.tsx).
 */

import { ChainMeta, EdgeResult, EdgeType, EvidenceItem, GraphEdgeData, GraphNodeData } from "../types";

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

// AGENT-CTX: EDGE_TYPE_STYLES is the single source of truth for edge colours/dash
// patterns. Exported so RelationshipLegend.tsx can render the legend from the same
// data without duplicating it. Applied to React Flow edges in buildEdges() below.
// markerEnd uses the plain-object form { type: "arrowclosed" } — React Flow accepts
// string literals for MarkerType so no @xyflow/react import is needed here.
export const EDGE_TYPE_STYLES: Record<EdgeType, { color: string; dash: string; label: string }> = {
  supports:                   { color: "#2d6a4f", dash: "none",      label: "Supports" },
  contradicts:                { color: "#c0392b", dash: "none",      label: "Contradicts" },
  contradicts_methodological: { color: "#e67e22", dash: "4,2",       label: "Contradicts (method)" },
  translates:                 { color: "#1a6faf", dash: "none",      label: "Translates" },
  fails_to_translate:         { color: "#8e44ad", dash: "8,3",       label: "Fails to Translate" },
  mechanistically_extends:    { color: "#16a085", dash: "6,3",       label: "Extends Mechanism" },
  qualifies:                  { color: "#d4ac0d", dash: "4,2",       label: "Qualifies" },
  combination_context:        { color: "#2980b9", dash: "2,2",       label: "Combination" },
  resistance_link:            { color: "#c0392b", dash: "8,4,2,4",  label: "Resistance" },
  replicates:                 { color: "#6a3d9a", dash: "2,2",       label: "Replicates" },
};

// AGENT-CTX: CHAIN_COLOURS wraps at 5 — intentional. More than 5 chains is rare
// in practice (10 papers max per query → few components). Wrapping avoids
// maintaining a longer palette that is harder to distinguish perceptually.
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
  style:     { stroke: string; strokeDasharray?: string; strokeWidth: number };
  markerEnd: { type: string; color: string; width: number; height: number };
}

// ── Entry point ───────────────────────────────────────────────────────────────

// AGENT-CTX: edgeResults is the second param (not third) to keep items/edges
// together — they are co-produced by the same worker job. query is last because
// it is only used for the root node label and is semantically separate.
export function buildGraphData(
  items: EvidenceItem[],
  edgeResults: EdgeResult[],
  query: string,
): { nodes: GraphNode[]; edges: GraphEdge[]; chains: ChainMeta[] } {
  const reviews    = items.filter((i) => i.layer === -1);
  const chainItems = items.filter((i) => i.layer >= 0);

  const nodes  = buildNodes(chainItems, query);
  const edges  = buildEdges(nodes, edgeResults);
  const chains = buildChains(nodes, edges, reviews);
  assignPositions(nodes);

  return { nodes, edges, chains };
}

// ── Node builders ─────────────────────────────────────────────────────────────

function buildNodes(chainItems: EvidenceItem[], query: string): GraphNode[] {
  const nodes: GraphNode[] = [];

  // Root node — the search query anchor
  // AGENT-CTX: chainIds initialised to [] here; buildChains() fills in all chain
  // IDs so the root remains visible for every chain (exclusive toggle still works).
  nodes.push({
    id:       "root",
    type:     "root",
    position: { x: ROOT_X, y: 0 },
    data: {
      nodeType:  "root",
      layer:     -2,
      evidence:  null,
      layerName: query,
      chainIds:  [],   // populated by buildChains
      grayedOut: false,
    },
  });

  // Evidence nodes — one per chain item
  // AGENT-CTX: chainIds initialised to [] here; buildChains() assigns each node
  // to exactly one chain based on BFS connectivity.
  for (const item of chainItems) {
    nodes.push({
      id:       `evidence-${item.pmid}`,
      type:     "evidence",
      position: { x: 0, y: 0 },
      data: {
        nodeType:  "evidence",
        layer:     item.layer,
        evidence:  item,
        layerName: LAYER_NAMES[item.layer] ?? "Unknown",
        chainIds:  [],   // populated by buildChains
        grayedOut: false,
      },
    });
  }

  // Gap nodes — one per layer that has no evidence
  // AGENT-CTX: Gap nodes always have chainIds: [] — they are visual placeholders
  // and are never owned by a chain. EvidenceGraph.tsx renders them regardless
  // of which chain is active.
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

// ── Edge builder ──────────────────────────────────────────────────────────────

// AGENT-CTX: Maps backend EdgeResult objects to GraphEdge objects.
// Filters edges where either endpoint node is absent from the graph —
// defensive guard against cross-job PMIDs that shouldn't appear but might
// if the backend result set changes between job creation and rendering.
// chainIds is left [] here; buildChains() back-fills after BFS discovery.
//
// AGENT-CTX: Visual source/target may be swapped from semantic source/target.
// EvidenceNode has its React Flow source handle on the RIGHT and target handle
// on the LEFT — correct for a left-to-right layout. If the semantic source has
// a higher layer (further right) than the semantic target, the edge would route
// backwards (right-of-higher-layer → left-of-lower-layer), creating an ugly
// reverse U-curve. Swapping the visual endpoints makes it route left→right.
// The original semantic direction is preserved in data.edge_type and data.rationale.
function buildEdges(nodes: GraphNode[], edgeResults: EdgeResult[]): GraphEdge[] {
  const nodeIdSet  = new Set(nodes.map((n) => n.id));
  const layerById  = new Map(nodes.map((n) => [n.id, n.data.layer]));
  const edges: GraphEdge[] = [];

  for (const er of edgeResults) {
    const semanticSource = `evidence-${er.source_pmid}`;
    const semanticTarget = `evidence-${er.target_pmid}`;

    if (!nodeIdSet.has(semanticSource) || !nodeIdSet.has(semanticTarget)) continue;

    const sourceLayer = layerById.get(semanticSource) ?? 0;
    const targetLayer = layerById.get(semanticTarget) ?? 0;

    // Swap visually if edge goes right→left so React Flow routes it cleanly.
    const [source, target] =
      sourceLayer > targetLayer
        ? [semanticTarget, semanticSource]
        : [semanticSource, semanticTarget];

    const edgeStyle = EDGE_TYPE_STYLES[er.edge_type] ?? EDGE_TYPE_STYLES.supports;

    edges.push({
      id:     `edge-${er.source_pmid}-${er.target_pmid}`,
      source,
      target,
      style: {
        stroke:           edgeStyle.color,
        strokeDasharray:  edgeStyle.dash === "none" ? undefined : edgeStyle.dash,
        strokeWidth:      2,
      },
      // AGENT-CTX: plain-object markerEnd — React Flow accepts "arrowclosed" as a
      // string literal for MarkerType without needing to import the enum.
      markerEnd: { type: "arrowclosed", color: edgeStyle.color, width: 12, height: 12 },
      data: {
        chainIds:   [],          // populated by buildChains
        edge_type:  er.edge_type,
        confidence: er.confidence,
        rationale:  er.rationale,
      },
    });
  }

  return edges;
}

// ── Chain builder (BFS connected components) ──────────────────────────────────

// AGENT-CTX: BFS over evidence nodes only. Gap and root nodes are excluded from
// the connectivity graph: gap nodes are placeholders, root is always visible.
// Each connected component (including isolated single nodes) becomes one ChainMeta.
// After chain discovery, chainIds are back-filled on both nodes and edges so that
// EvidenceGraph.tsx can filter by chain without re-running graph algorithms.
function buildChains(
  nodes: GraphNode[],
  graphEdges: GraphEdge[],
  reviews: EvidenceItem[],
): ChainMeta[] {
  const evidenceNodes = nodes.filter((n) => n.data.nodeType === "evidence");
  if (evidenceNodes.length === 0) return [];

  // Build undirected adjacency map over evidence nodes
  const adjacency = new Map<string, Set<string>>();
  for (const node of evidenceNodes) {
    adjacency.set(node.id, new Set());
  }
  for (const edge of graphEdges) {
    // AGENT-CTX: Both directions added so BFS works regardless of edge direction
    // (edge semantic direction "A→B" is stored in GraphEdgeData, not the graph topology).
    adjacency.get(edge.source)?.add(edge.target);
    adjacency.get(edge.target)?.add(edge.source);
  }

  // BFS — discover connected components
  const visited = new Set<string>();
  const components: string[][] = [];

  for (const node of evidenceNodes) {
    if (visited.has(node.id)) continue;

    const component: string[] = [];
    const queue: string[] = [node.id];
    visited.add(node.id);

    while (queue.length > 0) {
      const current = queue.shift()!;
      component.push(current);
      for (const neighbor of adjacency.get(current) ?? []) {
        if (!visited.has(neighbor)) {
          visited.add(neighbor);
          queue.push(neighbor);
        }
      }
    }

    components.push(component);
  }

  // AGENT-CTX: Sort chains descending by size, then by max layer within component.
  // This puts the richest (most-connected, highest-evidence) chain first so it
  // becomes chain-0 — the one shown by default on load.
  const nodeLayerMap = new Map(nodes.map((n) => [n.id, n.data.layer]));
  components.sort((a, b) => {
    if (b.length !== a.length) return b.length - a.length;
    const maxA = Math.max(...a.map((id) => nodeLayerMap.get(id) ?? 0));
    const maxB = Math.max(...b.map((id) => nodeLayerMap.get(id) ?? 0));
    return maxB - maxA;
  });

  // Build ChainMeta objects
  const chains: ChainMeta[] = components.map((nodeIds, i) => ({
    id:      `chain-${i}`,
    label:   `Evidence Chain ${i + 1}`,
    color:   CHAIN_COLOURS[i % CHAIN_COLOURS.length],
    nodeIds,
    edgeIds: [],            // populated in back-fill pass below
    // AGENT-CTX: Review is attached to chain-0 only. Reviews (layer -1) are not
    // part of the BFS graph so they have no natural chain affinity. Attaching to
    // the first (richest) chain ensures the review is visible on initial load.
    review:  i === 0 && reviews.length > 0 ? reviews[0] : null,
  }));

  // Back-fill chainIds on evidence nodes
  const chainIdByNodeId = new Map<string, string>();
  for (const chain of chains) {
    for (const nodeId of chain.nodeIds) {
      chainIdByNodeId.set(nodeId, chain.id);
    }
  }
  for (const node of nodes) {
    if (node.data.nodeType === "evidence") {
      const cid = chainIdByNodeId.get(node.id);
      if (cid) node.data.chainIds = [cid];
    } else if (node.data.nodeType === "root") {
      // AGENT-CTX: Root node assigned all chain IDs so it is visible regardless
      // of which chain is active in EvidenceGraph.tsx's exclusive-toggle logic.
      node.data.chainIds = chains.map((c) => c.id);
    }
    // gap nodes keep chainIds: []
  }

  // Back-fill edgeIds on chains and chainIds on edges
  for (const chain of chains) {
    const chainNodeSet = new Set(chain.nodeIds);
    const edgeIds: string[] = [];
    for (const edge of graphEdges) {
      if (chainNodeSet.has(edge.source) && chainNodeSet.has(edge.target)) {
        edgeIds.push(edge.id);
        edge.data.chainIds = [chain.id];
      }
    }
    chain.edgeIds = edgeIds;
  }

  return chains;
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
