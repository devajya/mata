/**
 * Test stubs for the SearchPage component.
 *
 * AGENT-CTX: Test status at T1 scaffold:
 *   PASS — test_renders_search_input (stub has the input)
 *   FAIL — test_shows_loading_state (no loading logic in stub — expected RED)
 *   FAIL — test_renders_result_list (no fetch/render logic in stub — expected RED)
 *
 * All three tests must be GREEN after T7 implementation.
 * Do not modify test assertions to make them pass — fix the component instead.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import SearchPage from "../app/page";

// AGENT-CTX: Reset fetch mock between tests to prevent cross-test pollution.
beforeEach(() => {
  jest.resetAllMocks();
});

test("renders search input with correct placeholder", () => {
  /**
   * AC: Input field accepts a target name.
   * AGENT-CTX: Regex /drug target/i must match the placeholder in page.tsx.
   * If you change the placeholder text, update this regex too.
   */
  render(<SearchPage />);
  expect(
    screen.getByPlaceholderText(/drug target/i)
  ).toBeInTheDocument();
});

test("renders search button", () => {
  render(<SearchPage />);
  expect(screen.getByRole("button", { name: /search/i })).toBeInTheDocument();
});

test("shows loading state while fetching", async () => {
  /**
   * AC: App shows loading state while waiting for results.
   * AGENT-CTX: Expects a loading indicator (text or role) to appear immediately
   * after the user submits the form and before results arrive.
   * The mock fetch never resolves so loading persists — use findByText to wait.
   */
  // AGENT-CTX: Mock fetch that hangs indefinitely to hold the loading state visible.
  global.fetch = jest.fn(() => new Promise(() => {})) as jest.Mock;

  render(<SearchPage />);
  fireEvent.change(screen.getByPlaceholderText(/drug target/i), {
    target: { value: "KRAS G12C" },
  });
  fireEvent.click(screen.getByRole("button", { name: /search/i }));

  // AGENT-CTX: "Loading" text is the expected loading indicator.
  // If you use a spinner icon instead, update this to check for aria-label or role="status".
  expect(await screen.findByText(/loading/i)).toBeInTheDocument();
});

test("renders result list with title and evidence type after fetch", async () => {
  /**
   * AC: Frontend renders a flat list of results with title + evidence type label.
   * AGENT-CTX: Mock returns 10 identical items to keep the test deterministic.
   * The real API returns unique items — this test only checks rendering, not content.
   */
  const mockResults = Array(10).fill({
    pmid: "12345678",
    title: "Sotorasib in KRAS G12C NSCLC",
    abstract: "Phase III trial...",
    evidence_type: "clinical trial",
  });

  global.fetch = jest.fn().mockResolvedValueOnce({
    ok: true,
    json: async () => ({
      query: "KRAS G12C",
      results: mockResults,
    }),
  }) as jest.Mock;

  render(<SearchPage />);
  fireEvent.change(screen.getByPlaceholderText(/drug target/i), {
    target: { value: "KRAS G12C" },
  });
  fireEvent.click(screen.getByRole("button", { name: /search/i }));

  // AGENT-CTX: waitFor needed because fetch is async — results render after state update.
  await waitFor(() => {
    expect(
      screen.getAllByText("Sotorasib in KRAS G12C NSCLC")
    ).toHaveLength(10);
  });

  // Each result must show the evidence type label.
  expect(screen.getAllByText("clinical trial")).toHaveLength(10);
});

test("shows error message when fetch fails", async () => {
  /**
   * AGENT-CTX: Error handling spec — network errors or non-200 responses must
   * display an inline error message. Not in original AC but required for
   * acceptable UX. If this test is too prescriptive, adjust the error text
   * regex but do not remove the test.
   */
  global.fetch = jest.fn().mockResolvedValueOnce({
    ok: false,
    status: 500,
    json: async () => ({ detail: "PubMed fetch failed" }),
  }) as jest.Mock;

  render(<SearchPage />);
  fireEvent.change(screen.getByPlaceholderText(/drug target/i), {
    target: { value: "KRAS G12C" },
  });
  fireEvent.click(screen.getByRole("button", { name: /search/i }));

  expect(await screen.findByText(/error|failed/i)).toBeInTheDocument();
});
