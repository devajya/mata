"use client";

// AGENT-CTX: "use client" required — component uses useState and event handlers.
// Next.js App Router defaults to Server Components; this directive opts in to client
// rendering. Do NOT remove — the component will break silently on the server.

import { useState } from "react";
import { EvidenceItem, SearchResponse } from "../types";

// AGENT-CTX: API_URL is the only place the backend URL is referenced.
// NEXT_PUBLIC_API_URL must be set in:
//   - frontend/.env.local (local dev, points to http://localhost:8000)
//   - Vercel environment variables (production, points to Render backend URL)
// Falls back to localhost:8000 so the dev server works without an env file.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Colour maps ───────────────────────────────────────────────────────────────

// AGENT-CTX: BADGE_COLOUR maps EvidenceType → badge background. All 5 values
// must be present. If EvidenceType values change in types.ts / models.py, update
// this map. These colours are unchanged from the walking skeleton.
const BADGE_COLOUR: Record<string, string> = {
  "clinical trial": "#1a6faf",
  "animal model":   "#6a3d9a",
  "human genetics": "#33a02c",
  "in vitro":       "#b15928",
  "review":         "#888888",
};

// AGENT-CTX: CONFIDENCE_TIER_COLOUR maps ConfidenceTier → badge background.
// All 3 values must be present — the engine always returns one of these.
// Colour semantics: high = green (strong evidence), medium = amber (moderate),
// low = grey (weak or unknown). Same green as EFFECT_DIRECTION_COLOUR "supports"
// is intentional — both signal "positive/strong" to the researcher.
// If ConfidenceTier values change in types.ts / confidence.py, update this map.
const CONFIDENCE_TIER_COLOUR: Record<string, string> = {
  high:   "#2d6a4f",
  medium: "#e07c00",
  low:    "#888888",
};

