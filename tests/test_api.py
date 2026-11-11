"""API contract tests — test all endpoints against the spec."""

import pytest


class TestHealth:
    def test_health(self, client, monkeypatch):
        from api.routers import health

        monkeypatch.setattr(health, "_check_executor_kubeconfig", lambda: "not_configured")
        monkeypatch.setattr(health, "_check_sandbox_api", lambda: "not_configured")
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded", "error")
        assert "components" in data
        assert data["components"]["api"] == "ok"
        assert data["components"]["database"] == "ok"


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

    def test_create_run_race_returns_existing(self, client, db, monkeypatch):
        """Two concurrent POSTs for the same run_id: the loser of the INSERT
        race gets an idempotent success, not a 500 that drops the whole scan
        cycle (~4/hour observed in production, Nov 11 2026)."""
        from db import repository as repo_module
        from db.models import RunRecord

        db.add(RunRecord(
            run_id="race-run", demo_id="demo", namespace="ns",
            requested_by="user", status="pending", rubric_version="v0.1.0",
        ))
        db.commit()

        real_get_run = repo_module.get_run
        calls = {"n": 0}

        def _racy_get_run(db_arg, run_id):
            calls["n"] += 1
            if calls["n"] == 1:
                return None  # pre-check misses: concurrent insert in flight
            return real_get_run(db_arg, run_id)

        monkeypatch.setattr(repo_module, "get_run", _racy_get_run)

        resp = client.post("/runs", json={
            "run_id": "race-run",
            "demo_id": "demo",
            "namespace": "ns",
            "requested_by": "user",
            "rubric_version": "v0.1.0",
        })
        assert resp.status_code == 201
        assert resp.json()["run_id"] == "race-run"
        assert calls["n"] == 2  # pre-check + race re-fetch

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

    def test_submit_evidence_server_id_is_full_uuid_width(self, client):
        """Server-generated evidence ids must use the full 32-hex uuid4 space.
        The original 8-hex prefix collided once the table passed ~70M rows
        (Nov 2026): ~1.6% of inserts died on ix_evidence_evidence_id and the
        evidence was silently dropped (scanner does not retry evidence POSTs).
        """
        import re
        self._setup(client)
        resp = client.post("/runs/ev-test-run/stages/namespace-ready/evidence", json={
            "type": "resource_state",
            "source": "oc",
            "observed": {"namespace_exists": True},
            "result": "pass",
        })
        assert resp.status_code == 201
        assert re.fullmatch(r"ev-[0-9a-f]{32}", resp.json()["evidence_id"])

    def test_submit_evidence_duplicate_client_id_is_409(self, client):
        """A client-supplied duplicate evidence_id is a 409, not a 500."""
        self._setup(client)
        body = {
            "type": "resource_state",
            "source": "oc",
            "observed": {"namespace_exists": True},
            "result": "pass",
            "evidence_id": "ev-client-supplied-dup",
        }
        assert client.post("/runs/ev-test-run/stages/namespace-ready/evidence", json=body).status_code == 201
        resp = client.post("/runs/ev-test-run/stages/namespace-ready/evidence", json=body)
        assert resp.status_code == 409

    def test_submit_evidence_server_collision_redraws(self, client, monkeypatch):
        """A server-side id collision must redraw instead of dropping the
        evidence with a 500. Forces the first draw to collide with a
        pre-existing row; the retry must succeed with the second draw."""
        from api.routers import runs as runs_module

        class _FakeUUID:
            def __init__(self, hexstr):
                self.hex = hexstr

        self._setup(client)
        # pre-existing row occupying the id the first draw will produce
        seeded = client.post("/runs/ev-test-run/stages/namespace-ready/evidence", json={
            "type": "resource_state",
            "source": "oc",
            "observed": {"namespace_exists": True},
            "result": "pass",
            "evidence_id": "ev-" + "a" * 32,
        })
        assert seeded.status_code == 201

        draws = iter([_FakeUUID("a" * 32), _FakeUUID("b" * 32)])
        monkeypatch.setattr(runs_module, "uuid4", lambda: next(draws))

        resp = client.post("/runs/ev-test-run/stages/namespace-ready/evidence", json={
            "type": "resource_state",
            "source": "oc",
            "observed": {"namespace_exists": True},
            "result": "pass",
        })
        assert resp.status_code == 201
        assert resp.json()["evidence_id"] == "ev-" + "b" * 32


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
