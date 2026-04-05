/**
 * Tests for frontend/lib/graphUtils.ts — pure graph assembly functions.
 *
 * AGENT-CTX: No @xyflow/react imports anywhere in this file. graphUtils.ts is
 * kept free of @xyflow/react to make exactly these tests possible: fast, pure
 * function tests with no canvas or browser mocks needed.
 *
 * AGENT-CTX: buildGraphData signature changed in Chain Links milestone:
 * OLD: buildGraphData(items, query)
 * NEW: buildGraphData(items, edgeResults, query)
 * All calls in this file pass [] for edgeResults unless testing edge/chain logic.
 */

import { EdgeResult, EvidenceItem } from "../types";
import {
  applyGrayOut,
  assignPositions,
  buildGraphData,
  CHAIN_LAYER_ORDER,
} from "../lib/graphUtils";

// ── Fixtures ──────────────────────────────────────────────────────────────────

function makeItem(overrides: Partial<EvidenceItem> = {}): EvidenceItem {
  return {
    pmid:             "11111111",
    title:            "Test Study",
    abstract:         "An abstract.",
    evidence_type:    "clinical trial",
    effect_direction: "supports",
    model_organism:   "not reported",
    sample_size:      "not reported",
    confidence_tier:  "high",
    layer:             3,
    publication_year:  2020,
    ...overrides,
  };
}

// AGENT-CTX: makeEdgeResult builds a minimal valid EdgeResult for tests.
// All fields required by EdgeResult interface are populated with sensible defaults.
// confidence_factors defaults to [] (matching backend Pydantic default).
function makeEdgeResult(overrides: Partial<EdgeResult> = {}): EdgeResult {
  return {
    source_pmid:        "11111111",
    target_pmid:        "22222222",
    edge_type:          "translates",
    direction:          "A→B",
    confidence:         0.75,
    rationale:          "In vitro finding translates to clinical outcome.",
    confidence_factors: ["+0.20 same intervention"],
    flag:               null,
    ...overrides,
  };
}

// ── buildGraphData ────────────────────────────────────────────────────────────

test("root node is always present", () => {
  const { nodes } = buildGraphData([makeItem()], [], "KRAS G12C");
  expect(nodes.find((n) => n.id === "root")).toBeTruthy();
});

test("evidence nodes created for each non-review item", () => {
  const items = [
    makeItem({ pmid: "AAA", layer: 0 }),
    makeItem({ pmid: "BBB", layer: 3 }),
  ];
  const { nodes } = buildGraphData(items, [], "test");
  expect(nodes.find((n) => n.id === "evidence-AAA")).toBeTruthy();
  expect(nodes.find((n) => n.id === "evidence-BBB")).toBeTruthy();
});

test("gap nodes created for missing layers", () => {
  // Only layer 3 (clinical trial) present → gaps for layers 0, 1, 2
  const { nodes } = buildGraphData([makeItem({ layer: 3 })], [], "test");
  const gapIds = nodes.filter((n) => n.type === "gap").map((n) => n.id);
  expect(gapIds).toContain("gap-0");
  expect(gapIds).toContain("gap-1");
  expect(gapIds).toContain("gap-2");
  expect(gapIds).not.toContain("gap-3"); // layer 3 is present
});

test("review items (layer -1) are excluded from graph nodes", () => {
  const items = [
    makeItem({ pmid: "REV", layer: -1, evidence_type: "review" }),
    makeItem({ pmid: "TRIAL", layer: 3 }),
  ];
  const { nodes } = buildGraphData(items, [], "test");
  expect(nodes.find((n) => n.id === "evidence-REV")).toBeFalsy();
  expect(nodes.find((n) => n.id === "evidence-TRIAL")).toBeTruthy();
});

test("review is attached to chain as metadata", () => {
  const review = makeItem({ pmid: "REV", layer: -1, evidence_type: "review", publication_year: 2019 });
  const { chains } = buildGraphData([review, makeItem({ layer: 0 })], [], "test");
  expect(chains[0].review?.pmid).toBe("REV");
});

