"""CLI tests — validate-rubric, evaluate, collect-dir."""

import pytest

from cli.stargate import main


class TestValidateRubric:
    def test_validate_directory(self, capsys):
        rc = main(["validate-rubric", "rubrics/platform/"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "namespace-ready" in out
        assert "deployment-ready" in out
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


class TestEvaluate:
    def test_successful_fixture(self, capsys):
        rc = main(["evaluate", "fixtures/successful-container-run.yaml"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[+] namespace-ready: pass" in out
        assert "[+] deployment-ready: pass" in out
        assert "8 passed, 0 failed" in out

    def test_failed_fixture(self, capsys):
        rc = main(["evaluate", "fixtures/failed-route-run.yaml"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "[X] route-ready: fail" in out
        assert "service_has_no_endpoints" in out

    def test_warn_fixture(self, capsys):
        rc = main(["evaluate", "fixtures/warn-smoke-test-run.yaml"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[~] smoke-test-ready: warn" in out
        assert "6 passed, 0 failed, 1 warned" in out

    def test_json_output(self, capsys):
        rc = main(["evaluate", "fixtures/successful-container-run.yaml", "--format", "json"])
        assert rc == 0
        import json
        data = json.loads(capsys.readouterr().out)
        assert data["run"]["run_id"] == "local-demo-001"
        assert all(r["outcome"] == "pass" for r in data["results"])

    def test_nonexistent_fixture(self, capsys):
        rc = main(["evaluate", "nonexistent.yaml"])
        assert rc == 1


class TestCollectDir:
    def test_collect_healthy_dir(self, capsys):
        rc = main(["collect-dir", "fixtures/oc/healthy",
                    "--stages", "namespace-ready,deployment-ready,route-ready"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[+] namespace-ready: pass" in out
        assert "[+] deployment-ready: pass" in out

    def test_collect_unhealthy_dir(self, capsys):
        rc = main(["collect-dir", "fixtures/oc/unhealthy",
                    "--stages", "namespace-ready,deployment-ready"])
        # unhealthy has crashlooping pods
        out = capsys.readouterr().out
        assert "[X] deployment-ready: fail" in out
        assert "pods_crashlooping" in out

    def test_collect_anarchy_healthy(self, capsys):
        rc = main(["collect-dir", "fixtures/oc/anarchy-healthy",
                    "--stages", "provision-complete"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[+] provision-complete: pass" in out

    def test_collect_anarchy_unhealthy(self, capsys):
        rc = main(["collect-dir", "fixtures/oc/anarchy-unhealthy",
                    "--stages", "provision-complete"])
        out = capsys.readouterr().out
        assert "[X] provision-complete: fail" in out
        assert "provision_failed" in out

    def test_collect_json_output(self, capsys):
        rc = main(["collect-dir", "fixtures/oc/healthy",
                    "--stages", "namespace-ready", "--format", "json"])
        assert rc == 0
        import json
        data = json.loads(capsys.readouterr().out)
        assert data["results"][0]["outcome"] == "pass"

    def test_nonexistent_dir(self, capsys):
        rc = main(["collect-dir", "nonexistent/"])
        assert rc == 1


class TestNoCommand:
    def test_no_command_shows_help(self, capsys):
        rc = main([])
        assert rc == 0
