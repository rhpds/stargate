"""API contract tests — test all endpoints against the spec."""

import pytest


class TestHealth:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestRunEndpoints:
    def test_create_run(self, client):
        resp = client.post("/runs", json={
            "demo_id": "demo-simple-container",
            "namespace": "summit-demo-001",
            "requested_by": "test-user",
            "rubric_version": "v0.1.0",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["demo_id"] == "demo-simple-container"
        assert data["status"] == "pending"

    def test_create_run_with_id(self, client):
        resp = client.post("/runs", json={
            "run_id": "custom-run-001",
            "demo_id": "demo-simple-container",
            "namespace": "ns",
            "requested_by": "user",
            "rubric_version": "v0.1.0",
        })
        assert resp.status_code == 201
        assert resp.json()["run_id"] == "custom-run-001"

    def test_create_duplicate_run(self, client):
        payload = {
            "run_id": "dup-run",
            "demo_id": "demo",
            "namespace": "ns",
            "requested_by": "user",
            "rubric_version": "v0.1.0",
        }
        client.post("/runs", json=payload)
        resp = client.post("/runs", json=payload)
        assert resp.status_code == 409

    def test_get_run(self, client):
        client.post("/runs", json={
            "run_id": "get-run",
            "demo_id": "demo",
            "namespace": "ns",
            "requested_by": "user",
            "rubric_version": "v0.1.0",
        })
        resp = client.get("/runs/get-run")
        assert resp.status_code == 200
        assert resp.json()["run_id"] == "get-run"

    def test_get_run_not_found(self, client):
        resp = client.get("/runs/nonexistent")
        assert resp.status_code == 404

    def test_list_runs(self, client):
        for i in range(3):
            client.post("/runs", json={
                "run_id": f"list-run-{i}",
                "demo_id": "demo",
                "namespace": "ns",
                "requested_by": "user",
                "rubric_version": "v0.1.0",
            })
        resp = client.get("/runs")
        assert resp.status_code == 200
        assert len(resp.json()) == 3


class TestStageEndpoints:
    def _create_run(self, client):
        client.post("/runs", json={
            "run_id": "stage-test-run",
            "demo_id": "demo-simple-container",
            "namespace": "ns",
            "requested_by": "user",
            "rubric_version": "v0.1.0",
        })

    def test_start_stage(self, client):
        self._create_run(client)
        resp = client.post("/runs/stage-test-run/stages/namespace-ready/start")
        assert resp.status_code == 201
        assert resp.json()["stage_id"] == "namespace-ready"

    def test_start_stage_run_not_found(self, client):
        resp = client.post("/runs/nonexistent/stages/namespace-ready/start")
        assert resp.status_code == 404

    def test_start_duplicate_stage(self, client):
        self._create_run(client)
        client.post("/runs/stage-test-run/stages/namespace-ready/start")
        resp = client.post("/runs/stage-test-run/stages/namespace-ready/start")
        assert resp.status_code == 409


class TestEvidenceEndpoints:
    def _setup(self, client):
        client.post("/runs", json={
            "run_id": "ev-test-run",
            "demo_id": "demo-simple-container",
            "namespace": "ns",
            "requested_by": "user",
            "rubric_version": "v0.1.0",
        })
        client.post("/runs/ev-test-run/stages/namespace-ready/start")

    def test_submit_evidence(self, client):
        self._setup(client)
        resp = client.post("/runs/ev-test-run/stages/namespace-ready/evidence", json={
            "type": "resource_state",
            "source": "oc",
            "observed": {"namespace_exists": True},
            "result": "pass",
        })
        assert resp.status_code == 201


class TestEvaluateEndpoints:
    def _setup(self, client):
        client.post("/runs", json={
            "run_id": "eval-test-run",
            "demo_id": "demo-simple-container",
            "namespace": "ns",
            "requested_by": "user",
            "rubric_version": "v0.1.0",
        })
        client.post("/runs/eval-test-run/stages/namespace-ready/start")

    def test_evaluate_with_inline_evidence(self, client):
        self._setup(client)
        resp = client.post("/runs/eval-test-run/stages/namespace-ready/evaluate", json={
            "evidence": {"namespace_exists": True},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome"] == "pass"
        assert data["stage_id"] == "namespace-ready"

    def test_evaluate_failure_returns_class(self, client):
        self._setup(client)
        resp = client.post("/runs/eval-test-run/stages/namespace-ready/evaluate", json={
            "evidence": {"namespace_exists": False},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome"] == "fail"
        assert data["failure_class"] == "namespace_missing"

    def test_evaluate_run_not_found(self, client):
        resp = client.post("/runs/nonexistent/stages/namespace-ready/evaluate", json={
            "evidence": {"namespace_exists": True},
        })
        assert resp.status_code == 404


class TestReportEndpoints:
    def test_report(self, client):
        client.post("/runs", json={
            "run_id": "report-run",
            "demo_id": "demo-simple-container",
            "namespace": "ns",
            "requested_by": "user",
            "rubric_version": "v0.1.0",
        })
        client.post("/runs/report-run/stages/namespace-ready/start")
        client.post("/runs/report-run/stages/namespace-ready/evaluate", json={
            "evidence": {"namespace_exists": True},
        })
        resp = client.get("/runs/report-run/report")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "report-run"
        assert data["passed"] == 1

    def test_report_not_found(self, client):
        resp = client.get("/runs/nonexistent/report")
        assert resp.status_code == 404


class TestBundleEndpoints:
    def test_bundle_stub(self, client):
        client.post("/runs", json={
            "run_id": "bundle-run",
            "demo_id": "demo",
            "namespace": "ns",
            "requested_by": "user",
            "rubric_version": "v0.1.0",
        })
        resp = client.get("/runs/bundle-run/bundle")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "bundle-run"
        assert isinstance(data["history"], list)
        assert "failure_frequency" in data
        assert "last_passing_run" in data