// ── Edge mapping ──────────────────────────────────────────────────────────────

test("buildEdges maps EdgeResult to GraphEdge with correct fields", () => {
  // AGENT-CTX: Replaces the old "edges are empty stub" test — edges are now real.
  const items = [
    makeItem({ pmid: "AAA", layer: 0 }),
    makeItem({ pmid: "BBB", layer: 3 }),
  ];
  const er = makeEdgeResult({ source_pmid: "AAA", target_pmid: "BBB" });
  const { edges } = buildGraphData(items, [er], "test");
  expect(edges).toHaveLength(1);
  expect(edges[0].source).toBe("evidence-AAA");
  expect(edges[0].target).toBe("evidence-BBB");
  expect(edges[0].data.edge_type).toBe("translates");
  expect(edges[0].data.confidence).toBe(0.75);
});

test("buildEdges filters out edges where a node is missing from graph", () => {
  // AGENT-CTX: Defensive guard — source_pmid "ZZZ" is not in items.
  const items = [makeItem({ pmid: "AAA", layer: 0 })];
  const er = makeEdgeResult({ source_pmid: "ZZZ", target_pmid: "AAA" });
  const { edges } = buildGraphData(items, [er], "test");
  expect(edges).toHaveLength(0);
});

test("empty edgeResults produces empty edges list", () => {
  const { edges } = buildGraphData([makeItem()], [], "test");
  expect(edges).toEqual([]);
});

// ── Multi-chain (BFS connected components) ────────────────────────────────────

test("isolated nodes each get their own chain", () => {
  // AGENT-CTX: Two nodes with no edges between them → two separate components.
  // Each becomes its own ChainMeta. This is intentional: each isolated paper
  // forms its own evidence chain rather than being merged into a single blob.
  const items = [
    makeItem({ pmid: "AAA", layer: 0 }),
    makeItem({ pmid: "BBB", layer: 3 }),
  ];
  const { chains } = buildGraphData(items, [], "test");
  expect(chains).toHaveLength(2);
});

test("connected nodes form a single chain", () => {
  const items = [
    makeItem({ pmid: "AAA", layer: 0 }),
    makeItem({ pmid: "BBB", layer: 3 }),
  ];
  const er = makeEdgeResult({ source_pmid: "AAA", target_pmid: "BBB" });
  const { chains } = buildGraphData(items, [er], "test");
  expect(chains).toHaveLength(1);
  expect(chains[0].nodeIds).toContain("evidence-AAA");
  expect(chains[0].nodeIds).toContain("evidence-BBB");
});

test("two disconnected components produce two chains", () => {
  // AGENT-CTX: AAA-BBB are connected; CCC is isolated → two chains.
  const items = [
    makeItem({ pmid: "AAA", layer: 0 }),
    makeItem({ pmid: "BBB", layer: 1 }),
    makeItem({ pmid: "CCC", layer: 3 }),
  ];
  const er = makeEdgeResult({ source_pmid: "AAA", target_pmid: "BBB" });
  const { chains } = buildGraphData(items, [er], "test");
  expect(chains).toHaveLength(2);
  // Component with 2 nodes comes first (sorted by size)
  expect(chains[0].nodeIds).toHaveLength(2);
  expect(chains[1].nodeIds).toHaveLength(1);
});

test("chain back-fills chainIds on edges", () => {
  const items = [
    makeItem({ pmid: "AAA", layer: 0 }),
    makeItem({ pmid: "BBB", layer: 3 }),
  ];
  const er = makeEdgeResult({ source_pmid: "AAA", target_pmid: "BBB" });
  const { edges, chains } = buildGraphData(items, [er], "test");
  expect(edges[0].data.chainIds).toContain(chains[0].id);
});

