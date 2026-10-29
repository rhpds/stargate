"""Tests for the lifecycle qualification case set and harness support.

The lifecycle set (qualify/lifecycle_cases.json) qualifies the classifier on
provisioning and reclamation outcomes: cases 1-7 are literal (baseline-
solvable from the lifecycle taxonomy patterns), cases 8-12 paraphrase the
same outcomes so semantic classification is required.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "qualify"))

from qualify_classifier import (  # noqa: E402
    CASES_PATH,
    ROOT as QROOT,
    _cases_id,
    build_card,
    load_taxonomy,
    regex_baseline_predict,
    run_qualification,
)

LIFECYCLE_PATH = QROOT / "qualify" / "lifecycle_cases.json"
CASES = json.loads(LIFECYCLE_PATH.read_text())["cases"]
LITERAL = [c for c in CASES if c["id"] <= "lc-07"]
PARAPHRASED = [c for c in CASES if c["id"] >= "lc-08"]


def test_lifecycle_cases_load_with_expected_shape():
    assert len(CASES) == 12
    assert len(LITERAL) == 7 and len(PARAPHRASED) == 5
    ids = [c["id"] for c in CASES]
    assert len(set(ids)) == len(ids)
    assert all(c.get("evidence") and c.get("expected_class") for c in CASES)


def test_lifecycle_expected_classes_are_taxonomy_members():
    taxonomy_names = {name for name, _ in load_taxonomy()}
    missing = {c["expected_class"] for c in CASES} - taxonomy_names
    assert not missing, f"expected classes missing from taxonomy: {missing}"


def test_regex_baseline_solves_the_literal_lifecycle_cases():
    taxonomy = load_taxonomy()
    solved = sum(
        1 for c in LITERAL
        if regex_baseline_predict(c["evidence"], taxonomy) == c["expected_class"]
    )
    assert solved >= 6, f"baseline solved only {solved}/7 literal lifecycle cases"


def test_regex_baseline_misses_paraphrased_lifecycle_cases():
    taxonomy = load_taxonomy()
    solved = sum(
        1 for c in PARAPHRASED
        if regex_baseline_predict(c["evidence"], taxonomy) == c["expected_class"]
    )
    assert solved <= 1, f"baseline solved {solved}/5 paraphrased lifecycle cases"


def test_cases_id_mapping_preserves_historical_default():
    assert _cases_id(CASES_PATH) == "failure"  # original frozen set
    assert _cases_id(LIFECYCLE_PATH) == "lifecycle"


def test_offline_baseline_run_and_card_emission_with_lifecycle_cases(tmp_path):
    """A baseline-only run (no models, no API key) on the lifecycle set must
    produce a schema-valid card carrying the lifecycle construct."""
    run_dir = tmp_path / "lifecycle-run"
    run = run_qualification(
        [], trials=2, output_dir=run_dir, context_mode="production",
        cases_path=LIFECYCLE_PATH,
    )
    assert run["cases_id"] == "lifecycle"
    rows = [json.loads(line) for line in (run_dir / "trials.jsonl").read_text().splitlines() if line.strip()]
    assert rows and all(r["system_id"] == "taxonomy-regex-baseline" for r in rows)

    card = build_card(run_dir)
    assert card["evaluation"]["source_id"] == "stargate-lifecycle-classification-production"
    assert "lifecycle" in card["construct"]["statement"].lower()
    baseline = next(s for s in card["systems"] if s["system_id"] == "taxonomy-regex-baseline")
    assert baseline["single_attempt_rate"]["passed"] >= 12  # ≥6/7 literal × 2 trials
    assert card["verdict"]["authorizes_execution"] is False


def test_card_emission_without_cases_id_keeps_historical_source_id(tmp_path):
    """Old run.json files (pre --cases) still emit the historical source_id."""
    rows = []
    for case in CASES[:2]:
        for trial in (1, 2):
            rows.append({"system_id": "taxonomy-regex-baseline", "case_id": case["id"],
                         "trial": trial, "expected": case["expected_class"],
                         "predicted": case["expected_class"], "outcome": "completed",
                         "quality": "GREEN", "latency": 0.0, "model_calls": 0})
    run_dir = tmp_path / "old-run"
    run_dir.mkdir()
    (run_dir / "trials.jsonl").write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
    (run_dir / "run.json").write_text(json.dumps({
        "schema_version": "stargate.classifier-qualification/v1",
        "cases_sha256": "a" * 64, "prompt_id": "classify",
        "models": [], "trials_per_case": 2,
        "finished_at": "2026-10-21T00:00:00+00:00"}) + "\n")
    card = build_card(run_dir)
    assert card["evaluation"]["source_id"] == "stargate-failure-classification-production"
