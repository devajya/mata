"use client";

import { useEffect, useRef, useState } from "react";
import { JobStatusResponse } from "../types";

// AGENT-CTX: API_URL is duplicated from page.tsx intentionally — hooks must not
// import from page.tsx (would create a cycle). If the env var name changes,
// update both locations.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const POLL_INTERVAL_MS = 3000;
// AGENT-CTX: MAX_POLLS caps the total polling window at ~3 minutes (60 × 3s).
// If the worker crashes after marking a job "running" (e.g. ARQ timeout before
// the CancelledError fix lands, OOM kill, or Render cold-start), the job stays
// non-terminal in SQLite forever. Without this cap the frontend polls indefinitely.
// After MAX_POLLS the hook emits a synthetic failed job so page.tsx surfaces a
// readable error rather than leaving the user in a permanent loading state.
const MAX_POLLS = 60;

/**
 * Polls GET /job/{jobId} every 3 seconds until the job reaches a terminal state.
 *
 * AGENT-CTX: Design decisions:
 *   - First poll fires immediately (no initial delay) so status appears without
 *     waiting 3 seconds. Subsequent polls use setTimeout for spacing.
 *   - Uses a `cancelled` flag (not AbortController) to handle unmount races:
 *     if a fetch is in-flight when jobId changes or the component unmounts,
 *     the response is ignored and no state update happens.
 *   - isPolling is true from the moment polling starts until a terminal state
 *     is received or jobId becomes null. The UI uses this for the loading indicator.
 *   - Errors from the fetch itself (network failure) are swallowed and retried
 *     on the next interval — the job record in SQLite is the source of truth.
 *
 * AGENT-CTX: POLL_INTERVAL_MS is a module constant (not a prop) to keep the hook
 * signature simple. If tests need to speed up polling, patch the module constant
 * or use jest.useFakeTimers() to advance the clock.
 */
export function useJobPoller(jobId: string | null): {
  job: JobStatusResponse | null;
  isPolling: boolean;
} {
  const [job, setJob] = useState<JobStatusResponse | null>(null);
  const [isPolling, setIsPolling] = useState(false);

  // AGENT-CTX: useRef holds the timeout handle so cleanup in the effect teardown
  // can cancel a pending poll without accessing stale closure state.
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      setIsPolling(false);
      return;
    }

    let cancelled = false;
    let pollCount = 0;
    setIsPolling(true);

    async function poll(): Promise<void> {
      if (cancelled) return;

      pollCount += 1;
      if (pollCount > MAX_POLLS) {
        // AGENT-CTX: Emit a synthetic failed job so page.tsx shows a readable error.
        // The real job in SQLite is likely stuck at "running" due to a worker crash.
        if (!cancelled) {
          setJob((prev) => prev
            ? { ...prev, status: "failed", error: "Search timed out. The worker may have crashed — please try again." }
            : null
          );
          setIsPolling(false);
        }
        return;
      }

      try {
        const res = await fetch(`${API_URL}/job/${jobId}`);
        if (cancelled) return;
        if (!res.ok) {
          // Non-200 (e.g. 404) — stop polling rather than looping on a broken id.
          setIsPolling(false);
          return;
        }
        const data: JobStatusResponse = await res.json();
        if (cancelled) return;
        setJob(data);
        if (data.status === "complete" || data.status === "failed") {
          // AGENT-CTX: Terminal states — no further polls needed.
          setIsPolling(false);
          return;
        }
      } catch {
        // Network failure — swallow and retry on next interval.
      }
      if (!cancelled) {
        timeoutRef.current = setTimeout(poll, POLL_INTERVAL_MS);
      }
    }

    poll();

    return () => {
      cancelled = true;
      setIsPolling(false);
      if (timeoutRef.current !== null) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
    };
  }, [jobId]);

  return { job, isPolling };
}