// AGENT-CTX: EFFECT_DIRECTION_COLOUR maps EffectDirection → text colour.
// Effect direction is rendered as coloured text (not a badge background) to give
// it different visual weight from the badge row — a researcher scans badges first,
// then reads direction text. All 3 values must be present.
// If EffectDirection values change in types.ts / llm.py system prompt, update here.
const EFFECT_DIRECTION_COLOUR: Record<string, string> = {
  supports:    "#2d6a4f",  // green — positive link to target
  contradicts: "#c00000",  // red   — negative/null result
  neutral:     "#666666",  // grey  — review or inconclusive
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function SearchPage() {
  const [query, setQuery]         = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults]     = useState<EvidenceItem[]>([]);
  const [error, setError]         = useState<string | null>(null);

  async function handleSearch() {
    if (!query.trim()) return;

    // AGENT-CTX: Reset all output state before each new search so stale results
    // from a previous query are never shown alongside a new query's loading state.
    setIsLoading(true);
    setError(null);
    setResults([]);

    try {
      const response = await fetch(
        `${API_URL}/search?query=${encodeURIComponent(query)}`
      );

      if (!response.ok) {
        // AGENT-CTX: Non-200 response — read FastAPI's error detail from JSON body.
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

      const data: SearchResponse = await response.json();
      setResults(data.results);
    } catch {
      // AGENT-CTX: Network-level failure (fetch threw) — server unreachable.
      setError("Network error — could not reach the server.");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main style={{ maxWidth: 820, margin: "0 auto", padding: "2rem 1rem", fontFamily: "sans-serif" }}>
      <h1 style={{ fontSize: "1.5rem", marginBottom: "1rem" }}>
        Drug Target Evidence Search
      </h1>

      {/* AGENT-CTX: Form wraps input + button so pressing Enter also triggers search. */}
      <form
        onSubmit={(e) => { e.preventDefault(); handleSearch(); }}
        style={{ display: "flex", gap: "0.5rem", marginBottom: "1.5rem" }}
      >
        {/* AGENT-CTX: Placeholder text must match /drug target/i regex in SearchPage.test.tsx.
            Do not change without updating that test. */}
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

      {/* AGENT-CTX: Loading text must match /loading/i regex in the loading test.
          Do not replace with a CSS-only spinner without also updating the test. */}
      {isLoading && (
        <p role="status" style={{ color: "#666" }}>Loading…</p>
      )}

      {/* AGENT-CTX: Error text must match /error|failed/i regex in the error test.
          The API detail string typically contains "failed" or "error". */}
      {error && !isLoading && (
        <p role="alert" style={{ color: "#c00" }}>{error}</p>
      )}

      {/* AGENT-CTX: Structured result cards — Milestone 1 replacement for the flat list.
          Each card shows: title, evidence type + confidence tier badges, effect direction,
          and optional organism / sample size rows. See card structure notes below. */}
      {results.length > 0 && !isLoading && (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {results.map((item, index) => (
            // AGENT-CTX: Key uses pmid + index. The test mock returns 10 identical pmids
            // so index is needed for uniqueness. Index alone is discouraged but safe here
            // since the list is never reordered in-place.
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
              {/* ── Row 1: title ───────────────────────────────────────────── */}
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
              
              {/* ── Row 2: badge strip ─────────────────────────────────────── */}
              {/* AGENT-CTX: evidence_type badge is kept exactly as the walking skeleton.
                  getAllByText("clinical trial") in existing tests targets this span — the
                  text must remain the raw EvidenceType string with no extra wrapping text. */}
              <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", marginBottom: "0.5rem" }}>
                <span
                  style={{
                    fontSize: "0.72rem", fontWeight: 600,
                    padding: "0.2rem 0.5rem", borderRadius: 3,
                    color: "#fff", whiteSpace: "nowrap",
                    backgroundColor: BADGE_COLOUR[item.evidence_type] ?? "#888",
                  }}
                >
                  {item.evidence_type}
                </span>

                {/* AGENT-CTX: confidence_tier badge uses CONFIDENCE_TIER_COLOUR map.
                    Falls back to "#888" if the value is missing (e.g. stale test data
                    without the new fields — safe, no crash, invisible text).
                    Text is the raw tier label ("high" / "medium" / "low") so tests can
                    find it with getByText("high") etc. */}
                <span
                  style={{
                    fontSize: "0.72rem", fontWeight: 600,
                    padding: "0.2rem 0.5rem", borderRadius: 3,
                    color: "#fff", whiteSpace: "nowrap",
                    backgroundColor: CONFIDENCE_TIER_COLOUR[item.confidence_tier] ?? "#888",
                  }}
                >
                  {item.confidence_tier}
                </span>
              </div>

              {/* ── Row 3: effect direction ────────────────────────────────── */}
              {/* AGENT-CTX: Rendered as coloured text, not a badge, to give it lighter
                  visual weight than the study-design badges above. Researchers read badges
                  first for study type, then scan direction text for the finding.
                  Falls back to grey (#666) if value is missing — safe for stale test data. */}
              <p style={{ margin: "0 0 0.35rem 0", fontSize: "0.82rem" }}>
                <span style={{ color: "#888", marginRight: "0.3rem" }}>Direction:</span>
                <span
                  style={{
                    fontWeight: 600,
                    color: EFFECT_DIRECTION_COLOUR[item.effect_direction] ?? "#666",
                  }}
                >
                  {item.effect_direction}
                </span>
              </p>

              {/* ── Row 4: model organism (conditional) ────────────────────── */}
              {/* AGENT-CTX: Row is completely hidden (not rendered) when value is
                  "not reported". Do NOT render a greyed-out "not reported" label —
                  it adds noise for clinical trials and human genetics studies.
                  The condition also covers undefined (old test data without the field)
                  which renders React-safe as nothing. */}
              {item.model_organism && item.model_organism !== "not reported" && (
                <p style={{ margin: "0 0 0.35rem 0", fontSize: "0.82rem", color: "#444" }}>
                  <span style={{ color: "#888", marginRight: "0.3rem" }}>Organism:</span>
                  {item.model_organism}
                </p>
              )}

              {/* ── Row 5: sample size (conditional) ───────────────────────── */}
              {/* AGENT-CTX: Same hiding rule as model_organism — omit the row entirely
                  when "not reported" or undefined. Tests verify this with
                  queryByText("not reported") returning null. */}
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

      {/* AGENT-CTX: Empty state — only shown after a completed search with zero results.
          Distinguishes "never searched" from "searched, found nothing". */}
      {!isLoading && !error && results.length === 0 && query && (
        <p style={{ color: "#666" }}>No results found for &ldquo;{query}&rdquo;.</p>
      )}
    </main>
  );
}
