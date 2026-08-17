"""Tests for InvestigationConsumer event handling."""

import os
import pytest
from unittest.mock import patch, MagicMock
from events.models import Event


class TestInvestigationConsumerReceive:
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {"STARGATE_AUTO_INVESTIGATE": "false"}):
            from events.consumers import InvestigationConsumer
            consumer = InvestigationConsumer()
            event = Event(event_type="evaluation.failed", lab_code="ns1", failure_class="fc1")
            assert not consumer.should_receive(event)

    def test_enabled(self):
        with patch.dict(os.environ, {"STARGATE_AUTO_INVESTIGATE": "true"}):
            from events.consumers import InvestigationConsumer
            consumer = InvestigationConsumer()
            event = Event(event_type="evaluation.failed", lab_code="ns1", failure_class="fc1")
            assert consumer.should_receive(event)

    def test_ignores_non_failure_events(self):
        with patch.dict(os.environ, {"STARGATE_AUTO_INVESTIGATE": "true"}):
            from events.consumers import InvestigationConsumer
            consumer = InvestigationConsumer()
            event = Event(event_type="evaluation.passed", lab_code="ns1", failure_class="fc1")
            assert not consumer.should_receive(event)

    def test_ignores_filtered_events(self):
        with patch.dict(os.environ, {"STARGATE_AUTO_INVESTIGATE": "true"}):
            from events.consumers import InvestigationConsumer
            consumer = InvestigationConsumer()
            event = Event(event_type="evaluation.failed", lab_code="ns1", failure_class="fc1")
            event.filtered = True
            assert not consumer.should_receive(event)

    def test_requires_lab_code_and_failure_class(self):
        with patch.dict(os.environ, {"STARGATE_AUTO_INVESTIGATE": "true"}):
            from events.consumers import InvestigationConsumer
            consumer = InvestigationConsumer()
            event = Event(event_type="evaluation.failed", lab_code="", failure_class="fc1")
            assert not consumer.should_receive(event)
            event2 = Event(event_type="evaluation.failed", lab_code="ns1", failure_class="")
            assert not consumer.should_receive(event2)


class TestInvestigationConsumerDeliver:
    def test_queues_investigation_when_should_investigate(self, db):
        with patch.dict(os.environ, {"STARGATE_AUTO_INVESTIGATE": "true"}):
            from events.consumers import InvestigationConsumer
            consumer = InvestigationConsumer()

        event = Event(
            event_type="evaluation.failed",
            lab_code="sandbox-ab12c-ocp4",
            failure_class="pods_crashlooping",
            cluster_name="east",
        )

        with patch("db.database.get_db") as mock_get_db, \
             patch("engine.attention_classifier.should_auto_investigate", return_value=(True, "stuck", "stuck")), \
             patch("db.repository.create_investigation") as mock_create:
            mock_gen = MagicMock()
            mock_gen.__next__ = MagicMock(return_value=db)
            mock_gen.close = MagicMock()
            mock_get_db.return_value = mock_gen

            consumer.deliver(event)
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args
            assert call_kwargs[1]["trigger_type"] == "auto_stuck"

    def test_skips_when_should_not_investigate(self, db):
        with patch.dict(os.environ, {"STARGATE_AUTO_INVESTIGATE": "true"}):
            from events.consumers import InvestigationConsumer
            consumer = InvestigationConsumer()

        event = Event(
            event_type="evaluation.failed",
            lab_code="sandbox-ab12c-ocp4",
            failure_class="pods_crashlooping",
            cluster_name="east",
        )

        with patch("db.database.get_db") as mock_get_db, \
             patch("engine.attention_classifier.should_auto_investigate", return_value=(False, "expected")), \
             patch("db.repository.create_investigation") as mock_create:
            mock_gen = MagicMock()
            mock_gen.__next__ = MagicMock(return_value=db)
            mock_gen.close = MagicMock()
            mock_get_db.return_value = mock_gen

            consumer.deliver(event)
            mock_create.assert_not_called()
