"""Unit tests for engine/oc_runner.py — shared oc command runner."""

import subprocess
from unittest.mock import patch, MagicMock

import pytest

from engine.oc_runner import run_oc, run_oc_traced, run_oc_stdin


def _mock_result(stdout="", stderr="", returncode=0):
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


# ---------------------------------------------------------------------------
# run_oc
# ---------------------------------------------------------------------------

class TestRunOc:
    @patch("engine.oc_runner.subprocess.run")
    def test_success_returns_stdout(self, mock_run):
        mock_run.return_value = _mock_result(stdout="pod/foo created\n")
        assert run_oc(["get", "pods"]) == "pod/foo created"

    @patch("engine.oc_runner.subprocess.run")
    def test_not_found_is_non_error(self, mock_run):
        mock_run.return_value = _mock_result(stderr="Error from server (NotFound): pods \"x\" not found\n", returncode=1)
        result = run_oc(["get", "pod", "x"])
        assert "not found" in result.lower()

    @patch("engine.oc_runner.subprocess.run")
    def test_no_resources_is_non_error(self, mock_run):
        mock_run.return_value = _mock_result(stderr="No resources found in namespace.\n", returncode=1)
        result = run_oc(["get", "pods", "-n", "empty"])
        assert "no resources" in result.lower()

    @patch("engine.oc_runner.subprocess.run")
    def test_forbidden_returns_stderr(self, mock_run):
        mock_run.return_value = _mock_result(stderr="Error: Forbidden\n", returncode=1)
        result = run_oc(["get", "secrets"])
        assert "Forbidden" in result

    @patch("engine.oc_runner.subprocess.run")
    def test_cannot_returns_stderr(self, mock_run):
        mock_run.return_value = _mock_result(stderr="cannot list resource\n", returncode=1)
        result = run_oc(["get", "nodes"])
        assert "cannot" in result

    @patch("engine.oc_runner.subprocess.run")
    def test_other_error_logs_warning(self, mock_run):
        mock_run.return_value = _mock_result(stderr="connection refused\n", returncode=1)
        with patch("engine.oc_runner.logger") as mock_logger:
            run_oc(["get", "pods"])
            mock_logger.warning.assert_called_once()
            assert "connection refused" in mock_logger.warning.call_args[0][0]

    @patch("engine.oc_runner.subprocess.run")
    def test_kubeconfig_set_in_env(self, mock_run):
        mock_run.return_value = _mock_result(stdout="ok")
        run_oc(["get", "pods"], kubeconfig="/path/to/kc")
        call_env = mock_run.call_args[1]["env"]
        assert call_env["KUBECONFIG"] == "/path/to/kc"

    @patch("engine.oc_runner.subprocess.run")
    def test_no_kubeconfig_no_override(self, mock_run):
        mock_run.return_value = _mock_result(stdout="ok")
        run_oc(["get", "pods"])
        call_env = mock_run.call_args[1]["env"]
        assert "KUBECONFIG" not in call_env or call_env.get("KUBECONFIG") == ""

    @patch("engine.oc_runner.subprocess.run")
    def test_timeout_passed_through(self, mock_run):
        mock_run.return_value = _mock_result(stdout="ok")
        run_oc(["get", "pods"], timeout=99)
        assert mock_run.call_args[1]["timeout"] == 99

    @patch("engine.oc_runner.subprocess.run")
    def test_cmd_prefixed_with_oc(self, mock_run):
        mock_run.return_value = _mock_result(stdout="ok")
        run_oc(["get", "pods", "-n", "default"])
        assert mock_run.call_args[0][0] == ["oc", "get", "pods", "-n", "default"]

    @patch("engine.oc_runner.subprocess.run")
    def test_empty_stdout_falls_back_to_stderr(self, mock_run):
        mock_run.return_value = _mock_result(stdout="", stderr="some info\n", returncode=0)
        assert run_oc(["version"]) == "some info"


# ---------------------------------------------------------------------------
# run_oc_traced
# ---------------------------------------------------------------------------

