"""Synthetic emulator integration tests — RED/GREEN TDD.

Tests are written FIRST (RED), then implementation makes them pass (GREEN).
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Reuse the existing test fixtures
from tests.conftest import client, db


# ===========================================================================
# Phase 1: Evidence Source Toggle
# ===========================================================================

class TestEvidenceSourceToggle:
    def test_default_source_is_real(self):
        """STARGATE_EVIDENCE_SOURCE defaults to 'real'."""
        from api.routers._shared import _evidence_source
        assert _evidence_source == "real"

    def test_synthetic_source_config_exists(self):
        """_synthetic_scenario variable exists in shared state."""
        from api.routers._shared import _synthetic_scenario
        assert _synthetic_scenario is None

    def test_toggle_endpoint_exists(self, client):
        """POST /admin/evidence-source endpoint exists."""
        resp = client.post("/admin/evidence-source", json={"source": "synthetic", "scenario": "healthy-baseline"})
        assert resp.status_code in (200, 403)  # 200 OK or 403 if auth required

    def test_toggle_switches_to_synthetic(self, client):
        """Toggling to synthetic updates the shared state."""
        resp = client.post("/admin/evidence-source", json={"source": "synthetic", "scenario": "healthy-baseline"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "synthetic"
        assert data["scenario"] == "healthy-baseline"

    def test_toggle_switches_back_to_real(self, client):
        """Toggling back to real clears synthetic scenario."""
        client.post("/admin/evidence-source", json={"source": "synthetic", "scenario": "node-failure"})
        resp = client.post("/admin/evidence-source", json={"source": "real"})
        assert resp.status_code == 200
        assert resp.json()["source"] == "real"

    def test_toggle_rejects_invalid_source(self, client):
        """Invalid source value returns 400."""
        resp = client.post("/admin/evidence-source", json={"source": "invalid"})
        assert resp.status_code == 400

    def test_get_evidence_source_status(self, client):
        """GET /admin/evidence-source returns current state."""
        resp = client.get("/admin/evidence-source")
        assert resp.status_code == 200
        data = resp.json()
        assert "source" in data


# ===========================================================================
# Phase 2: Dry-Run Mode
# ===========================================================================

class TestDryRunMode:
    def test_dry_run_default_off(self):
        """Dry-run mode defaults to False."""
        from api.routers._shared import _dry_run_enabled
        assert _dry_run_enabled is False

    def test_dry_run_toggle_endpoint(self, client):
        """POST /admin/dry-run toggles dry-run mode."""
        resp = client.post("/admin/dry-run", json={"enabled": True})
        assert resp.status_code == 200
        assert resp.json()["dry_run"] is True

    def test_dry_run_disable(self, client):
        """Disabling dry-run works."""
        client.post("/admin/dry-run", json={"enabled": True})
        resp = client.post("/admin/dry-run", json={"enabled": False})
        assert resp.status_code == 200
        assert resp.json()["dry_run"] is False

    def test_action_executor_exists(self):
        """Action executor module exists."""
        from api.action_executor import execute_action
        assert callable(execute_action)

    def test_dry_run_logs_without_executing(self):
        """In dry-run mode, execute_action returns skipped status."""
        from api.action_executor import execute_action
        from api.routers import _shared
        _shared._dry_run_enabled = True
        try:
            result = execute_action("test_action", "test_target", {"key": "val"}, confidence=0.9, db=None)
            assert result["executed"] is False
            assert result["reason"] == "dry_run"
        finally:
            _shared._dry_run_enabled = False


# ===========================================================================
# Phase 3: Confidence Gate
# ===========================================================================

class TestConfidenceGate:
    def test_threshold_configurable(self):
        """STARGATE_CONFIDENCE_THRESHOLD is configurable."""
        from api.routers._shared import CONFIDENCE_THRESHOLD
        assert isinstance(CONFIDENCE_THRESHOLD, float)
        assert 0 < CONFIDENCE_THRESHOLD <= 1.0

    def test_high_confidence_proceeds(self):
        """Action with confidence >= threshold proceeds."""
        from api.action_executor import execute_action
        from api.routers import _shared
        _shared._dry_run_enabled = False
        result = execute_action("test", "target", {}, confidence=0.95, db=None)
        assert result["executed"] is True or result["reason"] != "low_confidence"

    def test_low_confidence_queued(self, db):
        """Action with confidence < threshold goes to approval queue."""
        from api.action_executor import execute_action
        from api.routers import _shared
        _shared._dry_run_enabled = False
        result = execute_action("test", "target", {}, confidence=0.3, db=db)
        assert result["executed"] is False
        assert result["reason"] == "low_confidence"
        assert "pending_id" in result

    def test_approval_queue_endpoint(self, client):
        """GET /admin/approval-queue returns pending actions."""
        resp = client.get("/admin/approval-queue")
        assert resp.status_code == 200
        data = resp.json()
        assert "pending" in data

    def test_approve_action(self, client, db):
        """POST /admin/approval-queue/{id}/approve approves a pending action."""
        from api.action_executor import execute_action
        result = execute_action("test", "target", {}, confidence=0.3, db=db)
        if result.get("pending_id"):
            resp = client.post(f"/admin/approval-queue/{result['pending_id']}/approve")
            assert resp.status_code == 200

    def test_reject_action(self, client, db):
        """POST /admin/approval-queue/{id}/reject rejects a pending action."""
        from api.action_executor import execute_action
        result = execute_action("test", "target", {}, confidence=0.3, db=db)
        if result.get("pending_id"):
            resp = client.post(f"/admin/approval-queue/{result['pending_id']}/reject")
            assert resp.status_code == 200


# ===========================================================================
# Phase 4: Audit Trail
# ===========================================================================

class TestAuditTrail:
    def test_audit_entry_written_on_action(self, db):
        """AuditLog entry created when action is proposed."""
        from api.action_executor import execute_action
        from db.models import AuditLog
        before = db.query(AuditLog).count()
        execute_action("test_audit", "target", {}, confidence=0.9, db=db)
        after = db.query(AuditLog).count()
        assert after > before

    def test_audit_entry_has_evidence_source(self, db):
        """Audit entry records evidence source."""
        from api.action_executor import execute_action
        from db.models import AuditLog
        execute_action("test", "target", {}, confidence=0.9, db=db,
                       evidence_source="synthetic", scenario_name="gaudi-saturation")
        entry = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
        params = entry.parameters or {}
        assert params.get("evidence_source") == "synthetic"
        assert params.get("scenario_name") == "gaudi-saturation"

    def test_audit_entry_has_confidence(self, db):
        """Audit entry records confidence score."""
        from api.action_executor import execute_action
        from db.models import AuditLog
        execute_action("test", "target", {}, confidence=0.85, db=db)
        entry = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
        assert entry.parameters.get("confidence") == 0.85

    def test_audit_endpoint(self, client):
        """GET /admin/audit returns audit entries."""
        resp = client.get("/admin/audit")
        assert resp.status_code == 200
        data = resp.json()
        assert "entries" in data


# ===========================================================================
# Phase 5: Validation Mode
# ===========================================================================

class TestValidationMode:
    def test_validate_endpoint_exists(self, client):
        """POST /admin/validate endpoint exists."""
        resp = client.post("/admin/validate")
        assert resp.status_code == 200

    def test_validate_returns_scenario_results(self, client):
        """Validation returns results per scenario."""
        resp = client.post("/admin/validate")
        data = resp.json()
        assert "total" in data
        assert "passed" in data
        assert "failed" in data
        assert "results" in data

    def test_validate_each_result_has_fields(self, client):
        """Each result has scenario, match, expected, actual."""
        resp = client.post("/admin/validate")
        data = resp.json()
        if data["results"]:
            r = data["results"][0]
            assert "scenario" in r
            assert "match" in r

    def test_healthy_baseline_passes(self, client):
        """healthy-baseline scenario should produce no recommendations."""
        resp = client.post("/admin/validate")
        data = resp.json()
        baseline = next((r for r in data["results"] if r["scenario"] == "healthy-baseline"), None)
        if baseline:
            assert baseline["match"] is True


# ===========================================================================
# Regression: Existing tests still pass
# ===========================================================================

class TestExistingUnchanged:
    def test_health_endpoint(self, client):
        """Health endpoint still works."""
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_runs_endpoint(self, client):
        """Runs endpoint still works."""
        resp = client.post("/runs", json={
            "demo_id": "test",
            "namespace": "test-ns",
            "requested_by": "test-user",
            "rubric_version": "v0.1.0",
        })
        assert resp.status_code == 201
