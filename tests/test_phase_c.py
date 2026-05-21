"""Phase C Tests — Real execution against stargate-test namespace.

RED/GREEN TDD. These tests require infra01 access and the stargate-executor SA.
Marked as integration tests so they don't run in the normal test suite.
"""

import os
import pytest

EXECUTOR_KUBECONFIG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "secrets", "kubeconfig-executor")
HAS_EXECUTOR = os.path.exists(EXECUTOR_KUBECONFIG)

pytestmark = pytest.mark.integration


@pytest.mark.skipif(not HAS_EXECUTOR, reason="No executor kubeconfig — skipping Phase C tests")
class TestTestNamespace:
    def test_executor_identity(self):
        """Executor SA authenticates correctly."""
        from engine.rollback import _run_oc
        result = _run_oc(["whoami"], EXECUTOR_KUBECONFIG)
        assert "stargate-executor" in result

    def test_can_write_test_namespace(self):
        """SA can create resources in stargate-test."""
        from engine.rollback import _run_oc
        result = _run_oc(["auth", "can-i", "create", "deployments", "-n", "stargate-test"], EXECUTOR_KUBECONFIG)
        assert "yes" in result

    def test_cannot_write_stargate_namespace(self):
        """SA cannot create resources in stargate namespace."""
        from engine.rollback import _run_oc
        result = _run_oc(["auth", "can-i", "create", "deployments", "-n", "stargate"], EXECUTOR_KUBECONFIG)
        assert "no" in result


@pytest.mark.skipif(not HAS_EXECUTOR, reason="No executor kubeconfig")
class TestRollback:
    def test_capture_state(self):
        """Captures current state of stargate-test namespace."""
        from engine.rollback import capture_state
        snapshot = capture_state("stargate-test", EXECUTOR_KUBECONFIG)
        assert "deployments" in snapshot
        assert "pods" in snapshot
        assert "services" in snapshot
        assert "timestamp" in snapshot

    def test_capture_restore_cycle(self):
        """Create resource → snapshot → delete → restore → verify."""
        from engine.rollback import capture_state, restore_state, _run_oc
        import json

        # Create a test deployment
        _run_oc([
            "create", "deployment", "rollback-test",
            "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
            "-n", "stargate-test"
        ], EXECUTOR_KUBECONFIG)

        # Capture state WITH the deployment
        snapshot = capture_state("stargate-test", EXECUTOR_KUBECONFIG)
        assert any(d.get("metadata", {}).get("name") == "rollback-test"
                    for d in snapshot.get("deployments", []))

        # Delete the deployment
        _run_oc(["delete", "deployment", "rollback-test", "-n", "stargate-test"], EXECUTOR_KUBECONFIG)

        # Verify it's gone
        result = _run_oc(["get", "deployments", "-n", "stargate-test", "-o", "json"], EXECUTOR_KUBECONFIG)
        items = json.loads(result).get("items", [])
        assert not any(d.get("metadata", {}).get("name") == "rollback-test" for d in items)

        # Restore from snapshot
        restore_result = restore_state(snapshot, "stargate-test", EXECUTOR_KUBECONFIG)
        assert restore_result["restored"] > 0

        # Verify it's back
        result = _run_oc(["get", "deployments", "-n", "stargate-test", "-o", "json"], EXECUTOR_KUBECONFIG)
        items = json.loads(result).get("items", [])
        assert any(d.get("metadata", {}).get("name") == "rollback-test" for d in items)

        # Cleanup
        _run_oc(["delete", "deployment", "rollback-test", "-n", "stargate-test", "--ignore-not-found"], EXECUTOR_KUBECONFIG)


@pytest.mark.skipif(not HAS_EXECUTOR, reason="No executor kubeconfig")
class TestRealExecution:
    def test_execute_create_deployment(self):
        """Action executor creates a real deployment in stargate-test."""
        from engine.rollback import _run_oc
        import json

        _run_oc([
            "create", "deployment", "exec-test",
            "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
            "-n", "stargate-test"
        ], EXECUTOR_KUBECONFIG)

        result = _run_oc(["get", "deployment", "exec-test", "-n", "stargate-test", "-o", "json"], EXECUTOR_KUBECONFIG)
        dep = json.loads(result)
        assert dep["metadata"]["name"] == "exec-test"

        # Cleanup
        _run_oc(["delete", "deployment", "exec-test", "-n", "stargate-test", "--ignore-not-found"], EXECUTOR_KUBECONFIG)

    def test_execute_scale_deployment(self):
        """Scales a deployment in stargate-test."""
        from engine.rollback import _run_oc
        import json

        _run_oc(["delete", "deployment", "scale-test", "-n", "stargate-test", "--ignore-not-found"], EXECUTOR_KUBECONFIG)
        _run_oc([
            "create", "deployment", "scale-test",
            "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
            "-n", "stargate-test"
        ], EXECUTOR_KUBECONFIG)

        _run_oc(["scale", "deployment", "scale-test", "--replicas=3", "-n", "stargate-test"], EXECUTOR_KUBECONFIG)

        import time; time.sleep(2)
        result = _run_oc(["get", "deployment", "scale-test", "-n", "stargate-test", "-o", "json"], EXECUTOR_KUBECONFIG)
        dep = json.loads(result)
        assert dep["spec"]["replicas"] == 3

        # Cleanup
        _run_oc(["delete", "deployment", "scale-test", "-n", "stargate-test", "--ignore-not-found"], EXECUTOR_KUBECONFIG)
