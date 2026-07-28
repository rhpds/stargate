"""RED/GREEN TDD: tests written FIRST.

Contract tests for the Deepfield <-> StarGate integration boundary:
  - Outbound payload shape (all required fields present)
  - failure_class format (snake_case)
  - Inbound incident schema validation
"""

import json
import re
from unittest.mock import MagicMock, patch

import pytest

from events.models import Event
from events.consumers import DeepFieldConsumer


class TestOutboundPayloadContract:
    """The outbound payload sent to DeepField must include all required fields."""

    REQUIRED_TOP = {"source", "event_type", "event_id", "timestamp"}
    REQUIRED_INNER = {
        "run_id", "stage_id", "lab_code", "cluster", "namespace",
        "outcome", "failure_class", "message", "priority", "systemic",
        "blast_radius",
    }

    def _capture_payload(self, event: Event) -> dict:
        consumer = DeepFieldConsumer(url="http://deepfield.test")
        captured = {}

        def _mock_urlopen(req, timeout=10):
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            return MagicMock(status=200)

        with patch("events.consumers.urllib.request.urlopen", side_effect=_mock_urlopen):
            consumer.deliver(event)

        return captured.get("payload", {})

    def test_outbound_payload_has_required_fields(self):
        event = Event(
            event_type="evaluation.failed",
            run_id="run-contract-1",
            stage_id="stage-1",
            lab_code="OCP4_DEMO",
            cluster_name="ocpv05",
            namespace="sandbox-contract",
            outcome="fail",
            failure_class="readiness_probe",
            message="Readiness probe failed",
            priority=5.0,
            systemic=True,
            blast_radius={"total_events": 3, "labs_affected": ["lab1"]},
        )
        payload = self._capture_payload(event)

        # Top-level keys
        for key in self.REQUIRED_TOP:
            assert key in payload, f"Missing top-level key: {key}"

        # Inner payload keys
        inner = payload.get("payload", {})
        for key in self.REQUIRED_INNER:
            assert key in inner, f"Missing inner payload key: {key}"

    def test_failure_class_snake_case(self):
        event = Event(
            event_type="evaluation.failed",
            run_id="run-contract-2",
            failure_class="readiness_probe",
        )
        payload = self._capture_payload(event)
        fc = payload["payload"]["failure_class"]
        if fc:
            assert re.match(r"^[a-z][a-z0-9_]*$", fc), (
                f"failure_class '{fc}' is not snake_case"
            )


class TestInboundIncidentSchema:
    """DeepfieldIncidentRequest must parse valid payloads."""

    def test_inbound_incident_schema_valid(self):
        from api.schemas import DeepfieldIncidentRequest

        req = DeepfieldIncidentRequest(
            incident_id="inc-schema-1",
            namespace="sandbox-schema",
            cluster="ocpv05",
            failure_class="readiness_probe",
            severity="high",
            confidence=0.92,
            rca_output="Root cause: CrashLoopBackOff",
            correlated_signals=[{"type": "pod_restart", "count": 12}],
            remediation_options=[{"action": "delete_pod", "target": "my-pod"}],
            evidence_chain=[{"signal": "restart > 5", "source": "k8s"}],
            signal_count=3,
        )
        assert req.incident_id == "inc-schema-1"
        assert req.namespace == "sandbox-schema"
        assert req.source == "deepfield"
        assert req.confidence == 0.92
        assert len(req.evidence_chain) == 1

    def test_inbound_schema_defaults(self):
        from api.schemas import DeepfieldIncidentRequest

        req = DeepfieldIncidentRequest(
            incident_id="inc-defaults",
            namespace="sandbox-defaults",
        )
        assert req.source == "deepfield"
        assert req.severity == "medium"
        assert req.confidence == 0.5
        assert req.correlated_signals == []
        assert req.remediation_options == []
        assert req.evidence_chain == []
        assert req.signal_count == 0
