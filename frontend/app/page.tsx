"use client";

// AGENT-CTX: "use client" required — component uses useState, hooks, and event handlers.
// Next.js App Router defaults to Server Components; this directive opts in to client
// rendering. Do NOT remove — the component will break silently on the server.

import { useEffect, useState } from "react";
import { Sidebar } from "../components/Sidebar";
import { useJobHistory } from "../hooks/useJobHistory";
import { useJobPoller } from "../hooks/useJobPoller";
import {
  EvidenceItem,
  JobListItem,
  JobSubmitResponse,
} from "../types";

// AGENT-CTX: API_URL is the only place the backend URL is referenced in this file.
// NEXT_PUBLIC_API_URL must be set in:
//   - frontend/.env.local (local dev, points to http://localhost:8000)
//   - Vercel environment variables (production, points to Render backend URL)
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Colour maps ───────────────────────────────────────────────────────────────

// AGENT-CTX: BADGE_COLOUR, CONFIDENCE_TIER_COLOUR, EFFECT_DIRECTION_COLOUR are
// unchanged from the Milestone 1 SearchPage. All values must remain present.
const BADGE_COLOUR: Record<string, string> = {
  "clinical trial": "#1a6faf",
  "animal model":   "#6a3d9a",
  "human genetics": "#33a02c",
  "in vitro":       "#b15928",
  "review":         "#888888",
};

const CONFIDENCE_TIER_COLOUR: Record<string, string> = {
  high:   "#2d6a4f",
  medium: "#e07c00",
  low:    "#888888",
};

