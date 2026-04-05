/**
 * Tests for SearchPage (Milestone 3 — async job pipeline).
 *
 * AGENT-CTX: The page now uses POST /jobs → poll GET /job/{id} instead of
 * GET /search. All fetch mocks must handle the full call sequence:
 *   1. GET /jobs (useJobHistory on mount)
 *   2. POST /jobs (on submit)
 *   3. GET /job/{id} (useJobPoller, first poll)
 *   4. GET /jobs again (refreshHistory after terminal state)
 *
 * AGENT-CTX: mockJobFlow() uses mockImplementation (not mockResolvedValueOnce)
 * to route calls by method and URL. This avoids fragile call-order dependencies
 * when multiple hooks make concurrent fetches.
 *
 * AGENT-CTX: The loading text is now "Building your evidence map…" (AC1).
 * Tests that previously checked /loading/i now check /building|evidence map/i.
 *
 * AGENT-CTX: Walking-skeleton tests (1–2: static render) are unchanged.
 * Milestone 1 card-field tests (6–10) are updated to use mockJobFlow.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import SearchPage from "../app/page";
import { EvidenceItem, JobListItem, JobStatusResponse } from "../types";

// ── Shared fixtures ───────────────────────────────────────────────────────────

const BASE_MOCK_ITEM: EvidenceItem = {
  pmid:             "12345678",
  title:            "Sotorasib in KRAS G12C NSCLC",
  abstract:         "Phase III trial showing progression-free survival benefit.",
  evidence_type:    "clinical trial",
  effect_direction: "supports",
  model_organism:   "not reported",
  sample_size:      "not reported",
  confidence_tier:  "high",
  layer:            3,
  publication_year: 2021,
};

const TEST_JOB_ID = "test-job-id-001";

/**
 * Sets up global.fetch to handle the full job-flow call sequence.
 *
 * AGENT-CTX: Routes by method+URL pattern:
 *   GET  /jobs          → history list (empty by default; populated after terminal)
 *   POST /jobs          → job submission response
 *   GET  /job/{id}      → job status (complete with items, or failed with error)
 *
 * Returns the job_id used so tests can assert on sidebar state if needed.
 */
function mockJobFlow(
  items: EvidenceItem[],
  { failWith }: { failWith?: string } = {}
): void {
  const completedJob: JobStatusResponse = {
    job_id: TEST_JOB_ID,
    query: "KRAS G12C",
    status: "complete",
    result: { query: "KRAS G12C", results: items },
    error: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  const failedJob: JobStatusResponse = {
    job_id: TEST_JOB_ID,
    query: "KRAS G12C",
    status: "failed",
    result: null,
    error: failWith ?? "Search failed.",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  const historyItem: JobListItem = {
    job_id: TEST_JOB_ID,
    query: "KRAS G12C",
    status: failWith ? "failed" : "complete",
    error: failWith ?? null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  (global.fetch as jest.Mock).mockImplementation(
    (url: string, options?: RequestInit) => {
      const method = options?.method ?? "GET";

      // POST /jobs — job submission
      if (method === "POST" && (url as string).includes("/jobs")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            job_id: TEST_JOB_ID,
            query: "KRAS G12C",
            status: "pending",
            created_at: new Date().toISOString(),
          }),
        });
      }

      // GET /job/{id} — status poll
      if (method === "GET" && (url as string).includes(`/job/${TEST_JOB_ID}`)) {
        return Promise.resolve({
          ok: true,
          json: async () => (failWith ? failedJob : completedJob),
        });
      }

      // GET /jobs — history list (always returns stable list)
      if (method === "GET" && (url as string).includes("/jobs")) {
        return Promise.resolve({
          ok: true,
          json: async () => [historyItem],
        });
      }

      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) });
    }
  );
}

/**
 * Drives the search form: sets input value and clicks the submit button.
 */
function submitSearch(query = "KRAS G12C"): void {
  fireEvent.change(screen.getByPlaceholderText(/drug target/i), {
    target: { value: query },
  });
  fireEvent.click(screen.getByRole("button", { name: /search/i }));
}

// ── Hooks ──────────────────────────────────────────────────────────────────────

beforeEach(() => {
  jest.resetAllMocks();
  // AGENT-CTX: Default fetch mock for GET /jobs (sidebar on mount). Tests that
  // need different behaviour call mockJobFlow() or set their own mock.
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: async () => [],
  }) as jest.Mock;
});

