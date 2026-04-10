"use client";

// AGENT-CTX: "use client" required — component uses useState, hooks, and event handlers.
// Next.js App Router defaults to Server Components; this directive opts in to client
// rendering. Do NOT remove — the component will break silently on the server.

import { useEffect, useState } from "react";
import { EvidenceGraph } from "../components/EvidenceGraph";
import { Sidebar } from "../components/Sidebar";
import { useJobHistory } from "../hooks/useJobHistory";
import { useJobPoller } from "../hooks/useJobPoller";
import { EdgeResult, EvidenceItem, JobListItem } from "../types";
import { deleteJob, submitJob } from "../lib/api";

// ── Component ─────────────────────────────────────────────────────────────────

export default function SearchPage() {
  const [query, setQuery]                   = useState("");
  // AGENT-CTX: isSubmitting is true only while POST /jobs is in-flight (typically
  // <1s). isPolling (from useJobPoller) covers the longer wait for the worker.
  // The combined loading indicator uses isSubmitting || isPolling.
  const [isSubmitting, setIsSubmitting]     = useState(false);
  const [activeJobId, setActiveJobId]       = useState<string | null>(null);
  const [results, setResults]               = useState<EvidenceItem[]>([]);
  // AGENT-CTX: edges extracted from job.result.edges (added in Chain Links milestone).
  // Defaults to [] so the graph renders without edges until a job completes.
  // Uses ?? [] to handle pre-Chain-Links job records in SQLite that lack the edges field.
  const [edges, setEdges]                   = useState<EdgeResult[]>([]);
  const [error, setError]                   = useState<string | null>(null);
  const [activeQuery, setActiveQuery]       = useState<string>("");

  const { job, isPolling }                  = useJobPoller(activeJobId);
  const { jobs: historyJobs, refresh: refreshHistory, error: historyError } = useJobHistory();

  // AGENT-CTX: Watch the polled job and extract results/error when terminal.
  // refreshHistory() is called on terminal transitions so the sidebar chip
  // updates from "running" to "complete"/"failed" without a manual reload.
  useEffect(() => {
    if (!job) return;
    if (job.status === "complete" && job.result) {
      setResults(job.result.results);
      // AGENT-CTX: ?? [] handles old SQLite records (pre-Chain-Links) that have
      // no edges key in their result_json blob — avoids undefined prop error.
      setEdges(job.result.edges ?? []);
      setError(null);
      refreshHistory();
    } else if (job.status === "failed") {
      setError(job.error ?? "Search failed. Please try again.");
      setResults([]);
      setEdges([]);
      refreshHistory();
    }
  }, [job]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleSearch() {
    if (!query.trim()) return;

    setIsSubmitting(true);
    setError(null);
    setResults([]);
    // Clear active job so the poller stops for the previous job immediately.
    setActiveJobId(null);

    try {
      const data = await submitJob(query.trim());
      setActiveQuery(query.trim());
      // AGENT-CTX: Setting activeJobId kicks off useJobPoller which polls every 3s.
      setActiveJobId(data.job_id);
      // Refresh the sidebar immediately so the new job appears as "pending".
      refreshHistory();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error — could not reach the server.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleRetryJob(item: JobListItem) {
    // Delete the failed job then submit a fresh one with the same query.
    await deleteJob(item.job_id); // best-effort; never throws (see api.ts)
    refreshHistory();

    setIsSubmitting(true);
    setError(null);
    setResults([]);
    setActiveJobId(null);

    try {
      const data = await submitJob(item.query);
      setActiveQuery(item.query);
      setActiveJobId(data.job_id);
      refreshHistory();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Network error — could not reach the server.");
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleNewSearch() {
    setResults([]);
    setEdges([]);
    setError(null);
    setActiveJobId(null);
    setActiveQuery("");
    setQuery("");
  }

  // AGENT-CTX: handleSelectJob is called when the user clicks a sidebar history item.
  // Strategy differs by status:
  //   complete → set activeJobId, poller fetches result in one round-trip and stops.
  //   pending/running → set activeJobId, poller takes over and shows building state.
  //   failed → clear results, show the stored error without a network round-trip.
  function handleSelectJob(item: JobListItem) {
    setError(null);
    setResults([]);
    if (item.status === "failed") {
      setActiveJobId(null);
      setError(item.error ?? "This search failed.");
      setEdges([]);
      setActiveQuery(item.query);
      return;
    }
    setActiveQuery(item.query);
    setActiveJobId(item.job_id);
  }

  const isLoading = isSubmitting || isPolling;

  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        overflow: "hidden",
        fontFamily: "sans-serif",
      }}
    >
      {/* ── Sidebar ──────────────────────────────────────────────────────── */}
      <Sidebar
        jobs={historyJobs}
        activeJobId={activeJobId}
        onSelectJob={handleSelectJob}
        onNewSearch={handleNewSearch}
        onRetryJob={handleRetryJob}
        historyError={historyError}
      />

      {/* ── Main content ─────────────────────────────────────────────────── */}
      {/* AGENT-CTX: overflow:hidden + height:100% required for React Flow canvas
          to fill the viewport correctly. React Flow uses a percentage-height div
          internally; if the parent scrolls (overflow:auto) the canvas collapses.
          padding moved inside the form area only — graph gets the full height. */}
      <main
        style={{
          flex:     1,
          overflow: "hidden",
          height:   "100%",
          display:  "flex",
          flexDirection: "column",
        }}
      >
        {/* AGENT-CTX: Hide h1 + search form once results are displayed — the
            graph fills the full main area. "New Search" in the sidebar restores
            this block by clearing results (handleNewSearch → setResults([])).
            Keep the block during loading so the user sees what they searched for. */}
        {!(results.length > 0 && !isLoading) && (
        <div style={{ padding: "1.25rem 1rem 0.75rem", flexShrink: 0 }}>
          <h1 style={{ fontSize: "1.25rem", marginBottom: "0.75rem", marginTop: 0 }}>
            Drug Target Evidence Search
          </h1>

          {/* AGENT-CTX: Form wraps input + button so pressing Enter also triggers search. */}
          <form
            onSubmit={(e) => { e.preventDefault(); handleSearch(); }}
            style={{ display: "flex", gap: "0.5rem" }}
          >
            {/* AGENT-CTX: Placeholder text must match /drug target/i regex in SearchPage.test.tsx. */}
            <input
              type="text"
              placeholder="Enter drug target (e.g. KRAS G12C)"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Drug target search"
              disabled={isLoading}
              style={{
                flex: 1, padding: "0.5rem 0.75rem", fontSize: "1rem",
                borderRadius: 4, border: "1px solid #ccc",
              }}
            />
            <button
              type="submit"
              disabled={isLoading}
              style={{
                padding: "0.5rem 1.25rem", fontSize: "1rem",
                borderRadius: 4, cursor: isLoading ? "not-allowed" : "pointer",
              }}
            >
              Search
            </button>
          </form>
        </div>
        )}

        {/* AGENT-CTX: Loading text must match /building|evidence map/i in the
            loading test. Do not replace with a CSS-only spinner without also
            updating the test assertion. */}
        {isLoading && (
          <p role="status" style={{ color: "#666", padding: "0 1rem" }}>
            Building your evidence map…
          </p>
        )}

        {/* AGENT-CTX: Error text rendered directly from job.error or network failure. */}
        {error && !isLoading && (
          <p role="alert" style={{ color: "#c00", padding: "0 1rem" }}>{error}</p>
        )}

        {/* AGENT-CTX: Graph view replaces the card list from Milestone 1.
            EvidenceGraph consumes the same results[] EvidenceItem array — the
            async job pipeline (POST /jobs → poll → results) is unchanged.
            flex:1 + min-height:0 allow the graph canvas to fill remaining height. */}
        {results.length > 0 && !isLoading && (
          <div style={{ flex: 1, minHeight: 0 }}>
            <EvidenceGraph items={results} edges={edges} query={activeQuery} />
          </div>
        )}

        {/* AGENT-CTX: Empty state — only shown after a completed search with no results. */}
        {!isLoading && !error && results.length === 0 && activeQuery && (
          <p style={{ color: "#666", padding: "0 1rem" }}>No results found for &ldquo;{activeQuery}&rdquo;.</p>
        )}
      </main>
    </div>
  );
}
