"""Tests for the StarGate failure-classifier qualification flywheel."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "qualify"))

from qualify_classifier import (  # noqa: E402
    build_card,
    digest,
    load_taxonomy,
    parse_proposed_class,
    regex_baseline_predict,
    wilson,
)

CASES = json.loads((ROOT / "qualify" / "classifier_cases.json").read_text())["cases"]
LITERAL = [c for c in CASES if c["id"] <= "fc-08"]
PARAPHRASED = [c for c in CASES if c["id"] >= "fc-09"]


def test_taxonomy_loads_with_patterns():
    taxonomy = load_taxonomy()
    assert len(taxonomy) >= 50
    assert all(pattern.pattern for _, pattern in taxonomy)


def test_regex_baseline_solves_the_literal_cases():
    taxonomy = load_taxonomy()
    solved = sum(1 for case in LITERAL if regex_baseline_predict(case["evidence"], taxonomy) == case["expected_class"])
    assert solved >= 7, f"baseline solved only {solved}/8 literal cases; the case set is mis-authored"


def test_regex_baseline_misses_most_paraphrased_cases():
    taxonomy = load_taxonomy()
    solved = sum(1 for case in PARAPHRASED if regex_baseline_predict(case["evidence"], taxonomy) == case["expected_class"])
    assert solved <= 1, f"baseline solved {solved}/4 paraphrased cases; paraphrases are not semantically hard enough"


def test_parse_proposed_class_handles_production_shapes():
    assert parse_proposed_class('{"proposed_class": "oom_killed", "confidence": 0.9}') == "oom_killed"
    assert parse_proposed_class('Prefix text {"proposed_class": "ceph_health_warning"} suffix') == "ceph_health_warning"
    assert parse_proposed_class("not json at all") is None
    assert parse_proposed_class('{"unrelated": true}') is None


def test_wilson_bounds():
    low, high = wilson(9, 20)
    assert low <= 0.45 <= high
    assert low < high


def test_card_emission_validates_against_pinned_schema(tmp_path):
    rows = []
    trials = 2
    systems = {"taxonomy-regex-baseline": "OFFLINE", "model-a": "GREEN"}
    for system_id, mode in systems.items():
        for case in CASES[:4]:
            for trial in range(1, trials + 1):
                correct = mode == "GREEN" or case["id"] in ("fc-01", "fc-02")
                rows.append({"system_id": system_id, "case_id": case["id"], "trial": trial,
                             "expected": case["expected_class"],
                             "predicted": case["expected_class"] if correct else "wrong",
                             "outcome": "completed", "quality": "GREEN" if correct else "RED",
                             "latency": 0.1, "fingerprint": None, "model_calls": 0})
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "trials.jsonl").write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
    (run_dir / "run.json").write_text(json.dumps({
        "schema_version": "stargate.classifier-qualification/v1",
        "cases_sha256": digest(CASES), "prompt_id": "classify",
        "models": ["model-a"], "trials_per_case": trials,
        "finished_at": "2026-10-21T00:00:00+00:00"}) + "\n")

    card = build_card(run_dir)
    by_id = {s["system_id"]: s for s in card["systems"]}
    assert by_id["taxonomy-regex-baseline"]["evidence_label"] == "OFFLINE"
    assert by_id["model-a"]["evidence_label"] == "LIVE"
    assert card["verdict"]["authorizes_execution"] is False
    body = {k: v for k, v in card.items() if k != "card_sha256"}
    assert digest(body) == card["card_sha256"]


def test_card_refuses_inconsistent_repetition(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rows = [{"system_id": "m", "case_id": "fc-01", "trial": 1, "expected": "x", "predicted": "x",
             "outcome": "completed", "quality": "GREEN", "latency": 0.1, "model_calls": 1}]
    (run_dir / "trials.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (run_dir / "run.json").write_text(json.dumps({
        "schema_version": "stargate.classifier-qualification/v1",
        "cases_sha256": digest(CASES), "prompt_id": "classify",
        "models": ["m"], "trials_per_case": 3,
        "finished_at": "2026-10-21T00:00:00+00:00"}) + "\n")
    with pytest.raises(ValueError, match="trials per case"):
        build_card(run_dir)
