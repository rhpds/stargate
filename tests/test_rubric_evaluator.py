"""Tests for rubric evaluation — deterministic pass/fail/warn outcomes."""

from pathlib import Path

import pytest
import yaml

from engine.models import Rubric, RubricCriterion, StageOutcome
from engine.rubric_evaluator import evaluate_rubric
from engine.rubric_loader import load_rubric


# --- Inline rubric for unit tests ---

def make_route_rubric() -> Rubric:
    return Rubric(
        id="route-ready",
        version="v0.1.0",
        stage="route-ready",
        entry_criteria=[RubricCriterion(name="service_exists", required=True)],
        exit_criteria=[
            RubricCriterion(name="route_exists", required=True),
            RubricCriterion(name="service_has_ready_endpoints", required=True),
            RubricCriterion(name="health_endpoint_returns_200", required=True),
        ],
        failure_classes={
            "service_has_no_endpoints": {
                "when": ["service_exists == true", "ready_endpoint_count == 0"],
                "recommended_action": "inspect_service_selector_and_pod_labels",
            },
        },
    )


def make_namespace_rubric() -> Rubric:
    return Rubric(
        id="namespace-ready",
        version="v0.1.0",
        stage="namespace-ready",
        exit_criteria=[RubricCriterion(name="namespace_exists", required=True)],
        failure_classes={
            "namespace_missing": {
                "when": ["namespace_exists == false"],
                "recommended_action": "create_namespace",
            },
        },
    )


def make_smoke_rubric() -> Rubric:
    return Rubric(
        id="smoke-test-ready",
        version="v0.1.0",
        stage="smoke-test-ready",
        entry_criteria=[RubricCriterion(name="route_reachable", required=True)],
        exit_criteria=[
            RubricCriterion(name="smoke_test_passed", required=True),
            RubricCriterion(name="expected_response_received", required=True),
            RubricCriterion(name="response_time_acceptable", required=False),
        ],
    )


# --- Pass tests ---

class TestEvaluatePass:
    def test_namespace_pass(self):
        result = evaluate_rubric(make_namespace_rubric(), {"namespace_exists": True})
        assert result.outcome == StageOutcome.PASS
        assert result.failure_class is None

    def test_route_pass(self):
        evidence = {
            "service_exists": True,
            "route_exists": True,
            "service_has_ready_endpoints": True,
            "health_endpoint_returns_200": True,
            "ready_endpoint_count": 1,
        }
        result = evaluate_rubric(make_route_rubric(), evidence)
        assert result.outcome == StageOutcome.PASS

    def test_smoke_pass(self):
        evidence = {
            "route_reachable": True,
            "smoke_test_passed": True,
            "expected_response_received": True,
            "response_time_acceptable": True,
        }
        result = evaluate_rubric(make_smoke_rubric(), evidence)
        assert result.outcome == StageOutcome.PASS


# --- Fail tests ---

class TestEvaluateFail:
    def test_namespace_fail(self):
        result = evaluate_rubric(make_namespace_rubric(), {"namespace_exists": False})
        assert result.outcome == StageOutcome.FAIL
        assert result.failure_class == "namespace_missing"

    def test_namespace_fail_missing_evidence(self):
        result = evaluate_rubric(make_namespace_rubric(), {})
        assert result.outcome == StageOutcome.FAIL

    def test_route_fail_no_endpoints(self):
        evidence = {
            "service_exists": True,
            "route_exists": True,
            "service_has_ready_endpoints": False,
            "health_endpoint_returns_200": False,
            "ready_endpoint_count": 0,
        }
        result = evaluate_rubric(make_route_rubric(), evidence)
        assert result.outcome == StageOutcome.FAIL
        assert result.failure_class == "service_has_no_endpoints"

    def test_route_fail_entry_criterion_not_met(self):
        evidence = {
            "service_exists": False,
            "route_exists": True,
            "service_has_ready_endpoints": True,
            "health_endpoint_returns_200": True,
        }
        result = evaluate_rubric(make_route_rubric(), evidence)
        assert result.outcome == StageOutcome.FAIL
        assert "Entry criterion" in result.message

    def test_smoke_fail_entry_not_met(self):
        evidence = {
            "route_reachable": False,
            "smoke_test_passed": True,
            "expected_response_received": True,
        }
        result = evaluate_rubric(make_smoke_rubric(), evidence)
        assert result.outcome == StageOutcome.FAIL


