"""Observed failure, unobserved checks and automation completion stay distinct."""
from pathlib import Path

import pytest

from collectors.babylon.collect_anarchy_state import collect_anarchysubject
from collectors.openshift.collect_resource_state import CollectedEvidence
from collectors.openshift.evidence_normalizer import normalize_evidence
from engine.models import StageOutcome
from engine.rubric_evaluator import evaluate_rubric
from engine.rubric_loader import load_rubric

RUBRICS = Path(__file__).resolve().parents[1] / "rubrics" / "platform"


def topology():
    return [
        CollectedEvidence("Service", "example", "example", {"service_exists": True}),
        CollectedEvidence("Route", "example", "example", {"route_exists": True, "admitted": True}),
        CollectedEvidence("Endpoints", "example", "example", {
            "service_has_ready_endpoints": True, "ready_endpoint_count": 1,
        }),
    ]


def subject(jobs):
    return collect_anarchysubject({
        "metadata": {"name": "example", "namespace": "example"},
        "status": {"state": "started", "towerJobs": {"provision": jobs}},
    })


def test_endpoints_do_not_prove_http_success():
    evidence = normalize_evidence("route-ready", topology())
    assert evidence["health_endpoint_returns_200"] is None
    result = evaluate_rubric(load_rubric(RUBRICS / "route-ready.yaml"), evidence)
    assert result.outcome != StageOutcome.PASS
    assert result.failure_class is None


def test_unrun_smoke_test_is_indeterminate_not_failure():
    evidence = normalize_evidence("smoke-test-ready", topology())
    assert evidence["smoke_test_passed"] is None
    assert evidence["expected_response_received"] is None
    result = evaluate_rubric(load_rubric(RUBRICS / "smoke-test-ready.yaml"), evidence)
    assert result.outcome == StageOutcome.INDETERMINATE
    assert result.failure_class is None
    assert any(c.passed is None for c in result.criteria_results)


@pytest.mark.parametrize("status", ["failed", "error", "canceled", "cancelled"])
@pytest.mark.parametrize("as_list", [False, True])
def test_failed_completed_job_is_not_success(status, as_list):
    job = {"status": status, "completeTimestamp": "2026-01-01T00:00:00Z"}
    collected = subject([job] if as_list else job)
    assert collected.observed["provision_job_succeeded"] is False
    result = evaluate_rubric(load_rubric(RUBRICS / "provision-complete.yaml"),
                             normalize_evidence("provision-complete", [collected]))
    assert result.outcome == StageOutcome.FAIL
    assert result.failure_class == "provision_failed"


@pytest.mark.parametrize("job", [
    {"completeTimestamp": "2026-01-01T00:00:00Z"},
    {"status": "running"},
])
def test_timestamp_only_or_running_job_is_unverified(job):
    collected = subject(job)
    assert collected.observed["provision_job_succeeded"] is None
    result = evaluate_rubric(load_rubric(RUBRICS / "provision-complete.yaml"),
                             normalize_evidence("provision-complete", [collected]))
    assert result.outcome == StageOutcome.INDETERMINATE
    assert result.failure_class is None


def test_ambiguous_job_history_does_not_pick_a_success():
    collected = subject([{"status": "successful"}, {"status": "failed"}])
    assert collected.observed["provision_job_succeeded"] is None


@pytest.mark.parametrize("passed,expected", [(True, StageOutcome.PASS), (False, StageOutcome.FAIL)])
def test_observed_smoke_results_still_classify(passed, expected):
    evidence = {"route_reachable": True, "smoke_test_passed": passed,
                "expected_response_received": passed, "response_time_acceptable": True}
    result = evaluate_rubric(load_rubric(RUBRICS / "smoke-test-ready.yaml"), evidence)
    assert result.outcome == expected
    assert result.failure_class == (None if passed else "smoke_test_failed")


def test_known_failure_not_hidden_by_an_unobserved_optional_check():
    evidence = normalize_evidence("route-ready", topology())
    evidence.update(service_has_ready_endpoints=False, ready_endpoint_count=0)
    result = evaluate_rubric(load_rubric(RUBRICS / "route-ready.yaml"), evidence)
    assert result.outcome == StageOutcome.FAIL
    assert result.failure_class == "service_has_no_endpoints"


