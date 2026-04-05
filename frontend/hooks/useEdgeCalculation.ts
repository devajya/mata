"use client";

import { useEffect, useRef, useState } from "react";
import { GraphEdge, GraphNode } from "../lib/graphUtils";
import { getMockScenario } from "../lib/mockData";

export type EdgeCalcStatus = "idle" | "loading" | "ready" | "failed";

interface EdgeCalcResult {
  edges:        GraphEdge[];
  status:       EdgeCalcStatus;
  retryCount:   number;
  failedPayload: unknown;
}

const MAX_RETRIES    = 3;
const RETRY_DELAY_MS = 1500;

/**
 * Async edge calculation hook — state machine: idle → loading → ready | failed.
 *
 * AGENT-CTX: calculateEdges() is the ONLY function that changes when the real
 * edge API is implemented. Everything else (retry logic, status machine,
 * cancellation) stays the same. Replace the mock branch with a real POST to
 * /edges (or an embedding call) when the backend is ready.
 *
 * AGENT-CTX: Retry logic — max 3 attempts, 1500ms backoff between attempts.
 * On final failure: status→"failed", edges→[], failedPayload logged to console.error.
 *
 * AGENT-CTX: Returns [] edges for all real queries (non-mock). The graph renders
 * correctly without edges — nodes are positioned in the layer grid and the
 * absence of connection lines is acceptable for the current milestone.
 */
export function useEdgeCalculation(
  items: unknown[],
  query: string,
  nodes: GraphNode[],
): EdgeCalcResult {
  const [edges,         setEdges]         = useState<GraphEdge[]>([]);
  const [status,        setStatus]        = useState<EdgeCalcStatus>("idle");
  const [retryCount,    setRetryCount]    = useState(0);
  const [failedPayload, setFailedPayload] = useState<unknown>(null);

  // cancelledRef prevents stale state updates after query changes or unmount.
  const cancelledRef = useRef(false);

  useEffect(() => {
    if (items.length === 0) {
      setStatus("idle");
      setEdges([]);
      return;
    }

    cancelledRef.current = false;
    setStatus("loading");
    setRetryCount(0);
    setFailedPayload(null);

    let attempt = 0;

    async function run(): Promise<void> {
      if (cancelledRef.current) return;

      try {
        const result = await calculateEdges(query, nodes);
        if (cancelledRef.current) return;
        setEdges(result);
        setStatus("ready");
      } catch (err) {
        if (cancelledRef.current) return;
        attempt += 1;
        setRetryCount(attempt);

        if (attempt >= MAX_RETRIES) {
          setFailedPayload(err);
          setEdges([]);
          setStatus("failed");
          console.error("[useEdgeCalculation] All retries exhausted:", err);
          return;
        }

        await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
        run();
      }
    }

    run();

    return () => {
      cancelledRef.current = true;
    };
    // AGENT-CTX: query is the dependency — recalculate when the search changes.
    // nodes is not a dep: it's derived from items which changes with query.
  }, [query, items.length]); // eslint-disable-line react-hooks/exhaustive-deps

  return { edges, status, retryCount, failedPayload };
}

/**
 * Calculate edges for the given query and graph nodes.
 *
 * AGENT-CTX: THIS IS THE ONLY FUNCTION TO REPLACE when real edge calculation
 * is implemented. Current behaviour:
 *   - Known dev queries (5 mock scenarios) → return mock edges from mockData.ts
 *   - All other queries → return [] (no edges; graph renders nodes only)
 *
 * Future behaviour (replace this function body):
 *   - POST to /edges with { query, pmids: nodes.map(n=>n.id) }
 *   - OR call embedding service for semantic similarity
 *   - Return GraphEdge[] built from the response
 */
async function calculateEdges(
  query: string,
  nodes: GraphNode[],
): Promise<GraphEdge[]> {
  const mock = getMockScenario(query, nodes);
  if (mock !== null) {
    // Simulate async latency for realistic loading state in dev
    await new Promise((resolve) => setTimeout(resolve, 600));
    return mock;
  }
  // Real query — no edges yet
  return [];
}