// ── Walking-skeleton tests (static render — unchanged from T7) ────────────────

test("renders search input with correct placeholder", () => {
  /**
   * AGENT-CTX: Regex /drug target/i must match the placeholder in page.tsx.
   * If you change the placeholder text, update this regex too.
   */
  render(<SearchPage />);
  expect(screen.getByPlaceholderText(/drug target/i)).toBeInTheDocument();
});

test("renders search button", () => {
  render(<SearchPage />);
  expect(screen.getByRole("button", { name: /search/i })).toBeInTheDocument();
});

// ── Milestone 3: async job flow tests ────────────────────────────────────────

test("shows building state while job is pending", async () => {
  /**
   * AC1: UI shows "Building your evidence map…" state after submission.
   *
   * AGENT-CTX: POST /jobs is made to hang (never resolves) so isSubmitting=true
   * is held long enough for findByText to detect it. React 18 batches all
   * microtasks before the first render tick, so an immediately-resolving mock
   * would complete the full async cycle before the DOM is inspectable.
   * A hanging POST is the correct model for this assertion: it simulates the
   * user experience between click and job_id receipt (~100-500ms in prod).
   *
   * Loading text must match /building|evidence map/i.
   * If you change the text in page.tsx, update this regex.
   */
  (global.fetch as jest.Mock).mockImplementation(
    (url: string, options?: RequestInit) => {
      const method = options?.method ?? "GET";
      // POST /jobs hangs — keeps isSubmitting=true indefinitely.
      if (method === "POST") {
        return new Promise(() => {});
      }
      // GET /jobs (useJobHistory on mount) returns empty list normally.
      return Promise.resolve({ ok: true, json: async () => [] });
    }
  );

  render(<SearchPage />);
  submitSearch();

  expect(await screen.findByText(/building|evidence map/i)).toBeInTheDocument();
});

test("renders graph with node titles after job completes", async () => {
  /**
   * AC2: Frontend transitions to the graph view on job completion.
   * AGENT-CTX: The card list is replaced by EvidenceGraph (Milestone 2).
   * EvidenceNode renders each item title — getAllByText verifies all 10 nodes
   * are present. @xyflow/react is mocked (see jest.config.js moduleNameMapper)
   * so ReactFlow renders nodeTypes components into plain divs in jsdom.
   */
  const mockResults: EvidenceItem[] = Array(10).fill({ ...BASE_MOCK_ITEM });
  mockJobFlow(mockResults);

  render(<SearchPage />);
  submitSearch();

  await waitFor(() => {
    expect(screen.getAllByText("Sotorasib in KRAS G12C NSCLC")).toHaveLength(10);
  });

  // evidence_type badge rendered by EvidenceNode
  expect(screen.getAllByText("clinical trial")).toHaveLength(10);
});

test("shows error message when job fails", async () => {
  /**
   * AC3: Failed jobs surface a human-readable error.
   * AGENT-CTX: The error text is job.error from the backend. The test asserts
   * on the specific message rather than a generic regex so it validates the
   * full error propagation path (worker → SQLite → GET /job/{id} → UI).
   */
  mockJobFlow([], { failWith: "PubMed returned no results for 'KRAS G12C'." });

  render(<SearchPage />);
  submitSearch();

  expect(
    await screen.findByText(/PubMed returned no results/i)
  ).toBeInTheDocument();
});

test("shows error when POST /jobs itself fails (network or 503)", async () => {
  /**
   * Non-200 from POST /jobs → error shown without entering polling state.
   * AGENT-CTX: Tests the submission error path (distinct from job failure).
   */
  (global.fetch as jest.Mock).mockImplementation(
    (url: string, options?: RequestInit) => {
      const method = options?.method ?? "GET";
      if (method === "POST") {
        return Promise.resolve({
          ok: false,
          status: 503,
          json: async () => ({ detail: "Job queue not configured." }),
        });
      }
      return Promise.resolve({ ok: true, json: async () => [] });
    }
  );

  render(<SearchPage />);
  submitSearch();

  expect(await screen.findByText(/job queue not configured/i)).toBeInTheDocument();
});

// ── Milestone 1 + 2: Node field tests (EvidenceNode renders all card fields) ──
// AGENT-CTX: Card list replaced by EvidenceGraph (Milestone 2). EvidenceNode
// renders the same fields that the old card list rendered. Tests pass because
// @xyflow/react is mocked — ReactFlow renders nodeTypes components into plain
// divs, making EvidenceNode content queryable by findByText / queryByText.