class TestRunOcTraced:
    @patch("engine.oc_runner.subprocess.run")
    def test_returns_tuple(self, mock_run):
        mock_run.return_value = _mock_result(stdout="ok")
        result = run_oc_traced(["get", "pods"])
        assert isinstance(result, tuple)
        assert len(result) == 2

    @patch("engine.oc_runner.subprocess.run")
    def test_trace_has_required_keys(self, mock_run):
        mock_run.return_value = _mock_result(stdout="ok")
        _, trace = run_oc_traced(["get", "pods"])
        assert "command" in trace
        assert "output" in trace
        assert "exit_code" in trace
        assert "duration_ms" in trace

    @patch("engine.oc_runner.subprocess.run")
    def test_trace_command_includes_oc(self, mock_run):
        mock_run.return_value = _mock_result(stdout="ok")
        _, trace = run_oc_traced(["get", "pods", "-n", "ns"])
        assert trace["command"] == "oc get pods -n ns"

    @patch("engine.oc_runner.subprocess.run")
    def test_trace_exit_code_captured(self, mock_run):
        mock_run.return_value = _mock_result(stderr="err", returncode=42)
        _, trace = run_oc_traced(["bad"])
        assert trace["exit_code"] == 42

    @patch("engine.oc_runner.subprocess.run")
    def test_trace_duration_is_int(self, mock_run):
        mock_run.return_value = _mock_result(stdout="ok")
        _, trace = run_oc_traced(["get", "pods"])
        assert isinstance(trace["duration_ms"], int)
        assert trace["duration_ms"] >= 0

    @patch("engine.oc_runner.subprocess.run")
    def test_output_truncated_at_2000(self, mock_run):
        long_output = "x" * 3000
        mock_run.return_value = _mock_result(stdout=long_output)
        output, trace = run_oc_traced(["get", "pods"])
        assert len(trace["output"]) == 2000
        assert len(output) == 3000

    @patch("engine.oc_runner.subprocess.run")
    def test_forbidden_returns_stderr_in_trace(self, mock_run):
        mock_run.return_value = _mock_result(stderr="Forbidden: access denied\n", returncode=1)
        output, trace = run_oc_traced(["get", "secrets"])
        assert "Forbidden" in output
        assert "Forbidden" in trace["output"]

    @patch("engine.oc_runner.subprocess.run")
    def test_not_found_non_error(self, mock_run):
        mock_run.return_value = _mock_result(stderr="not found\n", returncode=1)
        output, trace = run_oc_traced(["get", "pod", "x"])
        assert "not found" in output

    @patch("engine.oc_runner.subprocess.run")
    def test_kubeconfig_set_in_env(self, mock_run):
        mock_run.return_value = _mock_result(stdout="ok")
        run_oc_traced(["get", "pods"], kubeconfig="/kc")
        call_env = mock_run.call_args[1]["env"]
        assert call_env["KUBECONFIG"] == "/kc"


# ---------------------------------------------------------------------------
# run_oc_stdin
# ---------------------------------------------------------------------------

class TestRunOcStdin:
    @patch("engine.oc_runner.subprocess.run")
    def test_success_returns_stdout(self, mock_run):
        mock_run.return_value = _mock_result(stdout="deployment.apps/foo created\n")
        result = run_oc_stdin(["apply", "-f", "-"], '{"kind": "Deployment"}')
        assert result == "deployment.apps/foo created"

    @patch("engine.oc_runner.subprocess.run")
    def test_input_data_passed_to_subprocess(self, mock_run):
        mock_run.return_value = _mock_result(stdout="ok")
        run_oc_stdin(["apply", "-f", "-"], "my-manifest-data")
        assert mock_run.call_args[1]["input"] == "my-manifest-data"

    @patch("engine.oc_runner.subprocess.run")
    def test_error_logs_warning(self, mock_run):
        mock_run.return_value = _mock_result(stderr="invalid yaml\n", returncode=1)
        with patch("engine.oc_runner.logger") as mock_logger:
            run_oc_stdin(["apply", "-f", "-"], "bad")
            mock_logger.warning.assert_called_once()

    @patch("engine.oc_runner.subprocess.run")
    def test_error_returns_stderr(self, mock_run):
        mock_run.return_value = _mock_result(stdout="", stderr="error: invalid\n", returncode=1)
        result = run_oc_stdin(["apply", "-f", "-"], "bad")
        assert "invalid" in result

    @patch("engine.oc_runner.subprocess.run")
    def test_kubeconfig_set_in_env(self, mock_run):
        mock_run.return_value = _mock_result(stdout="ok")
        run_oc_stdin(["apply", "-f", "-"], "{}", kubeconfig="/kc")
        call_env = mock_run.call_args[1]["env"]
        assert call_env["KUBECONFIG"] == "/kc"

    @patch("engine.oc_runner.subprocess.run")
    def test_timeout_passed_through(self, mock_run):
        mock_run.return_value = _mock_result(stdout="ok")
        run_oc_stdin(["apply", "-f", "-"], "{}", timeout=45)
        assert mock_run.call_args[1]["timeout"] == 45

    @patch("engine.oc_runner.subprocess.run")
    def test_cmd_prefixed_with_oc(self, mock_run):
        mock_run.return_value = _mock_result(stdout="ok")
        run_oc_stdin(["apply", "-f", "-", "-n", "test"], "{}")
        assert mock_run.call_args[0][0] == ["oc", "apply", "-f", "-", "-n", "test"]
