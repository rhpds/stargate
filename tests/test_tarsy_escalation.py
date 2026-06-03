"""TARSy escalation trigger and result handler tests."""

import json
import pytest
from unittest.mock import patch, MagicMock

from events.models import Event
from integrations.tarsy_escalation import TarsyEscalationTracker


class TestFailureCounting:
    def test_single_failure_no_escalation(self):
        tracker = TarsyEscalationTracker()
        event = Event(
            event_type="remediation.failed",
            run_id="run-1",
            lab_code="lab-a",
            cluster_name="ocpv06",
            failure_class=None,
        )
        tracker.record_failure(event)
        assert not tracker.should_escalate(event)

    def test_two_failures_triggers_escalation(self):
        tracker = TarsyEscalationTracker()
        event = Event(
            event_type="remediation.failed",
            run_id="run-1",
            lab_code="lab-a",
            cluster_name="ocpv06",
            failure_class=None,
        )
        tracker.record_failure(event)

        event2 = Event(
            event_type="remediation.failed",
            run_id="run-2",
            lab_code="lab-a",
            cluster_name="ocpv06",
            failure_class=None,
        )
        tracker.record_failure(event2)
        assert tracker.should_escalate(event2)

    def test_three_failures_still_triggers(self):
        tracker = TarsyEscalationTracker()
        for i in range(3):
            event = Event(
                event_type="remediation.failed",
                run_id=f"run-{i}",
                lab_code="lab-b",
                cluster_name="ocpv07",
                failure_class=None,
            )
            tracker.record_failure(event)
        assert tracker.should_escalate(event)


class TestClassifiedFailures:
    def test_classified_failure_not_escalated(self):
        tracker = TarsyEscalationTracker()
        for i in range(3):
            event = Event(
                event_type="remediation.failed",
                run_id=f"run-{i}",
                lab_code="lab-c",
                cluster_name="ocpv06",
                failure_class="pods_crashlooping",
            )
            tracker.record_failure(event)
        assert not tracker.should_escalate(event)

    def test_unclassified_string_triggers_escalation(self):
        tracker = TarsyEscalationTracker()
        for i in range(2):
            event = Event(
                event_type="failure.unclassified",
                run_id=f"run-{i}",
                lab_code="lab-d",
                cluster_name="ocpv08",
                failure_class="unclassified",
            )
            tracker.record_failure(event)
        assert tracker.should_escalate(event)

    def test_none_failure_class_triggers_escalation(self):
        tracker = TarsyEscalationTracker()
        for i in range(2):
            event = Event(
                event_type="evaluation.failed",
                run_id=f"run-{i}",
                lab_code="lab-e",
                cluster_name="ocpv09",
                failure_class=None,
            )
            tracker.record_failure(event)
        assert tracker.should_escalate(event)


class TestIdempotency:
    def test_same_key_not_escalated_twice(self):
        tracker = TarsyEscalationTracker()
        for i in range(2):
            event = Event(
                event_type="remediation.failed",
                run_id=f"run-{i}",
                lab_code="lab-f",
                cluster_name="ocpv10",
                failure_class=None,
            )
            tracker.record_failure(event)

        assert tracker.should_escalate(event)

        with patch("integrations.kafka_publisher.publish_tarsy_request"):
            tracker.escalate(event)

        # After escalation, should_escalate returns False for the same key
        event3 = Event(
            event_type="remediation.failed",
            run_id="run-3",
            lab_code="lab-f",
            cluster_name="ocpv10",
            failure_class=None,
        )
        tracker.record_failure(event3)
        assert not tracker.should_escalate(event3)

    def test_different_lab_cluster_tracked_separately(self):
        tracker = TarsyEscalationTracker()
        for i in range(2):
            event_a = Event(
                event_type="remediation.failed",
                run_id=f"run-a-{i}",
                lab_code="lab-x",
                cluster_name="ocpv06",
                failure_class=None,
            )
            event_b = Event(
                event_type="remediation.failed",
                run_id=f"run-b-{i}",
                lab_code="lab-y",
                cluster_name="ocpv07",
                failure_class=None,
            )
            tracker.record_failure(event_a)
            tracker.record_failure(event_b)

        assert tracker.should_escalate(event_a)
        assert tracker.should_escalate(event_b)


class TestEscalatePayload:
    @patch("integrations.kafka_publisher.publish_tarsy_request")
    def test_escalate_builds_correct_payload(self, mock_publish):
        tracker = TarsyEscalationTracker()
        event = Event(
            event_type="remediation.failed",
            run_id="run-42",
            lab_code="lab-g",
            cluster_name="ocpv11",
            failure_class=None,
            message="Pod restart loop detected",
        )
        tracker.record_failure(event)
        tracker.record_failure(event)

        tracker.escalate(event)

        mock_publish.assert_called_once()
        request = mock_publish.call_args[0][0]

        assert request["alert_type"] == "StarGateFailure"
        assert request["severity"] == "high"
        assert request["originator_id"] == "run-42"
        assert request["mcp_override"]["tools"] == ["kubernetes-server"]
        assert request["mcp_override"]["access"] == "read-only"
        assert "requested_at" in request

        data = json.loads(request["data"])
        assert data["event"]["run_id"] == "run-42"
        assert data["event"]["lab_code"] == "lab-g"
        assert data["failure_count"] == 2

    @patch("integrations.kafka_publisher.publish_tarsy_request")
    def test_escalate_adds_key_to_escalated(self, mock_publish):
        tracker = TarsyEscalationTracker()
        event = Event(
            event_type="remediation.failed",
            run_id="run-99",
            lab_code="lab-h",
            cluster_name="ocpv12",
            failure_class=None,
        )
        tracker.record_failure(event)
        tracker.record_failure(event)

        tracker.escalate(event)
        assert "lab-h:ocpv12" in tracker._escalated

    @patch("integrations.kafka_publisher.publish_tarsy_request", side_effect=Exception("kafka down"))
    def test_escalate_fails_silently(self, mock_publish):
        tracker = TarsyEscalationTracker()
        event = Event(
            event_type="remediation.failed",
            run_id="run-100",
            lab_code="lab-i",
            cluster_name="ocpv13",
            failure_class=None,
        )
        tracker.record_failure(event)
        tracker.record_failure(event)

        # Should not raise
        tracker.escalate(event)
        # Key is still marked escalated even on publish failure
        assert "lab-i:ocpv13" in tracker._escalated


class TestTarsyResultHandler:
    def test_handle_result_logs_and_emits(self):
        from integrations.tarsy_result_handler import handle_tarsy_result

        message = {
            "originator_id": "run-50",
            "severity": "high",
            "data": json.dumps({
                "status": "resolved",
                "root_cause": "OOM on worker nodes",
                "recommended_actions": [
                    "Scale worker node memory",
                    {"description": "Restart pods", "catalog_id": "restart-pods-v1"},
                ],
            }),
        }

        # Should not raise even without a bus
        handle_tarsy_result(message)

    def test_handle_result_maps_actions(self):
        from integrations.tarsy_result_handler import _map_to_catalog

        actions = [
            "Scale memory",
            {"description": "Restart pods", "catalog_id": "restart-pods-v1"},
        ]
        entries = _map_to_catalog(actions)
        assert len(entries) == 2
        assert entries[0]["action"] == "Scale memory"
        assert entries[0]["catalog_match"] is None
        assert entries[1]["catalog_match"] == "restart-pods-v1"
