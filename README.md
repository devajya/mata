# MATA — Drug Target Evidence Aggregator

MATA helps biopharma researchers quickly assess the evidence chain for a drug target. Type in a target (e.g. "KRAS G12C") and MATA searches PubMed, classifies every abstract by study type and effect, and renders the evidence as an interactive graph — so you can see at a glance where the science is strong and where it breaks down.

**Live app:** [mata-devajyas-projects.vercel.app](https://mata-devajyas-projects.vercel.app)

---

## What you see

Each search returns an interactive evidence chain organised into four layers:

| Layer | What it contains |
|-------|-----------------|
| In Vitro | Cell / biochemical studies |
| Animal Model | Rodent and other preclinical models |
| Human Genetics | GWAS, genetic association studies |
| Early Clinical | Phase I/II trials, clinical observations |

Each node shows the study title, evidence type, effect direction (supports / contradicts / neutral), and a confidence tier (high / medium / low) derived from study design. Clicking a node opens a detail panel with the abstract and a link to the PubMed source.

If a layer has no evidence, it renders as an explicit gap node — the absence of evidence is surfaced, not hidden.

---

## How to use it

1. Enter a drug target in the search box (e.g. `EGFR`, `BRAF V600E`, `PD-L1`)
2. Wait ~5–10 seconds while MATA fetches and classifies abstracts
3. Explore the evidence graph — pan, zoom, click nodes for details
4. Use the chain controls on the left to show/hide evidence chains

---

## Current limitations

- Results are drawn from PubMed abstracts only — no full text, no internal documents
- Classification is done by a small open-source LLM (Llama 3.1 8B via Groq) — expect occasional misclassifications
- The backend runs on Render's free tier: the first request after a period of inactivity may take 30–60 seconds while the server warms up
- Edge connections between nodes are not yet implemented (coming in the next release)
