"""API contract tests — test all endpoints against the spec."""

import pytest

P = "/api/v1"


class TestRunEndpoints:
    def test_create_run(self, client):
        resp = client.post(f"{P}/runs", json={
            "run_id": "test-run-001",
            "demo_id": "demo-simple-container",
            "namespace": "summit-demo-001",
            "requested_by": "test-user",
            "rubric_version": "v0.1.0",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["run_id"] == "test-run-001"
        assert data["status"] == "pending"

    def test_create_run_auto_id(self, client):
        resp = client.post(f"{P}/runs", json={
            "demo_id": "demo-simple-container",
            "namespace": "summit-demo-001",
            "requested_by": "test-user",
            "rubric_version": "v0.1.0",
        })
        assert resp.status_code == 201
        assert resp.json()["run_id"].startswith("demo-simple-container-")

    def test_create_run_duplicate(self, client):
        payload = {
            "run_id": "dup-run",
            "demo_id": "demo-simple-container",
            "namespace": "ns",
            "requested_by": "user",
            "rubric_version": "v0.1.0",
        }
        client.post(f"{P}/runs", json=payload)
        resp = client.post(f"{P}/runs", json=payload)
        assert resp.status_code == 409

    def test_get_run(self, client):
        client.post(f"{P}/runs", json={
            "run_id": "get-run-001",
            "demo_id": "demo-simple-container",
            "namespace": "ns",
            "requested_by": "user",
            "rubric_version": "v0.1.0",
        })
        resp = client.get(f"{P}/runs/get-run-001")
        assert resp.status_code == 200
        assert resp.json()["run_id"] == "get-run-001"

    def test_get_run_not_found(self, client):
        resp = client.get(f"{P}/runs/nonexistent")
        assert resp.status_code == 404

    def test_list_runs(self, client):
        for i in range(3):
            client.post(f"{P}/runs", json={
                "run_id": f"list-run-{i}",
                "demo_id": "demo",
                "namespace": "ns",
                "requested_by": "user",
                "rubric_version": "v0.1.0",
            })
        resp = client.get(f"{P}/runs")
        assert resp.status_code == 200
        assert len(resp.json()) == 3


class TestStageEndpoints:
    def _create_run(self, client):
        client.post(f"{P}/runs", json={
            "run_id": "stage-test-run",
            "demo_id": "demo-simple-container",
            "namespace": "ns",
            "requested_by": "user",
            "rubric_version": "v0.1.0",
        })

    def test_start_stage(self, client):
        self._create_run(client)
        resp = client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/start")
        assert resp.status_code == 201
        data = resp.json()
        assert data["stage_id"] == "namespace-ready"
        assert data["status"] == "running"
        assert data["started_at"] is not None

    def test_start_stage_promotes_run_to_running(self, client):
        self._create_run(client)
        client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/start")
        resp = client.get(f"{P}/runs/stage-test-run")
        assert resp.json()["status"] == "running"

    def test_start_stage_duplicate(self, client):
        self._create_run(client)
        client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/start")
        resp = client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/start")
        assert resp.status_code == 409

    def test_start_stage_run_not_found(self, client):
        resp = client.post(f"{P}/runs/nonexistent/stages/ns-ready/start")
        assert resp.status_code == 404

    def test_submit_evidence(self, client):
        self._create_run(client)
        client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/start")
        resp = client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/evidence", json={
            "type": "fixture",
            "source": "test",
            "observed": {"namespace_exists": True},
            "result": "pass",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["observed"]["namespace_exists"] is True
        assert data["result"] == "pass"

    def test_submit_evidence_stage_not_found(self, client):
        self._create_run(client)
        resp = client.post(f"{P}/runs/stage-test-run/stages/nonexistent/evidence", json={
            "type": "fixture",
            "source": "test",
            "observed": {},
            "result": "pass",
        })
        assert resp.status_code == 404

    def test_evaluate_stage_with_inline_evidence(self, client):
        self._create_run(client)
        client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/start")
        resp = client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/evaluate", json={
            "evidence": {"namespace_exists": True},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome"] == "pass"

    def test_evaluate_stage_fail(self, client):
        self._create_run(client)
        client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/start")
        resp = client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/evaluate", json={
            "evidence": {"namespace_exists": False},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["outcome"] == "fail"
        assert data["failure_class"] == "namespace_missing"

    def test_complete_stage(self, client):
        self._create_run(client)
        client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/start")
        client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/evaluate", json={
            "evidence": {"namespace_exists": True},
        })
        resp = client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/complete")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "passed"
        assert data["completed_at"] is not None
        assert data["duration_seconds"] is not None

    def test_complete_stage_without_evaluation_blocked(self, client):
        self._create_run(client)
        client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/start")
        resp = client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/complete")
        assert resp.status_code == 409
        assert "not been evaluated" in resp.json()["detail"]

    def test_submit_evidence_after_completion_blocked(self, client):
        self._create_run(client)
        client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/start")
        client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/evaluate", json={
            "evidence": {"namespace_exists": True},
        })
        client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/complete")
        resp = client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/evidence", json={
            "type": "fixture", "source": "test", "observed": {}, "result": "pass",
        })
        assert resp.status_code == 409
        assert "already completed" in resp.json()["detail"]

    def test_evaluate_updates_stage_status(self, client):
        self._create_run(client)
        client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/start")
        client.post(f"{P}/runs/stage-test-run/stages/namespace-ready/evaluate", json={
            "evidence": {"namespace_exists": True},
        })
        resp = client.get(f"{P}/runs/stage-test-run/report")
        stage = resp.json()["stages"][0]
        assert stage["outcome"] == "pass"


