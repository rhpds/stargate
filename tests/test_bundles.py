"""Stage 3 — evidence bundle tests with history."""

import pytest


class TestBundleWithHistory:
    def _create_evaluations(self, client):
        """Create multiple runs for the same lab to build history."""
        for i in range(5):
            client.post("/runs", json={
                "run_id": f"bundle-run-{i}",
                "demo_id": "demo-simple-container",
                "namespace": f"summit-demo-bundle",
                "requested_by": "test",
                "rubric_version": "v0.1.0",
            })
            client.post(f"/runs/bundle-run-{i}/stages/namespace-ready/start")

            evidence = {"namespace_exists": True} if i != 3 else {"namespace_exists": False}
            client.post(f"/runs/bundle-run-{i}/stages/namespace-ready/evaluate", json={
                "evidence": evidence,
            })

    def test_bundle_includes_current(self, client):
        self._create_evaluations(client)
        resp = client.get("/runs/bundle-run-4/bundle")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "bundle-run-4"
        assert len(data["current"]["stages"]) == 1
        assert data["current"]["stages"][0]["outcome"] == "pass"

    def test_bundle_has_history_key(self, client):
        self._create_evaluations(client)
        resp = client.get("/runs/bundle-run-4/bundle")
        data = resp.json()
        assert "history" in data
        assert isinstance(data["history"], list)

    def test_bundle_has_failure_frequency(self, client):
        self._create_evaluations(client)
        resp = client.get("/runs/bundle-run-4/bundle")
        data = resp.json()
        assert "failure_frequency" in data

    def test_bundle_has_last_passing_run(self, client):
        self._create_evaluations(client)
        resp = client.get("/runs/bundle-run-4/bundle")
        data = resp.json()
        assert "last_passing_run" in data


class TestLabHistory:
    def _seed(self, client):
        for i in range(3):
            outcome = "pass" if i < 2 else "fail"
            evidence = {"namespace_exists": True} if i < 2 else {"namespace_exists": False}
            client.post("/runs", json={
                "run_id": f"hist-{i}",
                "demo_id": "demo",
                "namespace": "ns",
                "requested_by": "test",
                "rubric_version": "v0.1.0",
            })
            client.post(f"/runs/hist-{i}/stages/namespace-ready/start")
            client.post(f"/runs/hist-{i}/stages/namespace-ready/evaluate", json={
                "evidence": evidence,
            })

    def test_lab_history_endpoint(self, client):
        self._seed(client)
        resp = client.get("/labs/test-lab/history")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_lab_failures_endpoint(self, client):
        self._seed(client)
        resp = client.get("/labs/test-lab/failures")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)


class TestClusterSummary:
    def test_cluster_summary_endpoint(self, client):
        resp = client.get("/clusters/test-cluster/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "cluster" in data
        assert "total_evaluations" in data
        assert "health_rate" in data
        assert "failure_classes" in data

    def test_cluster_failures_endpoint(self, client):
        resp = client.get("/clusters/test-cluster/failures")
        assert resp.status_code == 200
