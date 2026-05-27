"""E2E Integration tests — StarGate ↔ Launchpad ↔ DeepField.

Validates integration contracts: event ingestion, rubric evaluation, push notifications.
"""

import pytest


class TestIntegrationEndpoints:
    def test_receive_launchpad_event(self, client):
        resp = client.post("/integration/events", json={
            "source": "launchpad",
            "event_type": "session.provisioning",
            "event_id": "int-test-001",
            "timestamp": "2026-05-27T12:00:00Z",
            "payload": {
                "session_id": "int-sess-001",
                "lab_code": "inference-overdrive",
                "cluster_name": "infra01",
                "outcome": "pass",
            },
        })
        assert resp.status_code == 200
        assert resp.json()["received"] is True

    def test_evaluate_provision_allows(self, client):
        resp = client.get("/integration/evaluate", params={
            "catalog_item": "inference-overdrive",
            "tenant": "test-tenant",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["allowed"] is True

    def test_duplicate_event_rejected(self, client):
        event = {
            "source": "launchpad",
            "event_type": "test",
            "event_id": "dedup-test-001",
            "timestamp": "2026-05-27T12:00:00Z",
            "payload": {"session_id": "dedup-sess"},
        }
        resp1 = client.post("/integration/events", json=event)
        assert resp1.status_code == 200

        resp2 = client.post("/integration/events", json=event)
        assert resp2.status_code == 200
        assert resp2.json().get("duplicate") is True


class TestRubricEvaluation:
    def test_all_rubrics_loadable(self, client):
        for rubric in ["namespace-ready", "deployment-ready", "route-ready"]:
            resp = client.get(f"/api/v1/rubrics/{rubric}")
            assert resp.status_code == 200
            assert resp.json()["id"] == rubric

    def test_namespace_ready_pass(self, client):
        resp = client.post("/api/v1/rubrics/namespace-ready/evaluate", json={
            "evidence": {"namespace_exists": True},
        })
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "pass"

    def test_namespace_ready_fail(self, client):
        resp = client.post("/api/v1/rubrics/namespace-ready/evaluate", json={
            "evidence": {"namespace_exists": False},
        })
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "fail"
        assert resp.json()["failure_class"] == "namespace_missing"


class TestLLMAudit:
    def test_audit_module_importable(self):
        from api.app.integrations.llm_audit import log_llm_call, get_llm_audit_log
        log_llm_call("test-model", "prompt", "output", 100.0, caller="test")
        assert len(get_llm_audit_log()) >= 1
