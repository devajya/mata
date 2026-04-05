/**
 * Tests for the ChainPanel chain metadata panel.
 */

import { render, screen, fireEvent } from "@testing-library/react";
import { ChainPanel } from "../components/ChainPanel";
import { ChainMeta, EvidenceItem } from "../types";

const REVIEW: EvidenceItem = {
  pmid:             "55544433",
  title:            "Systematic Review of KRAS Inhibitors",
  abstract:         "A comprehensive review.",
  evidence_type:    "review",
  effect_direction: "neutral",
  model_organism:   "not reported",
  sample_size:      "not reported",
  confidence_tier:  "low",
  layer:            -1,
  publication_year:  2021,
};

const CHAIN_WITH_REVIEW: ChainMeta = {
  id:       "chain-0",
  label:    "Evidence Chain 1",
  color:    "#1a6faf",
  nodeIds:  ["evidence-aaa", "evidence-bbb"],
  edgeIds:  [],
  review:   REVIEW,
};

const CHAIN_NO_REVIEW: ChainMeta = {
  ...CHAIN_WITH_REVIEW,
  review: null,
};

test("renders null when chain is null (panel closed)", () => {
  const { container } = render(<ChainPanel chain={null} onClose={() => {}} />);
  expect(container.firstChild).toBeNull();
});

test("renders chain label when chain is provided", () => {
  render(<ChainPanel chain={CHAIN_WITH_REVIEW} onClose={() => {}} />);
  expect(screen.getByText("Evidence Chain 1")).toBeInTheDocument();
});

test("shows review title and year when review is present", () => {
  render(<ChainPanel chain={CHAIN_WITH_REVIEW} onClose={() => {}} />);
  expect(screen.getByText("Systematic Review of KRAS Inhibitors")).toBeInTheDocument();
  expect(screen.getByText("2021")).toBeInTheDocument();
});

test("shows fallback text when no review is associated", () => {
  render(<ChainPanel chain={CHAIN_NO_REVIEW} onClose={() => {}} />);
  expect(screen.getByText(/no review paper/i)).toBeInTheDocument();
});

test("shows node count", () => {
  render(<ChainPanel chain={CHAIN_WITH_REVIEW} onClose={() => {}} />);
  expect(screen.getByText(/2 evidence nodes/i)).toBeInTheDocument();
});

test("calls onClose when close button is clicked", () => {
  const onClose = jest.fn();
  render(<ChainPanel chain={CHAIN_WITH_REVIEW} onClose={onClose} />);
  fireEvent.click(screen.getByLabelText(/close chain panel/i));
  expect(onClose).toHaveBeenCalledTimes(1);
});
