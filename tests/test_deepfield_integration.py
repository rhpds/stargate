"""RED/GREEN TDD: tests written FIRST. Implementation doesn't exist yet.

Tests for the Deepfield <-> StarGate integration:
  A. Enriched outbound payload (DeepFieldConsumer includes all fields)
  B. Deepfield incident ingestion endpoint (POST /integration/deepfield-incident)
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from events.models import Event
from events.consumers import DeepFieldConsumer


# ---------------------------------------------------------------------------
# A. Enriched outbound payload tests
# ---------------------------------------------------------------------------

class TestDeepFieldConsumerPayload:
    """DeepFieldConsumer.deliver() must include every enrichment field."""

    def _capture_payload(self, event: Event) -> dict:
        """Deliver an event through DeepFieldConsumer and return the JSON payload."""
        consumer = DeepFieldConsumer(url="http://deepfield.test")
        captured = {}

        def _mock_urlopen(req, timeout=10):
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return MagicMock(status=200)

        with patch("events.consumers.urllib.request.urlopen", side_effect=_mock_urlopen):
            consumer.deliver(event)

        return captured.get("payload", {})

    def test_payload_includes_namespace(self):
        event = Event(
            event_type="evaluation.failed",
            run_id="run-001",
            stage_id="stage-1",
            cluster_name="ocpv05",
            namespace="sandbox-abc-ocp4-cluster",
        )
        payload = self._capture_payload(event)
        assert payload["payload"]["namespace"] == "sandbox-abc-ocp4-cluster"

    def test_payload_includes_message(self):
        event = Event(
            event_type="evaluation.failed",
            run_id="run-002",
            message="Readiness probe failed: connection refused",
        )
        payload = self._capture_payload(event)
        assert payload["payload"]["message"] == "Readiness probe failed: connection refused"

    def test_payload_includes_priority(self):
        event = Event(
            event_type="evaluation.failed",
            run_id="run-003",
            priority=0.8,
        )
        payload = self._capture_payload(event)
        assert payload["payload"]["priority"] == 0.8

    def test_payload_includes_systemic(self):
        event = Event(
            event_type="evaluation.failed",
            run_id="run-004",
            systemic=True,
        )
        payload = self._capture_payload(event)
        assert payload["payload"]["systemic"] is True

    def test_payload_includes_blast_radius(self):
        br = {"total_events": 5, "labs_affected": ["lab1"]}
        event = Event(
            event_type="evaluation.failed",
            run_id="run-005",
            blast_radius=br,
        )
        payload = self._capture_payload(event)
        assert payload["payload"]["blast_radius"] == br

    def test_payload_namespace_falls_back_to_metadata(self):
        event = Event(
            event_type="evaluation.failed",
            run_id="run-006",
            metadata={"namespace": "meta-ns"},
        )
        payload = self._capture_payload(event)
        assert payload["payload"]["namespace"] == "meta-ns"


# ---------------------------------------------------------------------------
# B. Deepfield incident ingestion endpoint tests
# ---------------------------------------------------------------------------

class TestDeepfieldIncidentEndpoint:
    """POST /integration/deepfield-incident ingestion tests."""

    def test_incident_creates_pending_action(self, client, db):
        resp = client.post("/integration/deepfield-incident", json={
            "incident_id": "inc-001",
            "namespace": "sandbox-xyz",
            "cluster": "ocpv05",
            "failure_class": "readiness_probe",
            "confidence": 0.9,
            "rca_output": "Pod not ready due to CrashLoopBackOff",
            "evidence_chain": [{"signal": "pod restart count > 5"}],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "queued_for_approval"
        assert data["target"] == "sandbox-xyz"
        assert data["confidence"] == 0.9

        # Verify PendingAction in DB
        from db.models import PendingAction
        pa = db.query(PendingAction).filter(
            PendingAction.source_event_id == "inc-001",
        ).first()
        assert pa is not None
        assert pa.proposed_by == "deepfield"
        assert pa.status == "pending"

    def test_incident_no_auto_remediation(self, client, db):
        resp = client.post("/integration/deepfield-incident", json={
            "incident_id": "inc-002",
            "namespace": "sandbox-auto",
            "confidence": 0.95,
            "remediation_options": [{"action": "delete pod"}],
        })
        assert resp.status_code == 201

        from db.models import PendingAction
        pa = db.query(PendingAction).filter(
            PendingAction.source_event_id == "inc-002",
        ).first()
        assert pa is not None
        # Must NEVER be approved or executing
        assert pa.status == "pending"
        assert pa.status != "approved"
        assert pa.status != "executing"

    def test_incident_requires_incident_id(self, client):
        resp = client.post("/integration/deepfield-incident", json={
            "namespace": "sandbox-xyz",
        })
        assert resp.status_code == 422

    def test_incident_requires_namespace(self, client):
        resp = client.post("/integration/deepfield-incident", json={
            "incident_id": "inc-003",
        })
        assert resp.status_code == 422

    def test_incident_stores_rca_and_evidence(self, client, db):
        evidence = [{"signal": "high restart count"}, {"signal": "OOM kill"}]
        resp = client.post("/integration/deepfield-incident", json={
            "incident_id": "inc-004",
            "namespace": "sandbox-rca",
            "rca_output": "Root cause is OOMKilled container",
            "evidence_chain": evidence,
        })
        assert resp.status_code == 201

        from db.models import PendingAction
        pa = db.query(PendingAction).filter(
            PendingAction.source_event_id == "inc-004",
        ).first()
        assert pa.parameters["rca_output"] == "Root cause is OOMKilled container"
        assert pa.parameters["evidence_chain"] == evidence

    def test_duplicate_incident_idempotent(self, client, db):
        body = {
            "incident_id": "inc-005",
            "namespace": "sandbox-dup",
            "confidence": 0.7,
        }
        resp1 = client.post("/integration/deepfield-incident", json=body)
        assert resp1.status_code == 201
        assert resp1.json()["status"] == "queued_for_approval"

        resp2 = client.post("/integration/deepfield-incident", json=body)
        assert resp2.status_code == 201
        assert resp2.json()["status"] == "already_queued"

        from db.models import PendingAction
        count = db.query(PendingAction).filter(
            PendingAction.source_event_id == "inc-005",
        ).count()
        assert count == 1
