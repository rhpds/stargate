"""End-to-End Synthetic Flow — full API flow with emulator data.

RED/GREEN TDD: tests written first, then wired to pass.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "stargate-synthetic-client-emulator"))

from tests.conftest import client, db


class TestEndToEndFlow:
    def test_full_flow_create_run_and_evaluate(self, client, db):
        """Create a run, submit evidence, evaluate — full API flow."""
        # Create run
        resp = client.post("/runs", json={
            "demo_id": "synthetic-test",
            "namespace": "sandbox-syn-001",
            "requested_by": "emulator",
            "rubric_version": "v0.1.0",
        })
        assert resp.status_code == 201
        run_id = resp.json()["run_id"]

        # Start a stage
        resp = client.post(f"/runs/{run_id}/stages/namespace-ready/start")
        assert resp.status_code == 201

        # Submit evidence from emulator
        from emulator.scenarios import get_scenario
        scenario = get_scenario("healthy-baseline")
        evidence = scenario.generate_evidence()
        ns_evidence = evidence["namespace-ready"]

        resp = client.post(f"/runs/{run_id}/stages/namespace-ready/evidence", json={
            "type": "synthetic",
            "source": "emulator",
            "observed": ns_evidence,
            "result": "pass",
        })
        assert resp.status_code == 201

        # Evaluate
        resp = client.post(f"/runs/{run_id}/stages/namespace-ready/evaluate", json={
            "evidence": ns_evidence,
        })
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "pass"

    def test_full_flow_failure_scenario(self, client, db):
        """node-failure scenario produces FAIL on cluster-health."""
        from emulator.scenarios import get_scenario
        scenario = get_scenario("node-failure")
        evidence = scenario.generate_evidence()

        resp = client.post("/runs", json={
            "demo_id": "syn-node-failure",
            "namespace": "sandbox-syn-002",
            "requested_by": "emulator",
            "rubric_version": "v0.1.0",
        })
        run_id = resp.json()["run_id"]

        client.post(f"/runs/{run_id}/stages/cluster-health/start")
        resp = client.post(f"/runs/{run_id}/stages/cluster-health/evaluate", json={
            "evidence": evidence["cluster-health"],
        })
        assert resp.status_code == 200
        assert resp.json()["outcome"] == "fail"
        assert resp.json()["failure_class"] is not None

    def test_full_flow_with_dry_run(self, client, db):
        """Enable dry-run → action logged but not executed."""
        from api.action_executor import execute_action
        from api.routers import _shared

        # Enable dry-run
        client.post("/admin/dry-run", json={"enabled": True})

        result = execute_action("test_action", "test_target", {"test": True}, confidence=0.95, db=db)
        assert result["executed"] is False
        assert result["reason"] == "dry_run"

        # Verify audit entry exists
        resp = client.get("/admin/audit")
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert any(e["action_type"] == "test_action" for e in entries)

        # Cleanup
        client.post("/admin/dry-run", json={"enabled": False})

    def test_full_flow_with_confidence_gate(self, client, db):
        """Low confidence → queued → approve → audit shows approved."""
        from api.action_executor import execute_action

        result = execute_action("low_conf_action", "target", {}, confidence=0.3, db=db)
        assert result["executed"] is False
        assert result["reason"] == "low_confidence"
        pending_id = result.get("pending_id")
        assert pending_id is not None

        # Check approval queue
        resp = client.get("/admin/approval-queue")
        pending = resp.json()["pending"]
        assert any(p["id"] == pending_id for p in pending)

        # Approve
        resp = client.post(f"/admin/approval-queue/{pending_id}/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