# --- Warn tests ---

class TestEvaluateWarn:
    def test_smoke_warn_optional_fail(self):
        evidence = {
            "route_reachable": True,
            "smoke_test_passed": True,
            "expected_response_received": True,
            "response_time_acceptable": False,
        }
        result = evaluate_rubric(make_smoke_rubric(), evidence)
        assert result.outcome == StageOutcome.WARN
        assert "response_time_acceptable" in result.message


# --- Criteria results tracking ---

class TestCriteriaResults:
    def test_pass_tracks_all_criteria(self):
        evidence = {
            "service_exists": True,
            "route_exists": True,
            "service_has_ready_endpoints": True,
            "health_endpoint_returns_200": True,
        }
        result = evaluate_rubric(make_route_rubric(), evidence)
        assert len(result.criteria_results) == 4
        assert all(c.passed for c in result.criteria_results)

    def test_fail_tracks_failed_criteria(self):
        evidence = {
            "service_exists": True,
            "route_exists": True,
            "service_has_ready_endpoints": False,
            "health_endpoint_returns_200": False,
        }
        result = evaluate_rubric(make_route_rubric(), evidence)
        failed = [c for c in result.criteria_results if not c.passed]
        assert len(failed) >= 1


# --- Fixture-based tests ---

class TestFixtureRuns:
    FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
    RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "platform"

    def _load_rubric_map(self) -> dict[str, Rubric]:
        rubrics = {}
        for path in self.RUBRIC_DIR.glob("*.yaml"):
            r = load_rubric(path)
            rubrics[r.stage] = r
        return rubrics

    def _load_fixture(self, name: str) -> dict:
        path = self.FIXTURE_DIR / name
        return yaml.safe_load(path.read_text())

    @pytest.mark.skipif(
        not (Path(__file__).parent.parent / "rubrics" / "platform").exists(),
        reason="Rubric files not present",
    )
    def test_successful_run_all_pass(self):
        rubrics = self._load_rubric_map()
        fixture = self._load_fixture("successful-container-run.yaml")
        for stage_data in fixture["stages"]:
            stage_id = stage_data["stage_id"]
            rubric = rubrics[stage_id]
            result = evaluate_rubric(rubric, stage_data["evidence"])
            assert result.outcome.value == stage_data["expected_outcome"], (
                f"Stage {stage_id}: expected {stage_data['expected_outcome']}, got {result.outcome.value}"
            )

    @pytest.mark.skipif(
        not (Path(__file__).parent.parent / "rubrics" / "platform").exists(),
        reason="Rubric files not present",
    )
    def test_failed_route_run(self):
        rubrics = self._load_rubric_map()
        fixture = self._load_fixture("failed-route-run.yaml")
        for stage_data in fixture["stages"]:
            stage_id = stage_data["stage_id"]
            rubric = rubrics[stage_id]
            result = evaluate_rubric(rubric, stage_data["evidence"])
            assert result.outcome.value == stage_data["expected_outcome"], (
                f"Stage {stage_id}: expected {stage_data['expected_outcome']}, got {result.outcome.value}"
            )
            if "expected_failure_class" in stage_data:
                assert result.failure_class == stage_data["expected_failure_class"], (
                    f"Stage {stage_id}: expected failure class {stage_data['expected_failure_class']}, "
                    f"got {result.failure_class}"
                )

    @pytest.mark.skipif(
        not (Path(__file__).parent.parent / "rubrics" / "platform").exists(),
        reason="Rubric files not present",
    )
    def test_warn_smoke_test_run(self):
        rubrics = self._load_rubric_map()
        fixture = self._load_fixture("warn-smoke-test-run.yaml")
        for stage_data in fixture["stages"]:
            stage_id = stage_data["stage_id"]
            rubric = rubrics[stage_id]
            result = evaluate_rubric(rubric, stage_data["evidence"])
            assert result.outcome.value == stage_data["expected_outcome"], (
                f"Stage {stage_id}: expected {stage_data['expected_outcome']}, got {result.outcome.value}"
            )
