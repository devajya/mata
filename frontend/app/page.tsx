"use client";

// AGENT-CTX: "use client" required — component uses useState and event handlers.
// Next.js App Router defaults to Server Components; this directive opts in to client rendering.
// Do NOT remove it — the component will break silently on the server.

import { useState } from "react";
import { EvidenceItem, SearchResponse } from "../types";

// AGENT-CTX: API_URL is the only place the backend URL is referenced.
// NEXT_PUBLIC_API_URL must be set in:
//   - frontend/.env.local (local dev, points to http://localhost:8000)
//   - Vercel environment variables (production, points to Render backend URL)
// Falls back to localhost:8000 so the dev server works without an env file.
// Do NOT hardcode a production URL here — it would break local dev and make
// the deployment URL impossible to change without a code change.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// AGENT-CTX: Badge colour map for evidence type labels.
// Kept as a plain object (not CSS modules/Tailwind) to avoid build config complexity
// in the walking skeleton. All 5 EvidenceType values must have an entry here.
// If EvidenceType values change in types.ts/models.py, update this map too.
const BADGE_COLOUR: Record<string, string> = {
  "clinical trial": "#1a6faf",
  "animal model":   "#6a3d9a",
  "human genetics": "#33a02c",
  "in vitro":       "#b15928",
  "review":         "#888888",
};

export default function SearchPage() {
  const [query, setQuery]       = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults]   = useState<EvidenceItem[]>([]);
  const [error, setError]       = useState<string | null>(null);

  // AGENT-CTX: handleSearch is an async function attached to the form's onSubmit.
  // It must be defined as a plain function (not useCallback) — no memoisation needed
  // for the walking skeleton since the component re-renders only on state change.
  async function handleSearch() {
    if (!query.trim()) return;

    // AGENT-CTX: Reset all output state before each new search so stale results
    // from a previous query are never shown alongside a new query's loading state.
    setIsLoading(true);
    setError(null);
    setResults([]);

    try {
      // AGENT-CTX: encodeURIComponent handles spaces and special chars in target names
      // (e.g. "KRAS G12C" → "KRAS%20G12C"). Required for a valid GET query string.
      const response = await fetch(
        `${API_URL}/search?query=${encodeURIComponent(query)}`
      );

      if (!response.ok) {
        // AGENT-CTX: Non-200 response — read the FastAPI error detail from JSON body.
        // Falls back to a generic message if the body is not parseable.
        let detail = `Request failed with status ${response.status}`;
        try {
          const body = await response.json();
          if (body?.detail) detail = body.detail;
        } catch {
          // JSON parse failed — use the generic message above.
        }
        setError(detail);
        return;
        // AGENT-CTX: `return` here — do not fall through to setResults.
        // The finally block still runs and sets isLoading=false.
      }

      const data: SearchResponse = await response.json();
      setResults(data.results);
    } catch {
      // AGENT-CTX: Network-level failure (fetch threw) — server unreachable.
      // Distinct from a non-200 response (handled above).
      setError("Network error — could not reach the server.");
    } finally {
      // AGENT-CTX: Always clear loading, whether success, API error, or network error.
      // Without this, the loading indicator stays forever after any failure.
      setIsLoading(false);
    }
  }

  return (
    <main style={{ maxWidth: 800, margin: "0 auto", padding: "2rem 1rem", fontFamily: "sans-serif" }}>
      <h1 style={{ fontSize: "1.5rem", marginBottom: "1rem" }}>
        Drug Target Evidence Search
      </h1>

      {/* AGENT-CTX: Form wraps input + button so pressing Enter also triggers search.
          onSubmit calls handleSearch(); e.preventDefault() blocks the native GET redirect. */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          handleSearch();
        }}
        style={{ display: "flex", gap: "0.5rem", marginBottom: "1.5rem" }}
      >
        {/* AGENT-CTX: Placeholder text must match /drug target/i regex in SearchPage.test.tsx.
            Do not change this text without updating the test regex. */}
        <input
          type="text"
          placeholder="Enter drug target (e.g. KRAS G12C)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Drug target search"
          disabled={isLoading}
          style={{ flex: 1, padding: "0.5rem 0.75rem", fontSize: "1rem", borderRadius: 4, border: "1px solid #ccc" }}
        />
        <button
          type="submit"
          disabled={isLoading}
          style={{ padding: "0.5rem 1.25rem", fontSize: "1rem", borderRadius: 4, cursor: isLoading ? "not-allowed" : "pointer" }}
        >
          Search
        </button>
      </form>

      {/* AGENT-CTX: Loading indicator text must match /loading/i regex in the loading test.
          The test mocks fetch to never resolve, so this stays visible indefinitely.
          Do not replace with a pure CSS spinner without also updating the test assertion. */}
      {isLoading && (
        <p role="status" style={{ color: "#666" }}>
          Loading…
        </p>
      )}

      {/* AGENT-CTX: Error text must match /error|failed/i regex in the error test.
          We render the raw detail string from the API — it typically contains "failed" or "error".
          If the API error format changes (not containing either word), update this element or the test. */}
      {error && !isLoading && (
        <p role="alert" style={{ color: "#c00" }}>
          {error}
        </p>
      )}

      {/* AGENT-CTX: Results list — flat, unformatted as per walking skeleton AC.
          Each item renders title in a <span> and evidence_type in a separate <span>
          so getAllByText() in tests can find each independently (exact text match). */}
      {results.length > 0 && !isLoading && (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {results.map((item, index) => (
            // AGENT-CTX: Key uses pmid + index because the test mock returns 10 identical
            // pmids. Index alone is discouraged but safe here since the list is never reordered.
            <li
              key={`${item.pmid}-${index}`}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: "0.75rem",
                padding: "0.75rem 0",
                borderBottom: "1px solid #eee",
              }}
            >
              {/* AGENT-CTX: Title in its own <span> so getAllByText(title) finds exactly 1 node per item.
                  If wrapped in a block element alongside the badge, getAllByText may also match the parent. */}
              <span style={{ flex: 1, fontSize: "0.95rem" }}>
                {item.title}
              </span>

              {/* AGENT-CTX: Evidence type badge — text must be the exact EvidenceType string
                  so getAllByText("clinical trial") finds exactly one node per result item.
                  Do not add extra text (e.g. "Type: clinical trial") without updating the test. */}
              <span
                style={{
                  flexShrink: 0,
                  fontSize: "0.75rem",
                  fontWeight: 600,
                  padding: "0.2rem 0.5rem",
                  borderRadius: 3,
                  color: "#fff",
                  backgroundColor: BADGE_COLOUR[item.evidence_type] ?? "#888",
                  whiteSpace: "nowrap",
                }}
              >
                {item.evidence_type}
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* AGENT-CTX: Empty state — only shown after a completed search with zero results.
          Distinguishes "never searched" from "searched, found nothing". */}
      {!isLoading && !error && results.length === 0 && query && (
        <p style={{ color: "#666" }}>No results found for &ldquo;{query}&rdquo;.</p>
      )}
    </main>
  );
}
