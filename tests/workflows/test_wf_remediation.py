"""Workflow tests — Remediation: recommendation → gates → execute → rollback."""

import os
from unittest.mock import patch, MagicMock

import pytest


class TestRemediationGates:

    def test_namespace_allowlist_blocks(self, mock_db):
        from api.action_executor import execute_action
        with patch.dict(os.environ, {"STARGATE_REMEDIATION_NS": "launchpad-,stargate", "STARGATE_EXECUTION_TARGET": "mock"}):
            result = execute_action(
                action_type="cleanup_stuck", target="kube-system",
                parameters={"pods": ["test-pod"]}, confidence=1.0, db=mock_db,
            )
        assert result["executed"] is False

    def test_namespace_allowlist_passes_ecosystem(self, mock_db):
        from api.action_executor import execute_action
        with patch.dict(os.environ, {"STARGATE_REMEDIATION_NS": "launchpad-,stargate", "STARGATE_EXECUTION_TARGET": "mock", "STARGATE_DRY_RUN": "false"}):
            result = execute_action(
                action_type="cleanup_stuck", target="launchpad-test",
                parameters={"pods": ["test-pod"]}, confidence=1.0, db=mock_db,
            )
        assert result.get("reason") != "block_namespace"

    def test_dry_run_skips_execution(self, mock_db):
        from api.action_executor import execute_action
        import api.routers._shared as shared
        old = shared._dry_run_enabled
        shared._dry_run_enabled = True
        try:
            with patch.dict(os.environ, {"STARGATE_REMEDIATION_NS": "launchpad-", "STARGATE_EXECUTION_TARGET": "mock"}):
                result = execute_action(
                    action_type="cleanup_stuck", target="launchpad-test",
                    parameters={"pods": ["test-pod"]}, confidence=1.0, db=mock_db,
                )
            assert result["executed"] is False
        finally:
            shared._dry_run_enabled = old

    def test_audit_trail_written(self, mock_db):
        from api.action_executor import execute_action
        from db.models import AuditLog
        with patch.dict(os.environ, {"STARGATE_REMEDIATION_NS": "launchpad-", "STARGATE_EXECUTION_TARGET": "mock"}):
            execute_action(
                action_type="cleanup_stuck", target="launchpad-test",
                parameters={"pods": ["test-pod"]}, confidence=1.0, db=mock_db,
            )
        audits = mock_db.query(AuditLog).all()
        assert len(audits) >= 1


class TestOcExecutor:

    def test_validate_k8s_name_rejects_invalid(self):
        from engine.oc_executor import _validate_k8s_name
        with pytest.raises(ValueError):
            _validate_k8s_name("--output=/etc/shadow", "deployment")

    def test_validate_k8s_name_accepts_valid(self):
        from engine.oc_executor import _validate_k8s_name
        assert _validate_k8s_name("my-app-v2", "deployment") == "my-app-v2"

    def test_builtin_commands_cleanup(self):
        from engine.oc_executor import _builtin_commands
        cmds = _builtin_commands("cleanup_stuck", "test-ns", {"pods": ["pod-1", "pod-2"]})
        assert len(cmds) == 2
        assert "delete pod" in cmds[0]


class TestRollback:

    def test_capture_returns_snapshot_shape(self, mock_oc):
        mock_oc.return_value.stdout = '{"items": []}'
        from engine.rollback import capture_state
        snapshot = capture_state("test-ns", "")
        assert "namespace" in snapshot
        assert "deployments" in snapshot

    def test_verify_restore_checks_names(self):
        from engine.rollback import verify_restore
        snapshot = {"deployments": [{"metadata": {"name": "app"}}], "services": [], "pods": []}
        with patch("engine.rollback.capture_state") as mock_capture:
            mock_capture.return_value = {"deployments": [{"metadata": {"name": "app"}}], "services": [], "pods": []}
            assert verify_restore(snapshot, "test-ns", "") is True
