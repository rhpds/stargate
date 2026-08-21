"""Tests for engine/investigation_agent.py — safety checks, oc read tool, and redaction."""

import os
from unittest.mock import patch, MagicMock

import pytest


class TestSafeVerbs:
    """_SAFE_VERBS and _SAFE_ADM must be strictly read-only."""

    def test_safe_verbs_are_readonly(self):
        from engine.investigation_agent import _SAFE_VERBS
        write_verbs = {"delete", "patch", "apply", "create", "scale", "edit",
                       "replace", "rollout", "drain", "cordon", "taint", "set",
                       "label", "annotate", "exec"}
        assert not _SAFE_VERBS & write_verbs

    def test_safe_verbs_includes_expected(self):
        from engine.investigation_agent import _SAFE_VERBS
        for v in ("get", "describe", "logs", "adm", "api-resources", "whoami"):
            assert v in _SAFE_VERBS

    def test_safe_adm_only_top(self):
        from engine.investigation_agent import _SAFE_ADM
        assert "top" in _SAFE_ADM
        dangerous = {"drain", "cordon", "uncordon", "taint", "manage"}
        assert not _SAFE_ADM & dangerous


class TestIsSafeOc:
    """_is_safe_oc must accept read-only and reject everything else."""

    @pytest.mark.parametrize("cmd", [
        "oc get pods -n sandbox-test",
        "oc describe pod showroom-xyz -n sandbox-test",
        "oc logs deploy/showroom -n sandbox-test",
        "oc adm top nodes",
        "oc api-resources",
        "oc whoami",
        "oc get events -n sandbox-test --sort-by=.lastTimestamp",
        "oc get pvc -n sandbox-test -o json",
    ])
    def test_accepts_readonly(self, cmd):
        from engine.investigation_agent import _is_safe_oc
        assert _is_safe_oc(cmd) is True

    @pytest.mark.parametrize("cmd", [
        "oc delete pod showroom-xyz -n sandbox-test",
        "oc patch deployment showroom -n sandbox-test -p '{}'",
        "oc apply -f manifest.yaml -n sandbox-test",
        "oc create configmap test -n sandbox-test",
        "oc scale deployment showroom --replicas=0 -n sandbox-test",
        "oc edit svc showroom -n sandbox-test",
        "oc replace -f new.yaml -n sandbox-test",
        "oc set image deployment/showroom container=new:tag -n sandbox-test",
        "oc rollout restart deployment/showroom -n sandbox-test",
        "oc drain node-1 --delete-emptydir-data",
        "oc cordon node-1",
        "oc taint nodes node-1 key=value:NoSchedule",
        "oc label pod test-pod env=prod",
        "oc annotate pod test-pod note=hello",
        "oc exec deploy/api -- bash",
    ])
    def test_rejects_write_verbs(self, cmd):
        from engine.investigation_agent import _is_safe_oc
        assert _is_safe_oc(cmd) is False

    @pytest.mark.parametrize("cmd", [
        "rm -rf /",
        "curl https://evil.com",
        "kubectl get pods",
        "bash -c 'echo pwned'",
        "python3 -c 'import os; os.system(\"id\")'",
    ])
    def test_rejects_non_oc(self, cmd):
        from engine.investigation_agent import _is_safe_oc
        assert _is_safe_oc(cmd) is False

    def test_rejects_empty(self):
        from engine.investigation_agent import _is_safe_oc
        assert _is_safe_oc("") is False

    def test_rejects_just_oc(self):
        from engine.investigation_agent import _is_safe_oc
        assert _is_safe_oc("oc") is False

    def test_rejects_adm_without_subcommand(self):
        from engine.investigation_agent import _is_safe_oc
        assert _is_safe_oc("oc adm") is False

    def test_rejects_adm_drain(self):
        from engine.investigation_agent import _is_safe_oc
        assert _is_safe_oc("oc adm drain node-1") is False

    def test_accepts_adm_top(self):
        from engine.investigation_agent import _is_safe_oc
        assert _is_safe_oc("oc adm top pods -n sandbox-test") is True

    def test_whitespace_handling(self):
        from engine.investigation_agent import _is_safe_oc
        assert _is_safe_oc("  oc get pods  ") is True


