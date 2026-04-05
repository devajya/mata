"use client";

import { JobListItem, JobStatus } from "../types";

// AGENT-CTX: STATUS_CHIP_COLOUR maps JobStatus → background colour.
// All 4 values must be present. If JobStatus values change in types.ts / db/models.py,
// update this map. Colour semantics: pending=amber (waiting), running=blue (active),
// complete=green (done), failed=red (error).
const STATUS_CHIP_COLOUR: Record<JobStatus, string> = {
  pending:  "#e07c00",
  running:  "#1a6faf",
  complete: "#2d6a4f",
  failed:   "#c00000",
};

interface SidebarProps {
  jobs: JobListItem[];
  // AGENT-CTX: activeJobId highlights the currently selected/polling job.
  // null = no job selected. The sidebar uses this for background highlight only —
  // it does not own the selection state. Selection is owned by the parent (page.tsx).
  activeJobId: string | null;
  onSelectJob: (job: JobListItem) => void;
  onNewSearch: () => void;
}

/**
 * Job history sidebar — renders a list of past searches with status chips.
 *
 * AGENT-CTX: SoC contract:
 *   - Sidebar is purely presentational. It renders jobs[] and calls onSelectJob.
 *   - It does NOT fetch data — that is useJobHistory()'s responsibility.
 *   - It does NOT own the active job state — that lives in page.tsx.
 *   - When auth is added, the jobs[] prop will be filtered by the backend;
 *     no changes to this component are needed.
 */
export function Sidebar({ jobs, activeJobId, onSelectJob, onNewSearch }: SidebarProps) {
  return (
    <aside
      aria-label="Search history"
      style={{
        width: 260,
        flexShrink: 0,
        borderRight: "1px solid #e0e0e0",
        backgroundColor: "#fafafa",
        overflow: "auto",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0.75rem 1rem",
          borderBottom: "1px solid #e0e0e0",
        }}
      >
        <h2
          style={{
            margin: 0,
            fontSize: "0.875rem",
            fontWeight: 600,
            color: "#333",
          }}
        >
          Previous Searches
        </h2>
        <button
          onClick={onNewSearch}
          title="Start a new search"
          style={{
            border: "1px solid #ccc",
            background: "#fff",
            cursor: "pointer",
            borderRadius: 4,
            padding: "0.2rem 0.5rem",
            fontSize: "0.78rem",
            color: "#333",
            fontWeight: 600,
            lineHeight: 1,
          }}
        >
          + New
        </button>
      </div>

      {jobs.length === 0 ? (
        <p style={{ padding: "1rem", color: "#888", fontSize: "0.82rem", margin: 0 }}>
          No searches yet. Submit a query to get started.
        </p>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {jobs.map((job) => (
            <li
              key={job.job_id}
              onClick={() => onSelectJob(job)}
              role="button"
              aria-label={`Select search: ${job.query}`}
              style={{
                padding: "0.75rem 1rem",
                cursor: "pointer",
                borderBottom: "1px solid #e0e0e0",
                backgroundColor: job.job_id === activeJobId ? "#e8f4fd" : "transparent",
              }}
            >
              {/* Query text */}
              <p
                style={{
                  margin: "0 0 0.35rem 0",
                  fontSize: "0.85rem",
                  fontWeight: 500,
                  // Truncate long queries with ellipsis
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {job.query}
              </p>

              {/* Status chip + timestamp */}
              <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
                <span
                  style={{
                    fontSize: "0.68rem",
                    fontWeight: 600,
                    padding: "0.15rem 0.4rem",
                    borderRadius: 3,
                    backgroundColor: STATUS_CHIP_COLOUR[job.status],
                    color: "#fff",
                    textTransform: "uppercase",
                    letterSpacing: "0.02em",
                  }}
                >
                  {job.status}
                </span>
                <span style={{ fontSize: "0.7rem", color: "#888" }}>
                  {new Date(job.created_at).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