test("chain back-fills chainIds on nodes", () => {
  const items = [
    makeItem({ pmid: "AAA", layer: 0 }),
    makeItem({ pmid: "BBB", layer: 3 }),
  ];
  const er = makeEdgeResult({ source_pmid: "AAA", target_pmid: "BBB" });
  const { nodes, chains } = buildGraphData(items, [er], "test");
  const nodeA = nodes.find((n) => n.id === "evidence-AAA")!;
  expect(nodeA.data.chainIds).toContain(chains[0].id);
});

test("root node belongs to all chains", () => {
  // AGENT-CTX: Root is always visible regardless of which chain is active.
  // It must appear in every chain's visibility set.
  const items = [
    makeItem({ pmid: "AAA", layer: 0 }),
    makeItem({ pmid: "BBB", layer: 3 }),
  ];
  const { nodes, chains } = buildGraphData(items, [], "test");
  const root = nodes.find((n) => n.id === "root")!;
  for (const chain of chains) {
    expect(root.data.chainIds).toContain(chain.id);
  }
});

// ── assignPositions ───────────────────────────────────────────────────────────

test("nodes in the same layer get different y positions", () => {
  const items = [
    makeItem({ pmid: "A", layer: 0 }),
    makeItem({ pmid: "B", layer: 0 }),
  ];
  const { nodes } = buildGraphData(items, [], "test");
  assignPositions(nodes);
  const nodeA = nodes.find((n) => n.id === "evidence-A")!;
  const nodeB = nodes.find((n) => n.id === "evidence-B")!;
  expect(nodeA.position.y).not.toBe(nodeB.position.y);
});

test("nodes in different layers get different x positions", () => {
  const items = [
    makeItem({ pmid: "A", layer: 0 }),
    makeItem({ pmid: "B", layer: 3 }),
  ];
  const { nodes } = buildGraphData(items, [], "test");
  const nodeA = nodes.find((n) => n.id === "evidence-A")!;
  const nodeB = nodes.find((n) => n.id === "evidence-B")!;
  expect(nodeA.position.x).not.toBe(nodeB.position.x);
});

// ── applyGrayOut ──────────────────────────────────────────────────────────────

test("applyGrayOut grays nodes published after reviewYear", () => {
  const { nodes } = buildGraphData([
    makeItem({ pmid: "A", layer: 0, publication_year: 2020 }),
    makeItem({ pmid: "B", layer: 1, publication_year: 2022 }),
  ], [], "test");

  const updated = applyGrayOut(nodes, 2021);
  const nodeA = updated.find((n) => n.id === "evidence-A")!;
  const nodeB = updated.find((n) => n.id === "evidence-B")!;
  expect(nodeA.data.grayedOut).toBe(false); // 2020 ≤ 2021
  expect(nodeB.data.grayedOut).toBe(true);  // 2022 > 2021
});

test("applyGrayOut with null reviewYear clears all gray-out", () => {
  const { nodes } = buildGraphData([makeItem({ pmid: "A", layer: 0, publication_year: 2020 })], [], "test");
  // First gray it
  const grayed = applyGrayOut(nodes, 2019);
  expect(grayed.find((n) => n.id === "evidence-A")!.data.grayedOut).toBe(true);
  // Then clear
  const cleared = applyGrayOut(grayed, null);
  expect(cleared.find((n) => n.id === "evidence-A")!.data.grayedOut).toBe(false);
});

test("applyGrayOut never grays gap or root nodes", () => {
  const { nodes } = buildGraphData([makeItem({ layer: 3, publication_year: 1990 })], [], "test");
  const updated = applyGrayOut(nodes, 2000);
  const gapNode = nodes.find((n) => n.type === "gap");
  if (gapNode) {
    const result = applyGrayOut([gapNode], 2030);
    expect(result[0].data.grayedOut).toBe(false);
  }
  const rootNode = nodes.find((n) => n.id === "root");
  if (rootNode) {
    const result = applyGrayOut([rootNode], 2030);
    expect(result[0].data.grayedOut).toBe(false);
  }
});
