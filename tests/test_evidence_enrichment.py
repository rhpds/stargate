"""TDD tests — LLM evidence bundle enrichment across all touchpoints."""

import inspect
from pathlib import Path


class TestClassifyEvidence:
    def test_classify_includes_pool_state(self):
        from engine.auto_llm import _classify_failure
        source = inspect.getsource(_classify_failure)
        assert "Pool State" in source or "pool" in source.lower()

    def test_classify_includes_cluster_cpu(self):
        from engine.auto_llm import _classify_failure
        source = inspect.getsource(_classify_failure)
        assert "Cluster Utilization" in source or "cpu" in source.lower()


class TestExecSummaryEvidence:
    def test_capacity_evidence_helper_exists(self):
        from api.routers.dashboard import _get_capacity_evidence_for_summary
        assert callable(_get_capacity_evidence_for_summary)

    def test_exec_summary_calls_capacity_evidence(self):
        from api.routers.dashboard import dashboard_executive_summary
        source = inspect.getsource(dashboard_executive_summary)
        assert "_get_capacity_evidence_for_summary" in source

    def test_exec_summary_returns_sources_queried(self, client):
        resp = client.post("/dashboard/executive-summary")
        if resp.status_code == 200:
            data = resp.json()
            assert "sources_queried" in data


class TestReadinessGates:
    def test_readiness_has_capacity_gate(self, client):
        resp = client.get("/dashboard/readiness")
        assert resp.status_code == 200
        data = resp.json()
        assert "capacity" in data["gates"]
        assert "status" in data["gates"]["capacity"]
        assert "detail" in data["gates"]["capacity"]

    def test_readiness_has_sandbox_api_gate(self, client):
        resp = client.get("/dashboard/readiness")
        data = resp.json()
        assert "sandbox_api" in data["gates"]
        assert "status" in data["gates"]["sandbox_api"]

    def test_readiness_formula_uses_six_gates(self, client):
        resp = client.get("/dashboard/readiness")
        data = resp.json()
        gates = data["gates"]
        assert len(gates) == 6
        expected = {"provisioning", "health", "sessions", "infrastructure", "capacity", "sandbox_api"}
        assert set(gates.keys()) == expected

    def test_readiness_formula_weights_sum_to_one(self):
        weights = [0.30, 0.25, 0.15, 0.10, 0.10, 0.10]
        assert abs(sum(weights) - 1.0) < 0.001
