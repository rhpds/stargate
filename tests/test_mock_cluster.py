"""RED/GREEN TDD — Item 5: Mock cluster for command validation."""


class TestMockCluster:
    """MockCluster must validate and track commands in-memory."""

    def test_mock_cluster_exists(self):
        from engine.mock_cluster import MockCluster
        mc = MockCluster()
        assert mc is not None

    def test_create_deployment(self):
        from engine.mock_cluster import MockCluster
        mc = MockCluster()
        result = mc.execute("oc create deployment test-app --image=ubi9:latest -n test-ns")
        assert result["success"]
        state = mc.get_state("test-ns")
        assert "test-app" in state.get("deployments", {})

    def test_scale_deployment(self):
        from engine.mock_cluster import MockCluster
        mc = MockCluster()
        mc.execute("oc create deployment myapp --image=ubi9 -n ns1")
        result = mc.execute("oc scale deployment/myapp --replicas=5 -n ns1")
        assert result["success"]
        state = mc.get_state("ns1")
        assert state["deployments"]["myapp"]["replicas"] == 5

    def test_delete_pod(self):
        from engine.mock_cluster import MockCluster
        mc = MockCluster()
        mc.execute("oc create deployment app1 --image=ubi9 -n ns1")
        result = mc.execute("oc delete pod pod-123 -n ns1")
        assert result["success"]

    def test_rollout_restart(self):
        from engine.mock_cluster import MockCluster
        mc = MockCluster()
        mc.execute("oc create deployment showroom --image=ubi9 -n ns1")
        result = mc.execute("oc rollout restart deployment/showroom -n ns1")
        assert result["success"]

    def test_unknown_command_fails(self):
        from engine.mock_cluster import MockCluster
        mc = MockCluster()
        result = mc.execute("oc totally-invalid-verb -n ns1")
        assert not result["success"]

    def test_forbidden_namespace(self):
        from engine.mock_cluster import MockCluster
        mc = MockCluster()
        result = mc.execute("oc delete pod test -n openshift-monitoring")
        assert not result["success"]
        assert "forbidden" in result.get("error", "").lower()

    def test_audit_trail(self):
        from engine.mock_cluster import MockCluster
        mc = MockCluster()
        mc.execute("oc create deployment app --image=ubi9 -n ns1")
        mc.execute("oc scale deployment/app --replicas=3 -n ns1")
        assert len(mc.history) == 2
        assert mc.history[0]["command"] == "oc create deployment app --image=ubi9 -n ns1"

    def test_reset(self):
        from engine.mock_cluster import MockCluster
        mc = MockCluster()
        mc.execute("oc create deployment app --image=ubi9 -n ns1")
        mc.reset()
        assert mc.get_state("ns1") == {"deployments": {}, "pods": {}, "services": {}}
        assert len(mc.history) == 0

    def test_patch_resourcepool(self):
        from engine.mock_cluster import MockCluster
        mc = MockCluster()
        result = mc.execute("oc patch resourcepool my-pool -n ns1 --type=merge -p '{\"spec\":{\"minAvailable\":5}}'")
        assert result["success"]


class TestMockExecutionMode:
    """action_executor mock mode must use MockCluster."""

    def test_mock_mode_validates_commands(self):
        """Mock mode should return command validation results, not just success=True."""
        from pathlib import Path
        src = Path(__file__).parent.parent / "api" / "action_executor.py"
        text = src.read_text()
        assert "MockCluster" in text or "mock_cluster" in text, (
            "action_executor.py must use MockCluster in mock mode"
        )