@pytest.mark.parametrize("failure_position", ["entry_before", "entry_after", "exit"])
def test_known_required_failure_wins_over_unknown_entry(failure_position):
    rubric = load_rubric(RUBRICS / "route-ready.yaml")
    if failure_position != "exit":
        entries = [rubric.entry_criteria[0], rubric.exit_criteria[0]]
        if failure_position == "entry_before":
            entries.reverse()
        rubric = rubric.model_copy(update={"entry_criteria": entries, "exit_criteria": []})
    result = evaluate_rubric(rubric, {
        "service_exists": None,
        "route_exists": False,
        "service_has_ready_endpoints": True,
        "health_endpoint_returns_200": None,
    })
    assert result.outcome == StageOutcome.FAIL
    assert result.failure_class == "route_missing"
    assert any(c.name == "route_exists" and c.passed is False for c in result.criteria_results)


def test_api_keeps_indeterminate_pending_and_emits_no_failure(client, monkeypatch):
    from api.routers import runs
    emitted = []
    monkeypatch.setattr(runs._event_bus, "emit", emitted.append)
    assert client.post("/runs", json={
        "run_id": "unobserved-run", "demo_id": "example", "namespace": "example",
        "requested_by": "test-user", "rubric_version": "v0.1.0",
    }).status_code == 201
    assert client.post("/runs/unobserved-run/stages/smoke-test-ready/start").status_code == 201
    response = client.post("/runs/unobserved-run/stages/smoke-test-ready/evaluate", json={
        "evidence": normalize_evidence("smoke-test-ready", topology()),
    })
    assert response.status_code == 200
    assert response.json()["outcome"] == "indeterminate"
    assert response.json()["failure_class"] is None
    assert any(c["passed"] is None for c in response.json()["criteria"])
    report = client.get("/runs/unobserved-run/report").json()
    assert report["passed"] == 0
    assert report["stages"][0]["status"] == "pending"
    assert [event.event_type for event in emitted] == ["evaluation.indeterminate"]


@pytest.mark.parametrize("outcomes,expected", [
    (["indeterminate"], "indeterminate"),
    (["pass", "indeterminate"], "indeterminate"),
    (["fail", "indeterminate"], "fail"),
    (["pass"], "pass"),
    ([], "indeterminate"),
])
def test_scanner_does_not_recover_on_unobserved_results(monkeypatch, outcomes, expected):
    from cli.worker import ClusterWorker
    worker = ClusterWorker("synthetic", "/not-used", api_url="http://not-used")
    worker.state.all_sandbox_namespaces = ["example"]
    worker.state.ns_outcomes["example"] = "fail"
    monkeypatch.setattr(worker, "_get_lab_mappings", dict)
    monkeypatch.setattr(worker, "_collect_namespace", lambda *a, **kw: {
        "results": [{"outcome": outcome} for outcome in outcomes],
    })
    result = worker._tier3_namespaces()
    assert worker.state.ns_outcomes["example"] == expected
    if expected != "pass":
        assert not any(c["direction"] == "recovered" for c in result["outcome_changes"])


def test_unobserved_entry_is_not_classified_as_failure():
    result = evaluate_rubric(load_rubric(RUBRICS / "smoke-test-ready.yaml"), {
        "route_reachable": None, "smoke_test_passed": None,
        "expected_response_received": None, "response_time_acceptable": None,
    })
    assert result.outcome == StageOutcome.INDETERMINATE
    assert result.failure_class is None


def test_cli_persistence_preserves_normalized_unknowns(monkeypatch):
    from unittest.mock import MagicMock

    from cli import api_client
    from cli.stargate import _persist_to_api
    client = MagicMock()
    client.health.return_value = True
    client.create_run.return_value = {"run_id": "synthetic"}
    monkeypatch.setattr(api_client, "StarGateClient", lambda *a: client)
    _persist_to_api("http://not-used", "synthetic", "synthetic", None, None,
                    topology(), [{"stage_id": "smoke-test-ready", "outcome": "indeterminate"}], "json")
    sent = client.evaluate_stage.call_args.kwargs["evidence"]
    assert sent["smoke_test_passed"] is None
    assert sent["expected_response_received"] is None
