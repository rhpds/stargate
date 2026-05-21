"""AnarchySubject provision-complete gate — collector, normalizer, rubric pipeline."""

import json
from pathlib import Path

import pytest

from engine.models import StageOutcome
from engine.rubric_evaluator import evaluate_rubric
from engine.rubric_loader import load_rubric
from collectors.babylon.collect_anarchy_state import collect_anarchysubject
from collectors.openshift.collect_resource_state import collect_from_data, collect_from_file
from collectors.openshift.evidence_normalizer import normalize_evidence


RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "platform"
ANARCHY_HEALTHY = Path(__file__).parent.parent / "fixtures" / "oc" / "anarchy-healthy"
ANARCHY_UNHEALTHY = Path(__file__).parent.parent / "fixtures" / "oc" / "anarchy-unhealthy"


def _load(path):
    return json.loads(path.read_text())


class TestCollectAnarchySubject:
    def test_healthy_anarchysubject(self):
        ev = collect_anarchysubject(_load(ANARCHY_HEALTHY / "anarchysubject.json"))
        assert ev.resource_kind == "AnarchySubject"
        assert ev.observed["anarchysubject_exists"] is True
        assert ev.observed["provision_job_succeeded"] is True
        assert ev.observed["state_is_started"] is True
        assert ev.observed["current_state"] == "started"
        assert ev.observed["no_error_conditions"] is True

    def test_unhealthy_anarchysubject(self):
        ev = collect_anarchysubject(_load(ANARCHY_UNHEALTHY / "anarchysubject.json"))
        assert ev.observed["anarchysubject_exists"] is True
        assert ev.observed["provision_job_succeeded"] is False
        assert ev.observed["state_is_started"] is False
        assert ev.observed["current_state"] == "provision-failed"
        assert ev.observed["no_error_conditions"] is False

    def test_v2_list_format(self):
        data = {
            "kind": "AnarchySubject",
            "metadata": {"name": "test-v2", "namespace": "test-ns"},
            "status": {
                "state": "started",
                "towerJobs": {
                    "provision": [
                        {"status": "successful", "completeTimestamp": "2026-05-06T10:00:00Z"}
                    ]
                },
                "conditions": [],
            },
        }
        ev = collect_anarchysubject(data)
        assert ev.observed["provision_job_succeeded"] is True
        assert ev.observed["state_is_started"] is True

    def test_missing_tower_jobs(self):
        data = {
            "kind": "AnarchySubject",
            "metadata": {"name": "test-empty", "namespace": "test-ns"},
            "status": {"state": "provisioning", "towerJobs": {}, "conditions": []},
        }
        ev = collect_anarchysubject(data)
        assert ev.observed["provision_job_succeeded"] is False
        assert ev.observed["state_is_started"] is False


class TestCollectFromDataDispatch:
    def test_anarchysubject_dispatches(self):
        data = _load(ANARCHY_HEALTHY / "anarchysubject.json")
        ev = collect_from_data(data)
        assert ev.resource_kind == "AnarchySubject"

    def test_collect_from_file(self):
        ev = collect_from_file(ANARCHY_HEALTHY / "anarchysubject.json")
        assert ev.resource_kind == "AnarchySubject"
        assert "file:" in ev.source


class TestProvisionNormalizer:
    def test_normalize_healthy(self):
        data = _load(ANARCHY_HEALTHY / "anarchysubject.json")
        ev = collect_anarchysubject(data)
        normalized = normalize_evidence("provision-complete", [ev])
        assert normalized["anarchysubject_exists"] is True
        assert normalized["provision_job_succeeded"] is True
        assert normalized["state_is_started"] is True
        assert normalized["no_error_conditions"] is True

    def test_normalize_unhealthy(self):
        data = _load(ANARCHY_UNHEALTHY / "anarchysubject.json")
        ev = collect_anarchysubject(data)
        normalized = normalize_evidence("provision-complete", [ev])
        assert normalized["anarchysubject_exists"] is True
        assert normalized["provision_job_succeeded"] is False
        assert normalized["state_is_started"] is False

    def test_normalize_empty(self):
        normalized = normalize_evidence("provision-complete", [])
        assert normalized["anarchysubject_exists"] is False


class TestProvisionRubricPipeline:
    def test_healthy_passes(self):
        rubric = load_rubric(RUBRIC_DIR / "provision-complete.yaml")
        data = _load(ANARCHY_HEALTHY / "anarchysubject.json")
        ev = collect_anarchysubject(data)
        normalized = normalize_evidence("provision-complete", [ev])
        result = evaluate_rubric(rubric, normalized)
        assert result.outcome == StageOutcome.PASS
        assert result.timeout_seconds == 120

    def test_unhealthy_fails_with_provision_failed(self):
        rubric = load_rubric(RUBRIC_DIR / "provision-complete.yaml")
        data = _load(ANARCHY_UNHEALTHY / "anarchysubject.json")
        ev = collect_anarchysubject(data)
        normalized = normalize_evidence("provision-complete", [ev])
        result = evaluate_rubric(rubric, normalized)
        assert result.outcome == StageOutcome.FAIL
        assert result.failure_class == "provision_failed"

    def test_missing_fails_with_anarchysubject_missing(self):
        rubric = load_rubric(RUBRIC_DIR / "provision-complete.yaml")
        normalized = normalize_evidence("provision-complete", [])
        result = evaluate_rubric(rubric, normalized)
        assert result.outcome == StageOutcome.FAIL
        assert result.failure_class == "anarchysubject_missing"