class TestRubricEndpoints:
    def test_validate_rubric_valid(self, client):
        resp = client.post(f"{P}/rubrics/validate", json={
            "rubric": {
                "id": "test-rubric",
                "version": "v0.1.0",
                "stage": "test-stage",
                "exit_criteria": [{"name": "check_one", "required": True}],
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["rubric_id"] == "test-rubric"

    def test_validate_rubric_invalid(self, client):
        resp = client.post(f"{P}/rubrics/validate", json={
            "rubric": {"version": "v0.1.0"},
        })
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    def test_get_rubric(self, client):
        resp = client.get(f"{P}/rubrics/namespace-ready")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "namespace-ready"

    def test_get_rubric_not_found(self, client):
        resp = client.get(f"{P}/rubrics/nonexistent-stage")
        assert resp.status_code == 404

    def test_evaluate_rubric_directly(self, client):
        resp = client.post(f"{P}/rubrics/namespace-ready/evaluate", json={
            "evidence": {"namespace_exists": True},
        })
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "pass"


class TestReportEndpoints:
    def _setup_run_with_stages(self, client):
        client.post(f"{P}/runs", json={
            "run_id": "report-run",
            "demo_id": "demo-simple-container",
            "namespace": "ns",
            "requested_by": "user",
            "rubric_version": "v0.1.0",
        })
        client.post(f"{P}/runs/report-run/stages/namespace-ready/start")
        client.post(f"{P}/runs/report-run/stages/namespace-ready/evidence", json={
            "type": "fixture",
            "source": "test",
            "observed": {"namespace_exists": True},
            "result": "pass",
        })
        client.post(f"{P}/runs/report-run/stages/namespace-ready/evaluate", json={
            "evidence": {"namespace_exists": True},
        })
        client.post(f"{P}/runs/report-run/stages/namespace-ready/complete")

    def test_run_report(self, client):
        self._setup_run_with_stages(client)
        resp = client.get(f"{P}/runs/report-run/report")
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == "report-run"
        assert data["passed"] == 1
        assert len(data["stages"]) == 1
        assert data["stages"][0]["outcome"] == "pass"
        assert data["stages"][0]["evidence_count"] == 1

    def test_run_report_not_found(self, client):
        resp = client.get(f"{P}/runs/nonexistent/report")
        assert resp.status_code == 404

    def test_bottlenecks(self, client):
        self._setup_run_with_stages(client)
        resp = client.get(f"{P}/runs/report-run/bottlenecks")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["stage_id"] == "namespace-ready"


class TestAIProposalEndpoints:
    def _setup_failed_run(self, client):
        client.post(f"{P}/runs", json={
            "run_id": "ai-run",
            "demo_id": "demo-simple-container",
            "namespace": "ns",
            "requested_by": "user",
            "rubric_version": "v0.1.0",
        })
        client.post(f"{P}/runs/ai-run/stages/namespace-ready/start")
        client.post(f"{P}/runs/ai-run/stages/namespace-ready/evidence", json={
            "type": "fixture",
            "source": "test",
            "observed": {"namespace_exists": False},
            "result": "fail",
        })
        client.post(f"{P}/runs/ai-run/stages/namespace-ready/evaluate", json={
            "evidence": {"namespace_exists": False},
        })
        client.post(f"{P}/runs/ai-run/stages/namespace-ready/complete")

    def test_failure_summary(self, client):
        self._setup_failed_run(client)
        resp = client.post(f"{P}/runs/ai-run/proposals/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "proposed"
        assert data["approved"] is False
        assert data["requires_human_review"] is True
        assert "namespace-ready" in data["failed_stages"]

    def test_failure_summary_not_found(self, client):
        resp = client.post(f"{P}/runs/nonexistent/proposals/summary")
        assert resp.status_code == 404

    def test_pr_text_generation(self, client):
        self._setup_failed_run(client)
        resp = client.post(f"{P}/runs/ai-run/proposals/pr-text")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "proposed"
        assert data["approved"] is False
        assert data["requires_human_review"] is True
        assert "ai-run" in data["title"]
        assert len(data["body"]) > 0

    def test_rubric_diffs(self, client):
        self._setup_failed_run(client)
        resp = client.post(f"{P}/runs/ai-run/proposals/rubric-diffs")
        assert resp.status_code == 200
        data = resp.json()
        assert "proposals" in data
        assert "count" in data


class TestIntegrationEndpoints:
    def test_receive_launchpad_event(self, client):
        resp = client.post("/integration/events", json={
            "source": "launchpad",
            "event_type": "session_provisioned",
            "event_id": "evt-001",
            "timestamp": "2026-05-25T12:00:00Z",
            "payload": {
                "session_id": "sess-001",
                "lab_code": "inference-overdrive",
                "cluster_name": "infra01",
                "outcome": "pass",
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["received"] is True
        assert data["run_id"] == "launchpad-sess-001"

    def test_receive_unknown_source(self, client):
        resp = client.post("/integration/events", json={
            "source": 
            "event_type": "test",
            "event_id": "evt-002",
            "timestamp": "2026-05-25T12:00:00Z",
            "payload": {},
        })
        assert resp.status_code == 200
        assert resp.json()["processed"] is False

    def test_evaluate_provision(self, client):
        resp = client.get("/integration/evaluate", params={
            "catalog_item": "inference-overdrive",
            "tenant": "test-tenant",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["allowed"] is True
        assert data["level"] == "allowed"

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["service"] == "stargate"
