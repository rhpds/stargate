"""Workflow tests — DeepField: outbound event forwarding."""

import json
from unittest.mock import patch, MagicMock

from events.models import Event


class TestDeepFieldOutbound:

    def test_forwards_failed_event(self, mock_http):
        from events.consumers import DeepFieldConsumer
        consumer = DeepFieldConsumer(url="http://deepfield.test:8090")
        event = Event(event_type="evaluation.failed", run_id="r1", stage_id="s1",
                      lab_code="lab1", cluster_name="c1", outcome="fail", failure_class="route_missing")
        assert consumer.should_receive(event) is True
        consumer.deliver(event)
        mock_http.assert_called_once()
        req = mock_http.call_args[0][0]
        body = json.loads(req.data)
        assert body["event_type"] == "stargate_stage_failed"

    def test_maps_event_types_correctly(self):
        from events.consumers import DeepFieldConsumer
        consumer = DeepFieldConsumer(url="http://deepfield.test:8090")
        assert consumer._EVENT_TYPE_MAP["evaluation.passed"] == "stargate_stage_passed"
        assert consumer._EVENT_TYPE_MAP["evaluation.failed"] == "stargate_stage_failed"

    def test_delivery_failure_doesnt_crash(self, mock_http):
        from events.consumers import DeepFieldConsumer
        mock_http.side_effect = Exception("connection refused")
        consumer = DeepFieldConsumer(url="http://deepfield.test:8090")
        event = Event(event_type="evaluation.failed", run_id="r1", stage_id="s1",
                      lab_code="lab1", cluster_name="c1", outcome="fail")
        consumer.deliver(event)
