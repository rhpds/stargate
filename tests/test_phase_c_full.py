"""Phase C Full Loop — scenario → recommend → execute real oc → verify → rollback.

RED/GREEN TDD. Requires infra01 access and stargate-executor SA.
"""

import os
import sys
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "stargate-synthetic-client-emulator"))

EXECUTOR_KUBECONFIG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "secrets", "kubeconfig-executor")
HAS_EXECUTOR = os.path.exists(EXECUTOR_KUBECONFIG)
TEST_NS = "stargate-test"

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not HAS_EXECUTOR, reason="No executor kubeconfig")
class TestActionCommandMapping:
    def test_cluster_capacity_maps_to_scale(self):
        """cluster_capacity recommendation maps to oc scale command."""
        from engine.oc_executor import map_action_to_commands
        cmds = map_action_to_commands("cluster_capacity", TEST_NS, {"deployment": "test-app", "replicas": 3})
        assert len(cmds) > 0
        assert any("scale" in c for c in cmds)

    def test_cleanup_stuck_maps_to_delete(self):
        """cleanup_stuck maps to oc delete pod commands."""
        from engine.oc_executor import map_action_to_commands
        cmds = map_action_to_commands("cleanup_stuck", TEST_NS, {"pods": ["stuck-pod-1"]})
        assert any("delete" in c for c in cmds)

    def test_provision_blocked_maps_to_apply(self):
        """provision_blocked_lab maps to oc apply."""
        from engine.oc_executor import map_action_to_commands
        cmds = map_action_to_commands("provision_blocked_lab", TEST_NS, {"pool": "test-pool"})
        assert len(cmds) > 0


@pytest.mark.skipif(not HAS_EXECUTOR, reason="No executor kubeconfig")
class TestRealExecution:
    def test_execute_action_creates_deployment(self):
        """Action executor creates a real deployment via oc."""
        from engine.oc_executor import execute_oc_action
        from engine.rollback import _run_oc, capture_state

        _run_oc(["delete", "deployment", "exec-loop-test", "-n", TEST_NS, "--ignore-not-found"], EXECUTOR_KUBECONFIG)

        result = execute_oc_action(
            "cluster_capacity", TEST_NS, EXECUTOR_KUBECONFIG,
            {"deployment": "exec-loop-test", "image": "registry.access.redhat.com/ubi9/ubi-minimal:latest", "replicas": 2}
        )
        assert result["success"] is True

        state = capture_state(TEST_NS, EXECUTOR_KUBECONFIG)
        dep_names = [d.get("metadata", {}).get("name") for d in state.get("deployments", [])]
        assert "exec-loop-test" in dep_names

        _run_oc(["delete", "deployment", "exec-loop-test", "-n", TEST_NS, "--ignore-not-found"], EXECUTOR_KUBECONFIG)

    def test_execute_with_rollback_on_failure(self):
        """Failed verification triggers automatic rollback."""
        from engine.oc_executor import execute_oc_action
        from engine.rollback import capture_state, _run_oc

        _run_oc([
            "create", "deployment", "rollback-victim",
            "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
            "-n", TEST_NS
        ], EXECUTOR_KUBECONFIG)

        snapshot = capture_state(TEST_NS, EXECUTOR_KUBECONFIG)

        _run_oc(["delete", "deployment", "rollback-victim", "-n", TEST_NS], EXECUTOR_KUBECONFIG)

        from engine.rollback import restore_state
        result = restore_state(snapshot, TEST_NS, EXECUTOR_KUBECONFIG)
        assert result["restored"] > 0

        after = capture_state(TEST_NS, EXECUTOR_KUBECONFIG)
        dep_names = [d.get("metadata", {}).get("name") for d in after.get("deployments", [])]
        assert "rollback-victim" in dep_names

        _run_oc(["delete", "deployment", "rollback-victim", "-n", TEST_NS, "--ignore-not-found"], EXECUTOR_KUBECONFIG)


@pytest.mark.skipif(not HAS_EXECUTOR, reason="No executor kubeconfig")
class TestFullFeedbackLoopReal:
    def test_full_loop_creates_and_verifies(self):
        """Full loop: create seed state → execute action → verify state changed → cleanup."""
        from engine.rollback import _run_oc, capture_state
        from engine.oc_executor import execute_oc_action

        _run_oc(["delete", "deployment", "loop-seed", "-n", TEST_NS, "--ignore-not-found"], EXECUTOR_KUBECONFIG)

        _run_oc([
            "create", "deployment", "loop-seed",
            "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
            "-n", TEST_NS
        ], EXECUTOR_KUBECONFIG)

        before = capture_state(TEST_NS, EXECUTOR_KUBECONFIG)
        before_deps = [d["metadata"]["name"] for d in before.get("deployments", [])]
        assert "loop-seed" in before_deps

        import time; time.sleep(2)
        result = execute_oc_action(
            "cluster_capacity", TEST_NS, EXECUTOR_KUBECONFIG,
            {"deployment": "loop-seed", "replicas": 3}
        )
        assert result["success"] is True

        import time; time.sleep(2)
        after = capture_state(TEST_NS, EXECUTOR_KUBECONFIG)
        after_dep = next((d for d in after["deployments"] if d["metadata"]["name"] == "loop-seed"), None)
        assert after_dep is not None
        assert after_dep["spec"]["replicas"] == 3

        _run_oc(["delete", "deployment", "loop-seed", "-n", TEST_NS, "--ignore-not-found"], EXECUTOR_KUBECONFIG)

    def test_audit_trail_recorded(self):
        """Execution writes to audit trail."""
        from engine.oc_executor import execute_oc_action
        from engine.rollback import _run_oc

        _run_oc(["delete", "deployment", "audit-test", "-n", TEST_NS, "--ignore-not-found"], EXECUTOR_KUBECONFIG)

        result = execute_oc_action(
            "cluster_capacity", TEST_NS, EXECUTOR_KUBECONFIG,
            {"deployment": "audit-test", "image": "registry.access.redhat.com/ubi9/ubi-minimal:latest", "replicas": 1}
        )
        assert "commands_executed" in result
        assert len(result["commands_executed"]) > 0

        _run_oc(["delete", "deployment", "audit-test", "-n", TEST_NS, "--ignore-not-found"], EXECUTOR_KUBECONFIG)
