"""Build TDD rubric tests and remediation catalog cross-reference validation."""

from pathlib import Path

import pytest
import yaml

from engine.models import StageOutcome
from engine.rubric_evaluator import evaluate_rubric
from engine.rubric_loader import load_rubric, load_rubrics_from_directory


BUILD_RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "build"
PLATFORM_RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "platform"
CATALOG_PATH = Path(__file__).parent.parent / "remediations" / "catalog.yaml"


class TestBuildRubricLoading:
    def test_load_all_build_rubrics(self):
        rubrics = load_rubrics_from_directory(BUILD_RUBRIC_DIR)
        assert len(rubrics) == 4

    def test_build_rubric_ids(self):
        rubrics = load_rubrics_from_directory(BUILD_RUBRIC_DIR)
        ids = {r.id for r in rubrics}
        assert ids == {"tdd-unit-ready", "tdd-integration-ready", "tdd-contract-ready", "tdd-e2e-ready"}

    def test_all_build_rubrics_have_timeout(self):
        rubrics = load_rubrics_from_directory(BUILD_RUBRIC_DIR)
        for r in rubrics:
            assert r.timeout_seconds is not None, f"Rubric {r.id} missing timeout_seconds"
            assert r.timeout_seconds > 0

    def test_all_build_rubrics_have_exit_criteria(self):
        rubrics = load_rubrics_from_directory(BUILD_RUBRIC_DIR)
        for r in rubrics:
            assert len(r.exit_criteria) > 0, f"Rubric {r.id} has no exit criteria"

    def test_all_build_rubrics_have_failure_classes(self):
        rubrics = load_rubrics_from_directory(BUILD_RUBRIC_DIR)
        for r in rubrics:
            assert len(r.failure_classes) > 0, f"Rubric {r.id} has no failure classes"


class TestBuildRubricEvaluation:
    def test_unit_ready_pass(self):
        rubric = load_rubric(BUILD_RUBRIC_DIR / "tdd-unit-ready.yaml")
        result = evaluate_rubric(rubric, {
            "unit_tests_exist": True,
            "unit_tests_pass": True,
            "coverage_above_threshold": True,
        })
        assert result.outcome == StageOutcome.PASS

    def test_unit_ready_fail_no_tests(self):
        rubric = load_rubric(BUILD_RUBRIC_DIR / "tdd-unit-ready.yaml")
        result = evaluate_rubric(rubric, {
            "unit_tests_exist": False,
            "unit_tests_pass": False,
        })
        assert result.outcome == StageOutcome.FAIL
        assert result.failure_class == "no_unit_tests"

    def test_unit_ready_fail_tests_failing(self):
        rubric = load_rubric(BUILD_RUBRIC_DIR / "tdd-unit-ready.yaml")
        result = evaluate_rubric(rubric, {
            "unit_tests_exist": True,
            "unit_tests_pass": False,
        })
        assert result.outcome == StageOutcome.FAIL
        assert result.failure_class == "unit_tests_failing"

    def test_unit_ready_warn_low_coverage(self):
        rubric = load_rubric(BUILD_RUBRIC_DIR / "tdd-unit-ready.yaml")
        result = evaluate_rubric(rubric, {
            "unit_tests_exist": True,
            "unit_tests_pass": True,
            "coverage_above_threshold": False,
        })
        assert result.outcome == StageOutcome.WARN

    def test_integration_ready_pass(self):
        rubric = load_rubric(BUILD_RUBRIC_DIR / "tdd-integration-ready.yaml")
        result = evaluate_rubric(rubric, {
            "unit_tests_pass": True,
            "integration_tests_exist": True,
            "integration_tests_pass": True,
            "service_dependencies_available": True,
        })
        assert result.outcome == StageOutcome.PASS

    def test_integration_ready_entry_gate(self):
        rubric = load_rubric(BUILD_RUBRIC_DIR / "tdd-integration-ready.yaml")
        result = evaluate_rubric(rubric, {
            "unit_tests_pass": False,
            "integration_tests_exist": True,
            "integration_tests_pass": True,
        })
        assert result.outcome == StageOutcome.FAIL
        assert "Entry criterion" in result.message

    def test_contract_ready_pass(self):
        rubric = load_rubric(BUILD_RUBRIC_DIR / "tdd-contract-ready.yaml")
        result = evaluate_rubric(rubric, {
            "unit_tests_pass": True,
            "contract_tests_exist": True,
            "contract_tests_pass": True,
            "schema_compatibility_verified": True,
        })
        assert result.outcome == StageOutcome.PASS

    def test_e2e_ready_pass(self):
        rubric = load_rubric(BUILD_RUBRIC_DIR / "tdd-e2e-ready.yaml")
        result = evaluate_rubric(rubric, {
            "integration_tests_pass": True,
            "e2e_tests_exist": True,
            "e2e_tests_pass": True,
            "all_stages_green": True,
        })
        assert result.outcome == StageOutcome.PASS

    def test_e2e_ready_fail(self):
        rubric = load_rubric(BUILD_RUBRIC_DIR / "tdd-e2e-ready.yaml")
        result = evaluate_rubric(rubric, {
            "integration_tests_pass": True,
            "e2e_tests_exist": True,
            "e2e_tests_pass": False,
        })
        assert result.outcome == StageOutcome.FAIL
        assert result.failure_class == "e2e_tests_failing"

    def test_timeout_propagated(self):
        rubric = load_rubric(BUILD_RUBRIC_DIR / "tdd-unit-ready.yaml")
        result = evaluate_rubric(rubric, {
            "unit_tests_exist": True,
            "unit_tests_pass": True,
        })
        assert result.timeout_seconds == 120


class TestRemediationCatalogCrossReference:
    """Every recommended_action in every rubric must have a catalog entry."""

    def _load_catalog_ids(self):
        data = yaml.safe_load(CATALOG_PATH.read_text())
        return {entry["id"] for entry in data}

    def _load_all_recommended_actions(self):
        actions = set()
        for rubric_dir in [PLATFORM_RUBRIC_DIR, BUILD_RUBRIC_DIR]:
            for rubric in load_rubrics_from_directory(rubric_dir):
                for fc in rubric.failure_classes.values():
                    actions.add(fc.recommended_action)
        return actions

    def test_all_recommended_actions_have_catalog_entry(self):
        catalog_ids = self._load_catalog_ids()
        actions = self._load_all_recommended_actions()
        missing = actions - catalog_ids
        assert not missing, (
            f"Recommended actions without catalog entries: {missing}"
        )

    def test_catalog_has_minimum_entries(self):
        catalog_ids = self._load_catalog_ids()
        assert len(catalog_ids) >= 10

    def test_all_platform_rubrics_have_timeout(self):
        for rubric in load_rubrics_from_directory(PLATFORM_RUBRIC_DIR):
            assert rubric.timeout_seconds is not None, f"Platform rubric {rubric.id} missing timeout_seconds"