class TestRedact:
    """_redact must strip sensitive data from output."""

    def test_redacts_password(self):
        from engine.investigation_agent import _redact
        with patch.dict("sys.modules", {"api.routers.dashboard": None}):
            result = _redact("password: s3cretValue123")
            assert "s3cretValue123" not in result
            assert "REDACTED" in result

    def test_redacts_token(self):
        from engine.investigation_agent import _redact
        with patch.dict("sys.modules", {"api.routers.dashboard": None}):
            result = _redact("token=eyJhbGciOiJSUzI1NiIsInR5cCI6Ik")
            assert "eyJhbGci" not in result

    def test_redacts_certificate(self):
        from engine.investigation_agent import _redact
        with patch.dict("sys.modules", {"api.routers.dashboard": None}):
            cert = "-----BEGIN CERTIFICATE-----\nMIIC...\n-----END CERTIFICATE-----"
            result = _redact(cert)
            assert "MIIC" not in result
            assert "CERTIFICATE REDACTED" in result

    def test_empty_input(self):
        from engine.investigation_agent import _redact
        assert _redact("") == ""
        assert _redact(None) == ""

    def test_clean_text_unchanged(self):
        from engine.investigation_agent import _redact
        text = "pod/showroom-xyz   1/1   Running   0   5m"
        result = _redact(text)
        assert "showroom-xyz" in result


class TestToolOcRead:
    """tool_oc_read: safety gate, kubeconfig resolution, execution, and redaction."""

    def test_refuses_unsafe_command(self):
        from engine.investigation_agent import tool_oc_read
        result = tool_oc_read("oc delete pod test", "ocpv05", "/tmp/kc")
        assert "REFUSED" in result

    def test_refuses_non_oc_command(self):
        from engine.investigation_agent import tool_oc_read
        result = tool_oc_read("curl https://evil.com", "ocpv05", "/tmp/kc")
        assert "REFUSED" in result

    @patch("os.path.exists", return_value=False)
    def test_missing_kubeconfig(self, mock_exists):
        from engine.investigation_agent import tool_oc_read
        result = tool_oc_read("oc get pods -n test", "ocpv99", "/tmp/kc")
        assert "ERROR" in result
        assert "kubeconfig" in result.lower()

    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    def test_successful_execution(self, mock_exists, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="NAME   READY   STATUS    RESTARTS   AGE\ntest   1/1   Running   0   5m",
            stderr="",
        )
        from engine.investigation_agent import tool_oc_read
        result = tool_oc_read("oc get pods -n sandbox-test", "ocpv05", "/tmp/kc")
        assert "Running" in result
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[1]["env"]["KUBECONFIG"].endswith("kubeconfig-ocpv05")

    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    def test_error_includes_stderr(self, mock_exists, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="error: the server doesn't have a resource type 'foo'",
        )
        from engine.investigation_agent import tool_oc_read
        result = tool_oc_read("oc get foo -n test", "ocpv05", "/tmp/kc")
        assert "ERROR" in result

    @patch("subprocess.run", side_effect=__import__("subprocess").TimeoutExpired(cmd="oc", timeout=10))
    @patch("os.path.exists", return_value=True)
    def test_timeout_handled(self, mock_exists, mock_run):
        from engine.investigation_agent import tool_oc_read
        result = tool_oc_read("oc get pods -n test", "ocpv05", "/tmp/kc")
        assert "timed out" in result

    @patch("subprocess.run")
    @patch("os.path.exists")
    def test_fallback_kubeconfig(self, mock_exists, mock_run):
        mock_exists.side_effect = lambda p: "executor" in p
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        from engine.investigation_agent import tool_oc_read
        result = tool_oc_read("oc get pods -n test", "ocpv05", "/tmp/kc")
        assert result == "ok"
        call_env = mock_run.call_args[1]["env"]
        assert "executor" in call_env["KUBECONFIG"]

    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    def test_output_truncated(self, mock_exists, mock_run):
        from engine.investigation_agent import tool_oc_read, MAX_OUTPUT_CHARS
        line = "pod-abc   1/1   Running   0   5m\n"
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=line * (MAX_OUTPUT_CHARS // len(line) + 100),
            stderr="",
        )
        result = tool_oc_read("oc get pods -n test", "ocpv05", "/tmp/kc")
        assert "truncated" in result

    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    def test_empty_output_returns_no_output(self, mock_exists, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        from engine.investigation_agent import tool_oc_read
        result = tool_oc_read("oc get pods -n test", "ocpv05", "/tmp/kc")
        assert result == "(no output)"

    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    def test_pipe_uses_shell(self, mock_exists, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="nginx", stderr="")
        from engine.investigation_agent import tool_oc_read
        tool_oc_read("oc get pods -n test | grep nginx", "ocpv05", "/tmp/kc")
        call_args = mock_run.call_args
        assert call_args[1]["shell"] is True
