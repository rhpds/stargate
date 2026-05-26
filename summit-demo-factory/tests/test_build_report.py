"""Tests for build TDD red/green report generation."""

from api.app.models import BuildReport, BuildStageReport, BuildStageResult
from reports.build_report import format_report_text, format_report_yaml


class TestBuildReportFormatting:
    def _make_green_report(self) -> BuildReport:
        return BuildReport(
            build_run_id="local-20260505-150000",
            git_sha="abc123",
            status=BuildStageResult.GREEN,
            stages=[
                BuildStageReport(name="schema_models", result=BuildStageResult.GREEN, tests=24, failures=0),
                BuildStageReport(name="rubric_parser", result=BuildStageResult.GREEN, tests=11, failures=0),
                BuildStageReport(name="rubric_evaluator", result=BuildStageResult.GREEN, tests=14, failures=0),
            ],
            blocking=[],
        )

    def _make_red_report(self) -> BuildReport:
        return BuildReport(
            build_run_id="local-20260505-150000",
            git_sha="abc123",
            status=BuildStageResult.RED,
            stages=[
                BuildStageReport(name="schema_models", result=BuildStageResult.GREEN, tests=24, failures=0),
                BuildStageReport(name="rubric_evaluator", result=BuildStageResult.RED, tests=14, failures=2),
            ],
            blocking=["rubric_evaluator"],
        )

    def test_green_report_text(self):
        text = format_report_text(self._make_green_report())
        assert "GREEN" in text
        assert "[+] schema_models" in text
        assert "[+] rubric_parser" in text
        assert "Blocking:" not in text

    def test_red_report_text(self):
        text = format_report_text(self._make_red_report())
        assert "RED" in text
        assert "[X] rubric_evaluator" in text
        assert "Blocking:" in text
        assert "rubric_evaluator" in text

    def test_green_report_yaml(self):
        yaml_output = format_report_yaml(self._make_green_report())
        assert "status: green" in yaml_output
        assert "schema_models" in yaml_output

    def test_red_report_yaml(self):
        yaml_output = format_report_yaml(self._make_red_report())
        assert "status: red" in yaml_output
        assert "rubric_evaluator" in yaml_output

    def test_report_contains_build_run_id(self):
        text = format_report_text(self._make_green_report())
        assert "local-20260505-150000" in text

    def test_report_contains_git_sha(self):
        text = format_report_text(self._make_green_report())
        assert "abc123" in text
