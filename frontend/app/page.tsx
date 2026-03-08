"use client";

// AGENT-CTX: "use client" required — component uses useState (React hook).
// Next.js App Router defaults to Server Components; explicit opt-in needed for interactivity.

import { useState } from "react";

// AGENT-CTX: STUB — this is the T1 scaffold shell.
// The component renders the search input but does NOT implement:
//   - loading state (test_shows_loading_state will FAIL — expected RED)
//   - result fetching or rendering (test_renders_result_list will FAIL — expected RED)
// Full implementation in T7. Do not add feature logic here before T7.

export default function SearchPage() {
  const [query, setQuery] = useState("");

  // AGENT-CTX: TODO (T7) — add isLoading, results, error state here.
  // AGENT-CTX: TODO (T7) — implement handleSearch() that calls NEXT_PUBLIC_API_URL/search.
  // AGENT-CTX: TODO (T7) — render loading indicator and results list below the form.

  return (
    <main>
      <h1>Drug Target Evidence Search</h1>
      <form onSubmit={(e) => e.preventDefault()}>
        {/* AGENT-CTX: Placeholder text must match /drug target/i regex used in test_renders_search_input */}
        <input
          type="text"
          placeholder="Enter drug target (e.g. KRAS G12C)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Drug target search"
        />
        <button type="submit">Search</button>
      </form>
    </main>
  );
}
