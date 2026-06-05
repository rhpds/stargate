"""Workflow tests — Event Pipeline: emit → filter → correlate → triage → impact → consumers."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from events.models import Event


class TestFilterAgent:

    def test_deduplicates_same_failure(self, event_bus, sample_event):
        event_bus.emit(sample_event)
        dup = Event(event_type="evaluation.failed", run_id="test-run-003", stage_id="deployment-ready",
                    lab_code="launchpad-test-lab", cluster_name="ocpv05", outcome="fail", failure_class="pods_crashlooping")
        event_bus.emit(dup)
        non_filtered = [e for e in event_bus.history if not e.filtered]
        assert len(non_filtered) == 1

    def test_passes_new_failure_class(self, event_bus, sample_event):
        event_bus.emit(sample_event)
        different = Event(event_type="evaluation.failed", run_id="test-run-004", stage_id="deployment-ready",
                         lab_code="launchpad-test-lab", cluster_name="ocpv05", outcome="fail", failure_class="route_missing")
        event_bus.emit(different)
        non_filtered = [e for e in event_bus.history if not e.filtered]
        assert len(non_filtered) == 2

    def test_passes_different_lab(self, event_bus, sample_event):
        event_bus.emit(sample_event)
        different_lab = Event(event_type="evaluation.failed", run_id="test-run-005", stage_id="deployment-ready",
                             lab_code="other-lab", cluster_name="ocpv05", outcome="fail", failure_class="pods_crashlooping")
        event_bus.emit(different_lab)
        non_filtered = [e for e in event_bus.history if not e.filtered]
        assert len(non_filtered) == 2


class TestTriageAgent:

    def test_assigns_priority(self, event_bus, sample_event):
        event_bus.emit(sample_event)
        assert sample_event.priority >= 0

    def test_failed_event_gets_higher_priority(self, event_bus):
        fail = Event(event_type="evaluation.failed", run_id="r1", stage_id="s1",
                     lab_code="lab1", cluster_name="c1", outcome="fail", failure_class="pods_crashlooping")
        event_bus.emit(fail)
        assert fail.priority > 0


class TestEventPersistence:

    def test_event_stored_in_history(self, event_bus, sample_event):
        event_bus.emit(sample_event)
        assert len(event_bus.history) >= 1
        assert event_bus.history[-1].event_id == sample_event.event_id

    def test_filtered_event_still_in_history(self, event_bus, sample_event):
        event_bus.emit(sample_event)
        dup = Event(event_type="evaluation.failed", run_id="r2", stage_id="deployment-ready",
                    lab_code="launchpad-test-lab", cluster_name="ocpv05", outcome="fail", failure_class="pods_crashlooping")
        event_bus.emit(dup)
        assert len(event_bus.history) == 2
        assert dup.filtered is True

    def test_consumer_failure_doesnt_crash_bus(self, event_bus, sample_event):
        from events.bus import EventConsumer
        class BrokenConsumer(EventConsumer):
            name = "broken"
            def deliver(self, event):
                raise RuntimeError("consumer exploded")
        event_bus.register_consumer(BrokenConsumer())
        event_bus.emit(sample_event)
        assert len(event_bus.history) == 1
