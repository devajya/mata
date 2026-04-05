/**
 * Mock edge scenarios for local development.
 *
 * AGENT-CTX: THIS FILE IS TEMPORARY. It exists only because buildEdges() is a stub
 * and real semantic edge calculation requires a backend endpoint that does not yet
 * exist. These 5 hard-coded scenarios let us develop and test graph UI features
 * (multi-chain, gray-out, edge styling) without a real LLM edge API.
 *
 * AGENT-CTX: Remove this file when the real edge calculation API is implemented.
 * The trigger is: when useEdgeCalculation.ts calls a real endpoint instead of
 * getMockScenario(). At that point mockData.ts has no callers and can be deleted.
 *
 * AGENT-CTX: getMockScenario() returns null for all queries not in the 5 triggers.
 * Production queries (real Ollama/Groq results) get no mock edges — the graph
 * simply renders nodes without connection lines, which is visually acceptable.
 */

import { GraphEdge, GraphNode } from "./graphUtils";
import { GraphEdgeData, RelationshipType } from "../types";

// ── Relationship styles (also used by RelationshipLegend) ─────────────────────

export const RELATIONSHIP_STYLES: Record<
  RelationshipType,
  { color: string; dash: string; label: string }
> = {
  supports:       { color: "#2d6a4f", dash: "none",    label: "Supports"       },
  extends:        { color: "#1a6faf", dash: "6,3",     label: "Extends"        },
  replicates:     { color: "#6a3d9a", dash: "2,2",     label: "Replicates"     },
  contextualizes: { color: "#888888", dash: "8,4,2,4", label: "Contextualizes" },
};

// ── Mock edge builder ─────────────────────────────────────────────────────────

function makeEdge(
  sourcePmid: string,
  targetPmid: string,
  relationshipType: RelationshipType,
  chainIds: string[],
): GraphEdge {
  return {
    id:     `edge-${sourcePmid}-${targetPmid}`,
    source: `evidence-${sourcePmid}`,
    target: `evidence-${targetPmid}`,
    data:   { chainIds, relationshipType } satisfies GraphEdgeData,
  };
}

// ── 5 named mock scenarios ────────────────────────────────────────────────────

const MOCK_SCENARIOS: Record<string, (_nodes: GraphNode[]) => GraphEdge[]> = {
  // Scenario 1: Full 4-layer chain, review 2021
  "KRAS G12C": (_nodes) => [
    makeEdge("11111111", "22222222", "supports",       ["chain-0"]),
    makeEdge("22222222", "33333333", "extends",        ["chain-0"]),
    makeEdge("33333333", "44444444", "contextualizes", ["chain-0"]),
  ],

  // Scenario 2: Two overlapping chains, shared animal model node
  "EGFR erlotinib": (_nodes) => [
    makeEdge("55555551", "55555552", "supports",   ["chain-0"]),
    makeEdge("55555552", "55555553", "extends",    ["chain-0", "chain-1"]),
    makeEdge("55555553", "55555554", "replicates", ["chain-1"]),
  ],

  // Scenario 3: In vitro only, 3 gap nodes, review with null year
  "p53 tumor suppressor": (_nodes) => [],

  // Scenario 4: Within-layer replication edge, review 2018
  "BRCA1 hereditary cancer": (_nodes) => [
    makeEdge("66666661", "66666662", "replicates",     ["chain-0"]),
    makeEdge("66666661", "66666663", "contextualizes", ["chain-0"]),
  ],

  // Scenario 5: All 4 relationship types, no review
  "mTOR rapamycin": (_nodes) => [
    makeEdge("77777771", "77777772", "supports",       ["chain-0"]),
    makeEdge("77777772", "77777773", "extends",        ["chain-0"]),
    makeEdge("77777773", "77777774", "replicates",     ["chain-0"]),
    makeEdge("77777774", "77777775", "contextualizes", ["chain-0"]),
  ],
};

/**
 * Return mock edges for known development queries, null for all real queries.
 *
 * AGENT-CTX: null return means "no mock available" — caller should use [] edges.
 * This is distinct from "empty edges" ([] return from a scenario like p53).
 */
export function getMockScenario(
  query: string,
  nodes: GraphNode[],
): GraphEdge[] | null {
  const fn = MOCK_SCENARIOS[query.trim()];
  return fn ? fn(nodes) : null;
}