const EFFECT_DIRECTION_COLOUR: Record<string, string> = {
  supports:    "#2d6a4f",
  contradicts: "#c00000",
  neutral:     "#666666",
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function SearchPage() {
  const [query, setQuery]                   = useState("");
  // AGENT-CTX: isSubmitting is true only while POST /jobs is in-flight (typically
  // <1s). isPolling (from useJobPoller) covers the longer wait for the worker.
  // The combined loading indicator uses isSubmitting || isPolling.
  const [isSubmitting, setIsSubmitting]     = useState(false);
  const [activeJobId, setActiveJobId]       = useState<string | null>(null);
  const [results, setResults]               = useState<EvidenceItem[]>([]);
  const [error, setError]                   = useState<string | null>(null);
  const [activeQuery, setActiveQuery]       = useState<string>("");

  const { job, isPolling }                  = useJobPoller(activeJobId);
  const { jobs: historyJobs, refresh: refreshHistory } = useJobHistory();

  // AGENT-CTX: Watch the polled job and extract results/error when terminal.
  // refreshHistory() is called on terminal transitions so the sidebar chip
  // updates from "running" to "complete"/"failed" without a manual reload.
  useEffect(() => {
    if (!job) return;
    if (job.status === "complete" && job.result) {
      setResults(job.result.results);
      setError(null);
      refreshHistory();
    } else if (job.status === "failed") {
      setError(job.error ?? "Search failed. Please try again.");
      setResults([]);
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
      const response = await fetch(`${API_URL}/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim() }),
      });

      if (!response.ok) {
        let detail = `Request failed with status ${response.status}`;
        try {
          const body = await response.json();
          if (body?.detail) detail = body.detail;
        } catch {
          // JSON parse failed — use the generic status message above.
        }
        setError(detail);
        return;
      }

      const data: JobSubmitResponse = await response.json();
      setActiveQuery(query.trim());
      // AGENT-CTX: Setting activeJobId kicks off useJobPoller which polls every 3s.
      setActiveJobId(data.job_id);
      // Refresh the sidebar immediately so the new job appears as "pending".
      refreshHistory();
    } catch {
      setError("Network error — could not reach the server.");
    } finally {
      setIsSubmitting(false);
    }
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
      />

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <main
        style={{
          flex: 1,
          overflow: "auto",
          padding: "2rem 1rem",
          maxWidth: 820,
        }}
      >
        <h1 style={{ fontSize: "1.5rem", marginBottom: "1rem" }}>
          Drug Target Evidence Search
        </h1>

        {/* AGENT-CTX: Form wraps input + button so pressing Enter also triggers search. */}
        <form
          onSubmit={(e) => { e.preventDefault(); handleSearch(); }}
          style={{ display: "flex", gap: "0.5rem", marginBottom: "1.5rem" }}
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

        {/* AGENT-CTX: Loading text must match /building|evidence map/i in the
            loading test. Do not replace with a CSS-only spinner without also
            updating the test assertion. */}
        {isLoading && (
          <p role="status" style={{ color: "#666" }}>
            Building your evidence map…
          </p>
        )}

        {/* AGENT-CTX: Error text rendered directly from job.error or network failure.
            Must contain text matching /error|failed/i for the error test, OR the
            specific backend message (e.g. "PubMed returned no results"). The test
            now checks for the actual message rather than a generic regex. */}
        {error && !isLoading && (
          <p role="alert" style={{ color: "#c00" }}>{error}</p>
        )}

        {results.length > 0 && !isLoading && (
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {results.map((item, index) => (
              // AGENT-CTX: Key uses pmid + index. pmids may repeat across queries so
              // index is included for uniqueness. Safe here — list is never reordered.
              <li
                key={`${item.pmid}-${index}`}
                style={{
                  padding: "1rem",
                  marginBottom: "0.75rem",
                  borderRadius: 6,
                  border: "1px solid #e0e0e0",
                  backgroundColor: "#fafafa",
                }}
              >
                {/* ── Row 1: title ─────────────────────────────────────── */}
                <a
                  href={`https://pubmed.ncbi.nlm.nih.gov/${item.pmid}/`}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: "inherit", textDecoration: "none" }}
                >
                  <p style={{ margin: "0 0 0.6rem 0", fontSize: "0.95rem", fontWeight: 500, lineHeight: 1.4 }}>
                    {item.title}
                  </p>
                </a>

                {/* ── Row 2: badge strip ───────────────────────────────── */}
                {/* AGENT-CTX: evidence_type badge text must remain the raw EvidenceType
                    string — getAllByText("clinical trial") in tests targets this span. */}
                <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", marginBottom: "0.5rem" }}>
                  <span style={{
                    fontSize: "0.72rem", fontWeight: 600,
                    padding: "0.2rem 0.5rem", borderRadius: 3,
                    color: "#fff", whiteSpace: "nowrap",
                    backgroundColor: BADGE_COLOUR[item.evidence_type] ?? "#888",
                  }}>
                    {item.evidence_type}
                  </span>
                  <span style={{
                    fontSize: "0.72rem", fontWeight: 600,
                    padding: "0.2rem 0.5rem", borderRadius: 3,
                    color: "#fff", whiteSpace: "nowrap",
                    backgroundColor: CONFIDENCE_TIER_COLOUR[item.confidence_tier] ?? "#888",
                  }}>
                    {item.confidence_tier}
                  </span>
                </div>

                {/* ── Row 3: effect direction ──────────────────────────── */}
                <p style={{ margin: "0 0 0.35rem 0", fontSize: "0.82rem" }}>
                  <span style={{ color: "#888", marginRight: "0.3rem" }}>Direction:</span>
                  <span style={{ fontWeight: 600, color: EFFECT_DIRECTION_COLOUR[item.effect_direction] ?? "#666" }}>
                    {item.effect_direction}
                  </span>
                </p>

                {/* ── Row 4: model organism (hidden when "not reported") ── */}
                {item.model_organism && item.model_organism !== "not reported" && (
                  <p style={{ margin: "0 0 0.35rem 0", fontSize: "0.82rem", color: "#444" }}>
                    <span style={{ color: "#888", marginRight: "0.3rem" }}>Organism:</span>
                    {item.model_organism}
                  </p>
                )}

                {/* ── Row 5: sample size (hidden when "not reported") ───── */}
                {item.sample_size && item.sample_size !== "not reported" && (
                  <p style={{ margin: 0, fontSize: "0.82rem", color: "#444" }}>
                    <span style={{ color: "#888", marginRight: "0.3rem" }}>Sample:</span>
                    {item.sample_size}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}

        {/* AGENT-CTX: Empty state — only shown after a completed search with no results. */}
        {!isLoading && !error && results.length === 0 && activeQuery && (
          <p style={{ color: "#666" }}>No results found for &ldquo;{activeQuery}&rdquo;.</p>
        )}
      </main>
    </div>
  );
}
