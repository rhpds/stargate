"""API tests for integration, dashboard, events, and constraints endpoints."""

import pytest


class TestExternalEvidence:
    def test_receive_external_evidence(self, client):
        resp = client.post("/integration/external-evidence", json={
            "source": "demolition",
            "session_id": 42,
            "session_name": "LB1088 load test",
            "lab_code": "LB1088",
            "cluster_name": "ocpv06",
            "outcome": "fail",
            "steps_passed": 10,
            "steps_failed": 3,
            "error_summary": "Step 5 timeout",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["source"] == "demolition"
        assert data["outcome"] == "fail"
        assert "run_id" in data

    def test_receive_passing_evidence(self, client):
        resp = client.post("/integration/external-evidence", json={
            "source": "demolition",
            "outcome": "pass",
            "lab_code": "LB9999",
        })
        assert resp.status_code == 201
        assert resp.json()["outcome"] == "pass"


class TestFeedback:
    def _create_evaluation(self, client):
        client.post("/runs", json={
            "run_id": "feedback-run",
            "demo_id": "demo",
            "namespace": "ns",
            "requested_by": "test",
            "rubric_version": "v0.1.0",
        })
        client.post("/runs/feedback-run/stages/namespace-ready/start")
        client.post("/runs/feedback-run/stages/namespace-ready/evaluate", json={
            "evidence": {"namespace_exists": False},
        })

    def test_submit_feedback(self, client):
        self._create_evaluation(client)
        resp = client.post("/integration/feedback/feedback-run", json={
            "action_taken": "deleted and recreated namespace",
            "worked": True,
            "correct_classification": True,
            "reviewed_by": "ops-user",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["evaluations_updated"] == 1
        assert data["feedback"]["worked"] is True

    def test_submit_correction(self, client):
        self._create_evaluation(client)
        resp = client.post("/integration/feedback/feedback-run", json={
            "correct_classification": False,
            "corrected_class": "network_issue",
            "notes": "Was actually a network partition",
        })
        assert resp.status_code == 200

    def test_feedback_not_found(self, client):
        resp = client.post("/integration/feedback/nonexistent", json={
            "worked": True,
        })
        assert resp.status_code == 404


class TestLabStatus:
    def _seed(self, client):
        for i in range(3):
            client.post("/runs", json={
                "run_id": f"status-run-{i}",
                "demo_id": "demo",
                "namespace": "ns",
                "requested_by": "test",
                "rubric_version": "v0.1.0",
                "lab_code": "LB-TEST",
                "cluster_name": "ocpv06",
            })
            client.post(f"/runs/status-run-{i}/stages/namespace-ready/start")
            evidence = {"namespace_exists": True} if i < 2 else {"namespace_exists": False}
            client.post(f"/runs/status-run-{i}/stages/namespace-ready/evaluate", json={
                "evidence": evidence,
            })

    def test_lab_status(self, client):
        self._seed(client)
        resp = client.get("/integration/lab-status/LB-TEST")
        assert resp.status_code == 200
        data = resp.json()
        assert data["lab_code"] == "LB-TEST"
        assert data["total_evaluations"] > 0
        assert "latest_outcome" in data
        assert "failure_classes" in data
        assert "history" in data

    def test_lab_status_not_found(self, client):
        resp = client.get("/integration/lab-status/NONEXISTENT")
        assert resp.status_code == 404


class TestDashboardClusters:
    def test_clusters_dashboard(self, client):
        resp = client.get("/dashboard/clusters")
        assert resp.status_code == 200
        data = resp.json()
        assert "clusters" in data
        assert "timestamp" in data


class TestDashboardSummit:
    def test_summit_dashboard(self, client):
        resp = client.get("/dashboard/summit")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_labs" in data
        assert "labs" in data
        assert isinstance(data["labs"], list)


class TestDashboardLab:
    def test_lab_dashboard(self, client):
        resp = client.get("/dashboard/lab/LB1088")
        assert resp.status_code == 200
        data = resp.json()
        assert data["lab_code"] == "LB1088"
        assert "stargate" in data
        assert "constraints" in data or data["constraints"] is None
        assert "demolition" in data
        assert "recent_events" in data


class TestEventsAPI:
    def _generate_events(self, client):
        client.post("/runs", json={
            "run_id": "event-run",
            "demo_id": "demo",
            "namespace": "ns",
            "requested_by": "test",
            "rubric_version": "v0.1.0",
            "lab_code": "EVT-LAB",
            "cluster_name": "test-cluster",
        })
        client.post("/runs/event-run/stages/namespace-ready/start")
        client.post("/runs/event-run/stages/namespace-ready/evaluate", json={
            "evidence": {"namespace_exists": False},
        })

    def test_get_events(self, client):
        self._generate_events(client)
        resp = client.get("/events")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_events_summary(self, client):
        self._generate_events(client)
        resp = client.get("/events/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_events" in data
        assert "filtered" in data
        assert "by_type" in data

    def test_register_consumer(self, client):
        resp = client.post("/events/consumers", json={
            "url": "https://hooks.slack.com/test",
            "event_types": ["evaluation.failed"],
        })
        assert resp.status_code == 200
        assert resp.json()["registered"] is True

    def test_register_consumer_no_url(self, client):
        resp = client.post("/events/consumers", json={})
        assert resp.status_code == 422


class TestConstraintsAPI:
    def test_get_all_constraints(self, client):
        resp = client.get("/constraints")
        assert resp.status_code == 200

    def test_get_lab_constraints_not_found(self, client):
        resp = client.get("/constraints/NONEXISTENT-LAB-XYZ")
        assert resp.status_code == 404
