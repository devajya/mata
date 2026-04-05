/**
 * Tests for the NodeDrawer detail panel.
 */

import { render, screen, fireEvent } from "@testing-library/react";
import { NodeDrawer } from "../components/NodeDrawer";
import { EvidenceItem } from "../types";

const ITEM: EvidenceItem = {
  pmid:             "99887766",
  title:            "BRAF V600E in melanoma",
  abstract:         "A study on BRAF inhibitors.",
  evidence_type:    "clinical trial",
  effect_direction: "supports",
  model_organism:   "not reported",
  sample_size:      "n=200",
  confidence_tier:  "high",
  layer:             3,
  publication_year:  2018,
};

test("renders null when evidence is null (drawer closed)", () => {
  const { container } = render(<NodeDrawer evidence={null} onClose={() => {}} />);
  expect(container.firstChild).toBeNull();
});

test("renders title and PubMed link when evidence is provided", () => {
  render(<NodeDrawer evidence={ITEM} onClose={() => {}} />);
  expect(screen.getByText("BRAF V600E in melanoma")).toBeInTheDocument();
  const link = screen.getByText(/open in pubmed/i);
  expect(link).toHaveAttribute("href", "https://pubmed.ncbi.nlm.nih.gov/99887766/");
});

test("shows sample_size when not 'not reported'", () => {
  render(<NodeDrawer evidence={ITEM} onClose={() => {}} />);
  expect(screen.getByText("n=200")).toBeInTheDocument();
});

test("hides model_organism row when value is 'not reported'", () => {
  render(<NodeDrawer evidence={{ ...ITEM, model_organism: "not reported" }} onClose={() => {}} />);
  expect(screen.queryByText("not reported")).not.toBeInTheDocument();
});

test("calls onClose when close button is clicked", () => {
  const onClose = jest.fn();
  render(<NodeDrawer evidence={ITEM} onClose={onClose} />);
  fireEvent.click(screen.getByLabelText(/close detail panel/i));
  expect(onClose).toHaveBeenCalledTimes(1);
});
