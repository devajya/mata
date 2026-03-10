/**
 * Tests for the SearchPage component.
 *
 * AGENT-CTX: Test tiers:
 *   [STATIC] — no fetch mock, component renders without interaction
 *   [MOCK]   — global.fetch is replaced with a jest.fn() returning controlled data
 *
 * All tests use mocked fetch only — no live API calls, no @live patterns.
 * The component is tested in isolation from the backend.
 *
 * AGENT-CTX: Walking-skeleton tests (1–5) are preserved with their original
 * assertions. The existing mock data has been updated to include all Milestone 1
 * fields (effect_direction, model_organism, sample_size, confidence_tier) so the
 * tests are TypeScript-clean and do not rely on undefined-fallback rendering.
 *
 * AGENT-CTX: New tests (6–10) cover the Milestone 1 structured card fields:
 *   6. confidence_tier badge renders
 *   7. effect_direction text renders
 *   8. model_organism row hidden when "not reported"
 *   9. model_organism row shown when populated
 *  10. sample_size row hidden when "not reported"
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import SearchPage from "../app/page";
import { EvidenceItem } from "../types";

// ── Shared fixtures ───────────────────────────────────────────────────────────

/**
 * AGENT-CTX: BASE_MOCK_ITEM is the canonical full EvidenceItem used across tests.
 * All nine fields are present — this is the shape the real API returns after T6.
 * Tests that need different field values build on this via object spread ({...BASE_MOCK_ITEM, ...}).
 *
 * Defaults for optional string fields are "not reported" so those rows do NOT render,
 * keeping them invisible to assertions that target other elements. Tests that specifically
 * verify optional field rendering override these defaults explicitly.
 */
const BASE_MOCK_ITEM: EvidenceItem = {
  pmid:             "12345678",
  title:            "Sotorasib in KRAS G12C NSCLC",
  abstract:         "Phase III trial showing progression-free survival benefit.",
  evidence_type:    "clinical trial",
  effect_direction: "supports",
  model_organism:   "not reported",
  sample_size:      "not reported",
  confidence_tier:  "high",
};

/**
 * AGENT-CTX: mockFetch replaces global.fetch with a jest.fn() that resolves once
 * with the given items. Called inside each test that needs fetch results.
 * jest.resetAllMocks() in beforeEach ensures no cross-test pollution.
 */
function mockFetch(items: EvidenceItem[]): void {
  global.fetch = jest.fn().mockResolvedValueOnce({
    ok: true,
    json: async () => ({ query: "KRAS G12C", results: items }),
  }) as jest.Mock;
}

/**
 * AGENT-CTX: submitSearch drives the form: sets input value and clicks the button.
 * Reused across every test that needs results to appear. Value defaults to "KRAS G12C"
 * since the query string itself is not under test in most cases.
 */
function submitSearch(query = "KRAS G12C"): void {
  fireEvent.change(screen.getByPlaceholderText(/drug target/i), {
    target: { value: query },
  });
  fireEvent.click(screen.getByRole("button", { name: /search/i }));
}

// ── Hooks ──────────────────────────────────────────────────────────────────────

// AGENT-CTX: resetAllMocks between tests — prevents a resolved fetch in one test
// from leaking into a later test that expects a pending or failed fetch.
beforeEach(() => {
  jest.resetAllMocks();
});

// ── Walking-skeleton tests (preserved from T7) ────────────────────────────────

test("renders search input with correct placeholder", () => {
  /**
   * AC: Input field accepts a target name.
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

test("shows loading state while fetching", async () => {
  /**
   * AC: App shows loading state while waiting for results.
   * AGENT-CTX: Mock fetch hangs indefinitely to hold the loading state visible.
   * The loading indicator must use text matching /loading/i — if you replace it
   * with a CSS-only spinner, add an aria-label and update this assertion.
   */
  global.fetch = jest.fn(() => new Promise(() => {})) as jest.Mock;

  render(<SearchPage />);
  submitSearch();

  expect(await screen.findByText(/loading/i)).toBeInTheDocument();
});

test("renders result list with title and evidence type after fetch", async () => {
  /**
   * AC: Frontend renders a list of results with title + evidence type badge.
   * AGENT-CTX: Mock returns 10 identical items to keep the test deterministic.
   * All Milestone 1 fields are included in the mock so the component renders
   * the full card structure without relying on undefined-fallback paths.
   * The assertions only check title and evidence_type counts — unchanged from T7.
   */
  const mockResults: EvidenceItem[] = Array(10).fill({ ...BASE_MOCK_ITEM });

  mockFetch(mockResults);
  render(<SearchPage />);
  submitSearch();

  await waitFor(() => {
    expect(screen.getAllByText("Sotorasib in KRAS G12C NSCLC")).toHaveLength(10);
  });

  // Each result must show the evidence type label exactly.
  // AGENT-CTX: getAllByText("clinical trial") targets the evidence_type badge span.
  // This still returns exactly 10 because the confidence_tier badge renders "high",
  // not "clinical trial" — the two badge texts are distinct.
  expect(screen.getAllByText("clinical trial")).toHaveLength(10);
});

