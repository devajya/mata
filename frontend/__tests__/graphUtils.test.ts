/**
 * Tests for frontend/lib/graphUtils.ts — pure graph assembly functions.
 *
 * AGENT-CTX: No @xyflow/react imports anywhere in this file. graphUtils.ts is
 * kept free of @xyflow/react to make exactly these tests possible: fast, pure
 * function tests with no canvas or browser mocks needed.
 */

import { EvidenceItem } from "../types";
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

// ── buildGraphData ────────────────────────────────────────────────────────────

test("root node is always present", () => {
  const { nodes } = buildGraphData([makeItem()], "KRAS G12C");
  expect(nodes.find((n) => n.id === "root")).toBeTruthy();
});

test("evidence nodes created for each non-review item", () => {
  const items = [
    makeItem({ pmid: "AAA", layer: 0 }),
    makeItem({ pmid: "BBB", layer: 3 }),
  ];
  const { nodes } = buildGraphData(items, "test");
  expect(nodes.find((n) => n.id === "evidence-AAA")).toBeTruthy();
  expect(nodes.find((n) => n.id === "evidence-BBB")).toBeTruthy();
});

test("gap nodes created for missing layers", () => {
  // Only layer 3 (clinical trial) present → gaps for layers 0, 1, 2
  const { nodes } = buildGraphData([makeItem({ layer: 3 })], "test");
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
  const { nodes } = buildGraphData(items, "test");
  expect(nodes.find((n) => n.id === "evidence-REV")).toBeFalsy();
  expect(nodes.find((n) => n.id === "evidence-TRIAL")).toBeTruthy();
});

test("review is attached to chain as metadata", () => {
  const review = makeItem({ pmid: "REV", layer: -1, evidence_type: "review", publication_year: 2019 });
  const { chains } = buildGraphData([review, makeItem({ layer: 0 })], "test");
  expect(chains[0].review?.pmid).toBe("REV");
});

test("edges are empty stub", () => {
  const { edges } = buildGraphData([makeItem()], "test");
  expect(edges).toEqual([]);
});

// ── assignPositions ───────────────────────────────────────────────────────────

test("nodes in the same layer get different y positions", () => {
  const items = [
    makeItem({ pmid: "A", layer: 0 }),
    makeItem({ pmid: "B", layer: 0 }),
  ];
  const { nodes } = buildGraphData(items, "test");
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
  const { nodes } = buildGraphData(items, "test");
  const nodeA = nodes.find((n) => n.id === "evidence-A")!;
  const nodeB = nodes.find((n) => n.id === "evidence-B")!;
  expect(nodeA.position.x).not.toBe(nodeB.position.x);
});

// ── applyGrayOut ──────────────────────────────────────────────────────────────

test("applyGrayOut grays nodes published after reviewYear", () => {
  const { nodes } = buildGraphData([
    makeItem({ pmid: "A", layer: 0, publication_year: 2020 }),
    makeItem({ pmid: "B", layer: 1, publication_year: 2022 }),
  ], "test");

  const updated = applyGrayOut(nodes, 2021);
  const nodeA = updated.find((n) => n.id === "evidence-A")!;
  const nodeB = updated.find((n) => n.id === "evidence-B")!;
  expect(nodeA.data.grayedOut).toBe(false); // 2020 ≤ 2021
  expect(nodeB.data.grayedOut).toBe(true);  // 2022 > 2021
});

test("applyGrayOut with null reviewYear clears all gray-out", () => {
  const { nodes } = buildGraphData([makeItem({ pmid: "A", layer: 0, publication_year: 2020 })], "test");
  // First gray it
  const grayed = applyGrayOut(nodes, 2019);
  expect(grayed.find((n) => n.id === "evidence-A")!.data.grayedOut).toBe(true);
  // Then clear
  const cleared = applyGrayOut(grayed, null);
  expect(cleared.find((n) => n.id === "evidence-A")!.data.grayedOut).toBe(false);
});

test("applyGrayOut never grays gap or root nodes", () => {
  const { nodes } = buildGraphData([makeItem({ layer: 3, publication_year: 1990 })], "test");
  const updated = applyGrayOut(nodes, 2000); // year 1990 > 2000 = false, so nothing grayed anyway
  // But explicitly test gap nodes with very old year
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
