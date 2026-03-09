"""
Eval harness for extract_structured_evidence() against hand-labelled abstracts.

AGENT-CTX: Two tiers of tests:

  [ALWAYS] — schema integrity tests that run on every `make test` invocation.
             These validate that the fixture file itself is internally consistent
             (valid JSON, entries conform to StructuredEvidence schema, IDs are
             unique and sequential). They pass with as few as 1 entry.

  [COVERAGE-GATED] — coverage assertions that require >=20 labelled entries.
                     Automatically skipped (not failed) when the fixture has
                     fewer than 20 entries. Run `make test` after adding all 20
                     entries — these will then execute and verify diversity.

  [LIVE] — accuracy tests that call the real Groq API for each fixture entry and
           compare extracted fields against ground truth. Run with: pytest -m live
           ⚠️ Burns ~20 Groq API calls per run. Do NOT include in make test.
           Accuracy is reported but not asserted — human review is the gate.

AGENT-CTX: The fixture file is backend/tests/fixtures/eval_abstracts.json.
It is structured as {"_schema": {...}, "entries": [...]} so the _schema key
can document the format inside the JSON file itself (JSON has no comment syntax).
The harness always reads data["entries"].

AGENT-CTX: confidence_tier is intentionally absent from fixture expected values.
It is derived deterministically by ConfidenceEngine from evidence_type and is
tested independently in test_confidence.py. Including it in the eval fixture would
duplicate the engine's responsibility and require fixture updates on threshold changes.

AGENT-CTX: Accuracy assertions in the live test are field-by-field but do NOT
assert a minimum accuracy percentage. Accuracy is a human review concern — the
agent cannot determine whether an LLM disagreement is a model error or a labelling
ambiguity. The live test prints a per-entry diff for human inspection.
"""

import json
import pathlib
from typing import Any

import pytest

from backend.models import StructuredEvidence, VALID_EVIDENCE_TYPES

# ── Fixture loading ───────────────────────────────────────────────────────────

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "eval_abstracts.json"

# AGENT-CTX: Coverage gate — tests that require a complete 20-entry fixture
# skip themselves when this threshold is not yet met, rather than failing.
# This keeps `make test` GREEN during the period when the user is building out
# the fixture. The threshold matches the T11 deploy requirement.
_COVERAGE_THRESHOLD = 20


def _load_fixture() -> dict[str, Any]:
    """Load and return the full fixture JSON object."""
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _load_cases() -> list[dict[str, Any]]:
    """Load and return the entries list from the fixture."""
    return _load_fixture()["entries"]


def _skip_if_incomplete(cases: list[dict]) -> None:
    """
    Skip the current test if the fixture has fewer than _COVERAGE_THRESHOLD entries.

    AGENT-CTX: Called at the top of coverage-gated tests. pytest.skip() raises
    internally so no code after this call runs when skipping. The skip message
    tells the user exactly what is needed to make the test run.
    """
    if len(cases) < _COVERAGE_THRESHOLD:
        pytest.skip(
            f"Fixture has {len(cases)} entr{'y' if len(cases) == 1 else 'ies'} — "
            f"add {_COVERAGE_THRESHOLD - len(cases)} more to run coverage checks. "
            f"See backend/tests/fixtures/eval_abstracts.json _schema for format."
        )


# ── Always-on: file integrity ─────────────────────────────────────────────────

def test_fixture_file_exists():
    """
    The fixture file must exist at the expected path.

    AGENT-CTX: This test fails fast if the file is accidentally deleted or if
    the fixtures/ directory is missing from the repo. It is the first check in
    the harness — all other tests depend on the file being loadable.
    """
    assert FIXTURE_PATH.exists(), (
        f"Eval fixture not found at {FIXTURE_PATH}. "
        "Run T4 to create it, or check that backend/tests/fixtures/ is committed."
    )


def test_fixture_is_valid_json():
    """Fixture file must parse as valid JSON without error."""
    try:
        data = _load_fixture()
    except json.JSONDecodeError as e:
        pytest.fail(f"eval_abstracts.json is not valid JSON: {e}")
    assert isinstance(data, dict), "Top-level fixture must be a JSON object"


def test_fixture_has_schema_and_entries_keys():
    """
    Fixture must have both '_schema' and 'entries' top-level keys.

    AGENT-CTX: The fixture is structured as {"_schema": {...}, "entries": [...]}
    rather than a bare array so the _schema key can document the format inline.
    If this structure ever changes, update _load_cases() and this test together.
    """
    data = _load_fixture()
    assert "_schema" in data, "Fixture missing '_schema' key — see format docs"
    assert "entries" in data, "Fixture missing 'entries' key"
    assert isinstance(data["entries"], list), "'entries' must be a JSON array"


