"use client";

import { useCallback, useEffect, useState } from "react";
import { JobListItem } from "../types";

// AGENT-CTX: API_URL duplicated from page.tsx — see useJobPoller.ts AGENT-CTX.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Fetches and caches the job history list from GET /jobs.
 *
 * AGENT-CTX: This hook abstracts the history data source so components never
 * call GET /jobs directly. When auth is added:
 *   1. The backend's get_job_filter() dep is overridden to filter by user_id.
 *   2. This hook adds an Authorization header to the fetch.
 *   3. Components require zero changes.
 *
 * AGENT-CTX: refresh() is exposed so callers can trigger a re-fetch after
 * submitting a new job or after a job transitions to complete/failed.
 * The hook does NOT auto-refresh on an interval — history is only stale when
 * the user submits a new job or selects a running job that completes.
 *
 * AGENT-CTX: Errors are swallowed silently. A failed GET /jobs is not fatal —
 * the sidebar shows an empty list and the user can still submit new searches.
 */
export function useJobHistory(): {
  jobs: JobListItem[];
  refresh: () => void;
  isLoading: boolean;
} {
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const refresh = useCallback(() => {
    setIsLoading(true);
    fetch(`${API_URL}/jobs`)
      .then((res) => (res.ok ? res.json() : []))
      .then((data: JobListItem[]) => setJobs(data))
      .catch(() => {})
      .finally(() => setIsLoading(false));
  }, []);

  // AGENT-CTX: Fetch once on mount to populate the sidebar immediately.
  // useCallback ensures refresh is stable across renders so the dependency
  // array [refresh] does not trigger infinite re-runs.
  useEffect(() => {
    refresh();
  }, [refresh]);

  return { jobs, refresh, isLoading };
}
