"""Simulated E2E test — runs a complete fixture through all stages end-to-end.

This test exercises the full local pipeline:
  load demo definition -> load rubrics -> evaluate each stage -> produce report

No API, no database, no cluster — purely deterministic.
"""

from pathlib import Path

import yaml

from engine.rubric_evaluator import evaluate_rubric
from engine.rubric_loader import load_rubrics_from_directory
from engine.models import StageOutcome
from cli.run_report import format_run_report_text, RunReportData, StageReportData


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "platform"
DEMO_DIR = Path(__file__).parent.parent / "demo-definitions"


class TestSimulatedE2E:
    """Full end-to-end simulation: load -> evaluate -> report."""

    def _load_rubrics(self):
        rubrics = {}
        for r in load_rubrics_from_directory(RUBRIC_DIR):
            rubrics[r.stage] = r
        return rubrics

    def _run_fixture(self, fixture_name: str):
        fixture_path = FIXTURE_DIR / fixture_name
        fixture = yaml.safe_load(fixture_path.read_text())
        rubrics = self._load_rubrics()

        run_info = fixture["run"]
        results = []

        for stage_data in fixture["stages"]:
            stage_id = stage_data["stage_id"]
            evidence = stage_data["evidence"]
            expected = stage_data.get("expected_outcome")

            rubric = rubrics[stage_id]
            result = evaluate_rubric(rubric, evidence)

            results.append({
                "stage_id": stage_id,
                "outcome": result.outcome,
                "failure_class": result.failure_class,
                "message": result.message,
                "expected": expected,
                "matched": result.outcome.value == expected if expected else None,
            })

        return run_info, results

    def test_successful_run_completes_all_stages(self):
        run_info, results = self._run_fixture("successful-container-run.yaml")
        assert len(results) == 8
        for r in results:
            assert r["outcome"] == StageOutcome.PASS
            assert r["matched"] is True

    def test_failed_run_identifies_failure_correctly(self):
        run_info, results = self._run_fixture("failed-route-run.yaml")
        assert len(results) == 7

        passed = [r for r in results if r["outcome"] == StageOutcome.PASS]
        failed = [r for r in results if r["outcome"] == StageOutcome.FAIL]
        assert len(passed) == 5
        assert len(failed) == 2

        route_fail = next(r for r in results if r["stage_id"] == "route-ready")
        assert route_fail["failure_class"] == "service_has_no_endpoints"
        assert route_fail["matched"] is True

    def test_warn_run_identifies_optional_failure(self):
        run_info, results = self._run_fixture("warn-smoke-test-run.yaml")
        assert len(results) == 7

        smoke_result = next(r for r in results if r["stage_id"] == "smoke-test-ready")
        assert smoke_result["outcome"] == StageOutcome.WARN
        assert smoke_result["matched"] is True

    def test_all_expectations_match(self):
        """Every stage in every fixture must match its expected outcome."""
        for fixture_name in ["successful-container-run.yaml", "failed-route-run.yaml", "warn-smoke-test-run.yaml"]:
            _, results = self._run_fixture(fixture_name)
            for r in results:
                if r["expected"] is not None:
                    assert r["matched"], (
                        f"{fixture_name} / {r['stage_id']}: "
                        f"expected {r['expected']}, got {r['outcome'].value}"
                    )

    def test_report_generation_from_fixture(self):
        """E2E: fixture -> evaluate -> report text includes correct data."""
        run_info, results = self._run_fixture("failed-route-run.yaml")

        stage_reports = [
            StageReportData(
                stage_id=r["stage_id"],
                status=r["outcome"].value,
                outcome=r["outcome"].value,
                failure_class=r["failure_class"],
                message=r["message"],
            )
            for r in results
        ]
        has_failure = any(r["outcome"] == StageOutcome.FAIL for r in results)

        report = RunReportData(
            run_id=run_info["run_id"],
            demo_id=run_info["demo_id"],
            namespace=run_info["namespace"],
            status="failed" if has_failure else "completed",
            rubric_version=run_info.get("rubric_version", "unknown"),
            stages=stage_reports,
        )

        text = format_run_report_text(report)
        assert "local-demo-002" in text
        assert "5 passed, 2 failed" in text
        assert "service_has_no_endpoints" in text
        assert "Failed Stages:" in text

    def test_demo_definition_stages_match_rubrics(self):
        """Every stage in the demo definition must have a corresponding rubric."""
        rubrics = self._load_rubrics()
        demo_path = DEMO_DIR / "demo-simple-container.yaml"
        demo = yaml.safe_load(demo_path.read_text())

        for stage_def in demo["stages"]:
            stage_id = stage_def["stage_id"]
            assert stage_id in rubrics, f"No rubric found for stage: {stage_id}"

    def test_stage_gate_blocks_on_failure(self):
        """A failed stage should produce FAIL — the gate blocks promotion."""
        _, results = self._run_fixture("failed-route-run.yaml")
        route_result = next(r for r in results if r["stage_id"] == "route-ready")
        assert route_result["outcome"] == StageOutcome.FAIL
        assert route_result["failure_class"] is not None
