"use client";

import { useEffect, useState } from "react";
import { CHAIN_LAYER_ORDER, LAYER_NAMES } from "../lib/graphUtils";

// API_URL duplicated from page.tsx — see useJobPoller.ts AGENT-CTX.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface AppMeta {
  layerNames: Record<number, string>;
  chainLayerOrder: number[];
}

const DEFAULT_META: AppMeta = {
  layerNames: LAYER_NAMES,
  chainLayerOrder: CHAIN_LAYER_ORDER,
};

/**
 * Fetches GET /meta once on mount and returns the authoritative layer
 * definitions from the backend. Falls back to the hardcoded defaults in
 * graphUtils.ts if the fetch fails, so the app always has valid values.
 */
export function useAppMeta(): AppMeta {
  const [meta, setMeta] = useState<AppMeta>(DEFAULT_META);

  useEffect(() => {
    fetch(`${API_URL}/meta`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!data) return;
        // JSON keys are always strings — convert back to numbers.
        const layerNames: Record<number, string> = {};
        for (const [k, v] of Object.entries(data.layer_names ?? {})) {
          layerNames[parseInt(k, 10)] = v as string;
        }
        setMeta({
          layerNames,
          chainLayerOrder: (data.chain_layer_order as number[]) ?? DEFAULT_META.chainLayerOrder,
        });
      })
      .catch(() => {
        // Silently keep defaults — the app works without /meta.
      });
  }, []);

  return meta;
}