def test_fixture_has_at_least_one_entry():
    """Fixture must contain at least the skeleton example entry."""
    cases = _load_cases()
    assert len(cases) >= 1, (
        "Fixture 'entries' array is empty. At minimum the skeleton example entry "
        "must be present. See backend/tests/fixtures/eval_abstracts.json."
    )


def test_fixture_entries_validate_against_structured_evidence_schema():
    """
    Every entry's 'expected' object must pass StructuredEvidence.model_validate().

    AGENT-CTX: This is the primary schema integrity check. It verifies that the
    human-provided labels are themselves valid — correct enum values, no missing
    fields, no invalid sentinel strings. If this test fails after adding entries,
    the labels in the failing entry need to be corrected before the eval harness
    can produce meaningful accuracy results.

    AGENT-CTX: We validate each entry independently and report all failures rather
    than stopping at the first, so the user can fix all label errors in one pass.
    """
    cases = _load_cases()
    failures = []
    for c in cases:
        entry_id = c.get("id", "?")
        if "expected" not in c:
            failures.append(f"  entry id={entry_id}: missing 'expected' key")
            continue
        try:
            StructuredEvidence.model_validate(c["expected"])
        except Exception as e:
            failures.append(f"  entry id={entry_id}: {e}")

    assert not failures, (
        f"{len(failures)} fixture entr{'y' if len(failures) == 1 else 'ies'} "
        f"failed StructuredEvidence validation:\n" + "\n".join(failures)
    )


def test_fixture_entry_ids_are_unique_and_sequential():
    """
    IDs must be unique integers starting at 1 and incrementing by 1.

    AGENT-CTX: Sequential IDs make the live accuracy report easier to read
    (sorted output, easy cross-reference with the JSON file). Non-sequential
    IDs are caught here rather than producing confusing accuracy report output.
    """
    cases = _load_cases()
    ids = [c.get("id") for c in cases]
    expected_ids = list(range(1, len(cases) + 1))
    assert ids == expected_ids, (
        f"Entry IDs are not sequential starting from 1. "
        f"Got: {ids}. Expected: {expected_ids}"
    )


def test_fixture_entries_have_required_top_level_keys():
    """Every entry must have id, title, abstract, and expected keys."""
    cases = _load_cases()
    required = {"id", "title", "abstract", "expected"}
    for c in cases:
        missing = required - c.keys()
        assert not missing, (
            f"Entry id={c.get('id', '?')} is missing required keys: {missing}"
        )


def test_fixture_entries_pmid_is_string_or_null():
    """pmid must be a string (real PMID) or null (synthetic abstract)."""
    cases = _load_cases()
    for c in cases:
        pmid = c.get("pmid")
        assert pmid is None or isinstance(pmid, str), (
            f"Entry id={c.get('id', '?')}: pmid must be a string or null, "
            f"got {type(pmid).__name__!r}"
        )


def test_fixture_expected_has_no_confidence_tier():
    """
    expected must NOT contain confidence_tier.

    AGENT-CTX: confidence_tier is engine-derived and tested in test_confidence.py.
    If it appears in expected, it was added by mistake — remove it from the entry.
    Including it would create a maintenance burden: fixture entries would need
    updating whenever tier thresholds are retuned in confidence.py.
    """
    cases = _load_cases()
    for c in cases:
        expected = c.get("expected", {})
        assert "confidence_tier" not in expected, (
            f"Entry id={c.get('id', '?')}: 'confidence_tier' must not appear in "
            f"expected — it is engine-derived. Remove it from the entry."
        )


# ── Coverage-gated: diversity checks (skip until 20 entries present) ──────────

def test_fixture_covers_all_five_evidence_types():
    """
    At least 2 examples of each EvidenceType value must be present.

    AGENT-CTX: Skipped until fixture reaches _COVERAGE_THRESHOLD entries.
    When 20 entries are added, this test ensures the eval harness has coverage
    across all study design categories and is not biased toward one type.
    """
    cases = _load_cases()
    _skip_if_incomplete(cases)

    type_counts: dict[str, int] = {}
    for c in cases:
        et = c["expected"]["evidence_type"]
        type_counts[et] = type_counts.get(et, 0) + 1

    missing = VALID_EVIDENCE_TYPES - type_counts.keys()
    assert not missing, f"Fixture missing entries for evidence types: {missing}"

    under_covered = {k: v for k, v in type_counts.items() if v < 2}
    assert not under_covered, (
        f"Fixture has fewer than 2 examples for: {under_covered}. "
        "Add more entries for these types."
    )