test("shows error message when fetch fails", async () => {
  /**
   * AGENT-CTX: Non-200 response must display an inline error with text matching
   * /error|failed/i. The API detail string "PubMed fetch failed" satisfies this.
   * Do not remove — UX requires a visible error state, not silent failure.
   */
  global.fetch = jest.fn().mockResolvedValueOnce({
    ok: false,
    status: 500,
    json: async () => ({ detail: "PubMed fetch failed" }),
  }) as jest.Mock;

  render(<SearchPage />);
  submitSearch();

  expect(await screen.findByText(/error|failed/i)).toBeInTheDocument();
});

// ── Milestone 1: Structured card field tests ──────────────────────────────────

test("renders confidence_tier badge with correct label", async () => {
  /**
   * AC: Each result card displays confidence_tier.
   * AGENT-CTX: The badge renders the raw tier label ("high" / "medium" / "low")
   * as its text content so getByText() can target it without a test-id.
   * BASE_MOCK_ITEM has confidence_tier="high" — asserting on "high".
   */
  mockFetch([{ ...BASE_MOCK_ITEM, confidence_tier: "high" }]);
  render(<SearchPage />);
  submitSearch();

  expect(await screen.findByText("high")).toBeInTheDocument();
});

test("renders effect_direction with correct value", async () => {
  /**
   * AC: Each result card displays effect_direction.
   * AGENT-CTX: The component renders {item.effect_direction} as plain text
   * (coloured, not a badge) so getByText("supports") finds it.
   * A "Direction:" label precedes it but is a separate span — not part of the
   * found text node. If the label is merged with the value, update this query.
   */
  mockFetch([{ ...BASE_MOCK_ITEM, effect_direction: "supports" }]);
  render(<SearchPage />);
  submitSearch();

  expect(await screen.findByText("supports")).toBeInTheDocument();
});

test("hides model_organism row when value is 'not reported'", async () => {
  /**
   * AC: model_organism field only shown when applicable.
   * AGENT-CTX: The component completely omits the organism <p> row when
   * model_organism === "not reported". queryByText returns null for absent nodes.
   * We assert on "not reported" specifically because the component never renders
   * this sentinel string — finding it would indicate a regression in hiding logic.
   * sample_size is also "not reported" in this mock to ensure neither row renders.
   */
  mockFetch([{ ...BASE_MOCK_ITEM, model_organism: "not reported", sample_size: "not reported" }]);
  render(<SearchPage />);
  submitSearch();

  // Wait for results to render before asserting absence
  await screen.findByText("Sotorasib in KRAS G12C NSCLC");
  expect(screen.queryByText("not reported")).not.toBeInTheDocument();
});

test("shows model_organism row when value is populated", async () => {
  /**
   * AC: model_organism field shows when an organism is present.
   * AGENT-CTX: Using "mouse" as the organism value — distinct from any other
   * text in the component so getByText() finds exactly one node.
   * If the organism label "Organism:" were merged with the value, update this
   * to use a regex or query by a test-id. Currently they are separate spans.
   */
  mockFetch([{ ...BASE_MOCK_ITEM, model_organism: "mouse", evidence_type: "animal model" }]);
  render(<SearchPage />);
  submitSearch();

  expect(await screen.findByText("mouse")).toBeInTheDocument();
});

test("hides sample_size row when value is 'not reported'", async () => {
  /**
   * AC: sample_size field only shown when extractable.
   * AGENT-CTX: Same hiding logic as model_organism — the <p> row is omitted
   * entirely when sample_size === "not reported". model_organism is also
   * "not reported" in this mock so neither optional row renders.
   */
  mockFetch([{ ...BASE_MOCK_ITEM, sample_size: "not reported", model_organism: "not reported" }]);
  render(<SearchPage />);
  submitSearch();

  await screen.findByText("Sotorasib in KRAS G12C NSCLC");
  expect(screen.queryByText("not reported")).not.toBeInTheDocument();
});

test("shows sample_size row when value is populated", async () => {
  /**
   * AC: sample_size field shows when stated in the abstract.
   * AGENT-CTX: Using "n=345" — a realistic value, distinct from all other
   * rendered text. Verifies the Sample: row renders when the sentinel is absent.
   */
  mockFetch([{ ...BASE_MOCK_ITEM, sample_size: "n=345" }]);
  render(<SearchPage />);
  submitSearch();

  expect(await screen.findByText("n=345")).toBeInTheDocument();
});
