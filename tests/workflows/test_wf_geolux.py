"""Workflow tests — GeoLux: outbound events → inbound proposals → approval queue."""

import json
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
from events.models import Event


class TestGeoLuxOutbound:

    def test_forwards_failed_event(self, mock_http):
        from events.consumers import GeoLuxConsumer
        consumer = GeoLuxConsumer(url="http://geolux.test:8091")
        event = Event(event_type="evaluation.failed", run_id="r1", stage_id="s1",
                      lab_code="lab1", cluster_name="c1", outcome="fail", failure_class="pods_crashlooping")
        assert consumer.should_receive(event) is True
        consumer.deliver(event)
        mock_http.assert_called_once()
        call_args = mock_http.call_args
        req = call_args[0][0]
        assert "geolux.test" in req.full_url
        body = json.loads(req.data)
        assert body["source"] == "stargate"
        assert body["event_type"] == "stargate_evaluation_failed"

    def test_skips_filtered_event(self):
        from events.consumers import GeoLuxConsumer
        consumer = GeoLuxConsumer(url="http://geolux.test:8091")
        event = Event(event_type="evaluation.failed", run_id="r1", stage_id="s1",
                      lab_code="lab1", cluster_name="c1", outcome="fail")
        event.filtered = True
        assert consumer.should_receive(event) is False

    def test_skips_when_no_url(self):
        from events.consumers import GeoLuxConsumer
        consumer = GeoLuxConsumer(url="")
        event = Event(event_type="evaluation.failed", run_id="r1", stage_id="s1",
                      lab_code="lab1", cluster_name="c1", outcome="fail")
        assert consumer.should_receive(event) is False


class TestGeoLuxInbound:

    def test_proposal_creates_pending_action(self, mock_db):
        from api.routers.integration import receive_geolux_proposal
        body = {
            "source": "geolux",
            "event_id": "evt-123",
            "proposal": {
                "action_type": "cleanup_stuck",
                "target": "launchpad-test",
                "failure_class": "pods_crashlooping",
                "confidence": 0.85,
                "reasoning": "GeoLux detected CrashLoopBackOff pattern",
            },
        }
        result = receive_geolux_proposal(body, db=mock_db)
        assert result["status"] == "queued_for_approval"
        assert result["pending_id"] is not None

        from db.models import PendingAction
        pending = mock_db.query(PendingAction).first()
        assert pending is not None
        assert pending.proposed_by == "geolux"
        assert pending.confidence == 0.85
        assert pending.status == "pending"

    def test_proposal_logged_to_audit(self, mock_db):
        from api.routers.integration import receive_geolux_proposal
        body = {"source": "geolux", "event_id": "evt-456",
                "proposal": {"action_type": "cleanup_stuck", "target": "launchpad-test", "confidence": 0.7}}
        receive_geolux_proposal(body, db=mock_db)

        from db.models import AuditLog
        audit = mock_db.query(AuditLog).first()
        assert audit is not None
        assert audit.proposed_by == "geolux"
        assert audit.status == "proposed"

    def test_proposal_requires_target(self, mock_db):
        from api.routers.integration import receive_geolux_proposal
        from fastapi import HTTPException
        body = {"source": "geolux", "proposal": {"action_type": "cleanup_stuck", "confidence": 0.5}}
        with pytest.raises(HTTPException) as exc:
            receive_geolux_proposal(body, db=mock_db)
        assert exc.value.status_code == 422
