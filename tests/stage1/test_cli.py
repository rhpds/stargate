"""CLI command tests — validate-rubric, create-run, run-fixture, build-report."""

from unittest.mock import patch

import pytest

from engine.models import BuildReport, BuildStageReport, BuildStageResult
from cli.sdf import main


class TestValidateRubric:
    def test_validate_directory(self, capsys):
        rc = main(["validate-rubric", "rubrics/platform/"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "namespace-ready" in out
        assert "deployment-ready" in out
        assert "route-ready" in out
        assert "smoke-test-ready" in out
        assert "Validated 11 rubrics" in out

    def test_validate_single_file(self, capsys):
        rc = main(["validate-rubric", "rubrics/platform/namespace-ready.yaml"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "namespace-ready" in out

    def test_validate_nonexistent(self, capsys):
        rc = main(["validate-rubric", "rubrics/platform/nonexistent.yaml"])
        assert rc == 1

    def test_validate_bad_extension(self, tmp_path, capsys):
        bad = tmp_path / "test.json"
        bad.write_text("{}")
        rc = main(["validate-rubric", str(bad)])
        assert rc == 1


class TestCreateRun:
    def test_create_from_definition(self, capsys):
        rc = main(["create-run", "demo-definitions/demo-simple-container.yaml"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Run created:" in out
        assert "demo-simple-container" in out
        assert "namespace-ready" in out

    def test_create_with_custom_id(self, capsys):
        rc = main(["create-run", "demo-definitions/demo-simple-container.yaml",
                    "--run-id", "my-custom-run"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "my-custom-run" in out

    def test_create_nonexistent_definition(self, capsys):
        rc = main(["create-run", "nonexistent.yaml"])
        assert rc == 1


class TestRunFixture:
    def test_successful_fixture(self, capsys):
        rc = main(["run-fixture", "fixtures/successful-container-run.yaml"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "local-demo-001" in out
        assert "[+] namespace-ready: pass" in out
        assert "[+] deployment-ready: pass" in out
        assert "[+] route-ready: pass" in out
        assert "[+] smoke-test-ready: pass" in out
        assert "8 passed, 0 failed" in out

    def test_failed_fixture(self, capsys):
        rc = main(["run-fixture", "fixtures/failed-route-run.yaml"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[X] route-ready: fail" in out
        assert "service_has_no_endpoints" in out
        assert "Failed Stages:" in out
        assert "5 passed, 2 failed" in out

    def test_warn_fixture(self, capsys):
        rc = main(["run-fixture", "fixtures/warn-smoke-test-run.yaml"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[~] smoke-test-ready: warn" in out
        assert "response_time_acceptable" in out
        assert "6 passed, 0 failed, 1 warned" in out

    def test_fixture_yaml_output(self, capsys):
        rc = main(["run-fixture", "fixtures/successful-container-run.yaml", "--format", "yaml"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "run_id: local-demo-001" in out
        assert "status: completed" in out

    def test_fixture_nonexistent(self, capsys):
        rc = main(["run-fixture", "nonexistent.yaml"])
        assert rc == 1


class TestBuildReport:
    def test_build_report(self, capsys):
        mock_report = BuildReport(
            build_run_id="test-build-001",
            status=BuildStageResult.GREEN,
            stages=[
                BuildStageReport(name="schema_models", result=BuildStageResult.GREEN, tests=10, failures=0),
            ],
        )
        with patch("cli.sdf.generate_build_report", return_value=mock_report):
            rc = main(["build-report"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Build Report:" in out
        assert "schema_models" in out


class TestNoCommand:
    def test_no_command_shows_help(self, capsys):
        rc = main([])
        assert rc == 1