def test_fixture_covers_all_three_effect_directions():
    """
    At least 1 example of each EffectDirection value must be present.

    AGENT-CTX: Skipped until _COVERAGE_THRESHOLD entries present.
    """
    cases = _load_cases()
    _skip_if_incomplete(cases)

    directions = {c["expected"]["effect_direction"] for c in cases}
    required = {"supports", "contradicts", "neutral"}
    missing = required - directions
    assert not missing, (
        f"Fixture missing examples for effect directions: {missing}. "
        "Add entries that contradict or are neutral."
    )


def test_fixture_has_populated_model_organisms():
    """
    At least 3 entries must have model_organism != 'not reported'.

    AGENT-CTX: Skipped until _COVERAGE_THRESHOLD entries present.
    Tests that the LLM extracts organism names from animal model abstracts.
    """
    cases = _load_cases()
    _skip_if_incomplete(cases)

    populated = [
        c for c in cases if c["expected"]["model_organism"] != "not reported"
    ]
    assert len(populated) >= 3, (
        f"Only {len(populated)} entr{'y' if len(populated) == 1 else 'ies'} have "
        "a populated model_organism. Add animal model entries with explicit organism names."
    )


def test_fixture_has_populated_sample_sizes():
    """
    At least 3 entries must have sample_size != 'not reported'.

    AGENT-CTX: Skipped until _COVERAGE_THRESHOLD entries present.
    Tests that the LLM extracts sample size strings from relevant abstracts.
    """
    cases = _load_cases()
    _skip_if_incomplete(cases)

    populated = [
        c for c in cases if c["expected"]["sample_size"] != "not reported"
    ]
    assert len(populated) >= 3, (
        f"Only {len(populated)} entr{'y' if len(populated) == 1 else 'ies'} have "
        "a populated sample_size. Add entries with explicit sample sizes in the abstract."
    )


# ── Live: accuracy report (requires GROQ_API_KEY + ~20 API calls) ─────────────

@pytest.mark.live
async def test_extraction_accuracy_report():
    """
    Run extract_structured_evidence() on every fixture entry and compare
    against ground truth. Prints a per-entry diff for human review.

    AGENT-CTX: This test does NOT assert a pass/fail accuracy threshold.
    Accuracy is a human review gate — the agent cannot determine whether an
    LLM disagreement is a model error or a labelling ambiguity. The test
    reports results for inspection and marks itself as PASSED regardless of
    accuracy, so the CI pipeline is not blocked by expected LLM variance.

    AGENT-CTX: ⚠️ Burns one Groq API call per fixture entry (~20 calls total).
    Run only when explicitly asked: pytest -m live tests/test_eval.py
    Do NOT add this to make test or make test-live without considering quota.

    AGENT-CTX: Only evidence_type and effect_direction are checked for accuracy.
    model_organism and sample_size are string fields with many valid phrasings —
    an exact string match would produce false negatives (e.g. "mouse" vs "mice").
    Future slices may add fuzzy matching or normalisation for these fields.
    """
    from backend.llm import extract_structured_evidence

    cases = _load_cases()
    if not cases:
        pytest.skip("No fixture entries — add abstracts before running accuracy test.")

    fields_to_check = ["evidence_type", "effect_direction"]
    results: list[dict] = []

    for c in cases:
        result = await extract_structured_evidence(c["title"], c["abstract"])
        entry_result = {
            "id": c["id"],
            "title": c["title"][:60] + ("…" if len(c["title"]) > 60 else ""),
        }
        for field in fields_to_check:
            got = getattr(result, field)
            expected = c["expected"][field]
            entry_result[field] = {"expected": expected, "got": got, "match": got == expected}
        results.append(entry_result)

    # ── Print report ──
    print(f"\n{'='*70}")
    print(f"EVAL ACCURACY REPORT  ({len(cases)} entries)")
    print(f"{'='*70}")

    for field in fields_to_check:
        correct = sum(1 for r in results if r[field]["match"])
        pct = correct / len(results) * 100 if results else 0
        print(f"\n{field}: {correct}/{len(results)} correct ({pct:.0f}%)")

        for r in results:
            info = r[field]
            status = "OK  " if info["match"] else "FAIL"
            print(f"  [{status}] id={r['id']:2d} | expected={info['expected']!r:20s} | got={info['got']!r}")

    print(f"\n{'='*70}")
    print("Review FAILs above — determine if error is model or labelling ambiguity.")
    print(f"{'='*70}\n")

    # AGENT-CTX: No assertion here — see docstring. The test always passes so the
    # accuracy report is available even when the model disagrees with some labels.
    # Failing this test would block make test-live for an accuracy issue that might
    # be a labelling disagreement, not a code bug.