test("renders confidence_tier badge in EvidenceNode after job completes", async () => {
  mockJobFlow([{ ...BASE_MOCK_ITEM, confidence_tier: "high" }]);
  render(<SearchPage />);
  submitSearch();

  // EvidenceNode renders "high confidence" — findByText uses partial match via regex
  expect(await screen.findByText(/high confidence/i)).toBeInTheDocument();
});

test("renders effect_direction in NodeDrawer after clicking a node", async () => {
  /**
   * AGENT-CTX: effect_direction lives in NodeDrawer (detail panel), not in
   * EvidenceNode (graph card). This test clicks the rendered node to open the
   * drawer, then asserts on the direction field.
   */
  mockJobFlow([{ ...BASE_MOCK_ITEM, effect_direction: "supports" }]);
  render(<SearchPage />);
  submitSearch();

  // Wait for graph to render, then click the evidence node
  await screen.findByText("Sotorasib in KRAS G12C NSCLC");
  fireEvent.click(screen.getAllByText("Sotorasib in KRAS G12C NSCLC")[0]);

  expect(await screen.findByText("supports")).toBeInTheDocument();
});

test("hides model_organism in NodeDrawer when value is 'not reported'", async () => {
  mockJobFlow([{ ...BASE_MOCK_ITEM, model_organism: "not reported", sample_size: "not reported" }]);
  render(<SearchPage />);
  submitSearch();

  await screen.findByText("Sotorasib in KRAS G12C NSCLC");
  fireEvent.click(screen.getAllByText("Sotorasib in KRAS G12C NSCLC")[0]);

  await screen.findByText(/direction/i); // drawer is open
  expect(screen.queryByText("not reported")).not.toBeInTheDocument();
});

test("shows model_organism in NodeDrawer when value is populated", async () => {
  mockJobFlow([{ ...BASE_MOCK_ITEM, model_organism: "mouse", evidence_type: "animal model" }]);
  render(<SearchPage />);
  submitSearch();

  await screen.findByText("Sotorasib in KRAS G12C NSCLC");
  fireEvent.click(screen.getAllByText("Sotorasib in KRAS G12C NSCLC")[0]);

  expect(await screen.findByText("mouse")).toBeInTheDocument();
});

test("hides sample_size in NodeDrawer when value is 'not reported'", async () => {
  mockJobFlow([{ ...BASE_MOCK_ITEM, sample_size: "not reported", model_organism: "not reported" }]);
  render(<SearchPage />);
  submitSearch();

  await screen.findByText("Sotorasib in KRAS G12C NSCLC");
  fireEvent.click(screen.getAllByText("Sotorasib in KRAS G12C NSCLC")[0]);

  await screen.findByText(/direction/i); // drawer is open
  expect(screen.queryByText("not reported")).not.toBeInTheDocument();
});

test("shows sample_size in NodeDrawer when value is populated", async () => {
  mockJobFlow([{ ...BASE_MOCK_ITEM, sample_size: "n=345" }]);
  render(<SearchPage />);
  submitSearch();

  await screen.findByText("Sotorasib in KRAS G12C NSCLC");
  fireEvent.click(screen.getAllByText("Sotorasib in KRAS G12C NSCLC")[0]);

  expect(await screen.findByText("n=345")).toBeInTheDocument();
});

// ── Milestone 3: Sidebar tests ────────────────────────────────────────────────

test("renders sidebar with 'Previous Searches' heading", () => {
  /**
   * AC5: Sidebar is visible on page load.
   */
  render(<SearchPage />);
  expect(screen.getByText(/previous searches/i)).toBeInTheDocument();
});

test("shows 'No searches yet' when history is empty", async () => {
  /**
   * AC5: Empty sidebar state is user-friendly.
   */
  render(<SearchPage />);
  expect(await screen.findByText(/no searches yet/i)).toBeInTheDocument();
});

test("sidebar shows submitted query after search", async () => {
  /**
   * AC5: Sidebar updates after a job is submitted.
   */
  mockJobFlow([{ ...BASE_MOCK_ITEM }]);
  render(<SearchPage />);
  submitSearch("KRAS G12C");

  // Sidebar should eventually show the query text (from GET /jobs response).
  await waitFor(() => {
    // The query appears both in the sidebar list item and potentially the main area.
    // getAllByText handles multiple instances.
    expect(screen.getAllByText("KRAS G12C").length).toBeGreaterThan(0);
  });
});
