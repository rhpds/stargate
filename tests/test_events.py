"""Stage 4 — event bus and nanoagent pipeline tests."""

import pytest

from events.bus import EventBus
from events.models import Event
from events.nanoagents import (
    FilterAgent,
    CorrelateAgent,
    TriageAgent,
    ImpactAgent,
    create_default_pipeline,
)
from events.consumers import LogConsumer


class TestEventBus:
    def test_emit_stores_in_history(self):
        bus = EventBus()
        event = Event(event_type="evaluation.passed", run_id="test-1")
        bus.emit(event)
        assert len(bus.history) == 1

    def test_get_recent(self):
        bus = EventBus()
        for i in range(5):
            bus.emit(Event(event_type="evaluation.passed" if i < 3 else "evaluation.failed", run_id=f"r-{i}"))
        assert len(bus.get_recent()) == 5
        assert len(bus.get_recent(event_type="evaluation.failed")) == 2

    def test_consumer_receives_event(self):
        bus = EventBus()
        received = []

        class TestConsumer(LogConsumer):
            def deliver(self, event):
                received.append(event)

        bus.register_consumer(TestConsumer())
        bus.emit(Event(event_type="evaluation.failed", failure_class="pods_crashlooping"))
        assert len(received) == 1


class TestFilterAgent:
    def test_routine_pass_filtered(self):
        bus = EventBus()
        agent = FilterAgent()
        bus.register_nanoagent(agent)

        # First pass — not filtered (no previous)
        e1 = Event(event_type="evaluation.passed", lab_code="lab1", stage_id="ns-ready", outcome="pass")
        bus.emit(e1)
        assert not e1.filtered

        # Second pass same lab — filtered (routine)
        e2 = Event(event_type="evaluation.passed", lab_code="lab1", stage_id="ns-ready", outcome="pass")
        bus.emit(e2)
        assert e2.filtered

    def test_pass_after_fail_not_filtered(self):
        bus = EventBus()
        agent = FilterAgent()
        bus.register_nanoagent(agent)

        e1 = Event(event_type="evaluation.failed", lab_code="lab1", stage_id="ns-ready", outcome="fail")
        bus.emit(e1)

        e2 = Event(event_type="evaluation.passed", lab_code="lab1", stage_id="ns-ready", outcome="pass")
        bus.emit(e2)
        assert not e2.filtered  # Recovery — important event

    def test_duplicate_failure_deduplicated(self):
        bus = EventBus()
        agent = FilterAgent()
        bus.register_nanoagent(agent)

        e1 = Event(event_type="evaluation.failed", lab_code="lab1", failure_class="pods_crashlooping", cluster_name="ocpv06")
        bus.emit(e1)
        assert not e1.filtered

        e2 = Event(event_type="evaluation.failed", lab_code="lab1", failure_class="pods_crashlooping", cluster_name="ocpv06")
        bus.emit(e2)
        assert e2.filtered
        assert e2.deduplicated

    def test_different_failure_class_not_deduplicated(self):
        bus = EventBus()
        agent = FilterAgent()
        bus.register_nanoagent(agent)

        e1 = Event(event_type="evaluation.failed", lab_code="lab1", failure_class="pods_crashlooping", cluster_name="ocpv06")
        bus.emit(e1)

        e2 = Event(event_type="evaluation.failed", lab_code="lab1", failure_class="route_missing", cluster_name="ocpv06")
        bus.emit(e2)
        assert not e2.filtered

    def test_suppress_rule(self):
        bus = EventBus()
        agent = FilterAgent(suppress_rules=[
            {"failure_class": "guest_agent_not_connected"},
        ])
        bus.register_nanoagent(agent)

        e = Event(event_type="evaluation.failed", failure_class="guest_agent_not_connected")
        bus.emit(e)
        assert e.filtered


class TestCorrelateAgent:
    def test_systemic_failure_detected(self):
        bus = EventBus()
        agent = CorrelateAgent()

        # Seed history with failures
        for i in range(10):
            e = Event(
                event_type="evaluation.failed",
                cluster_name="ocpv06",
                failure_class="pods_crashlooping" if i < 5 else "other",
                lab_code=f"lab-{i}",
            )
            bus.history.append(e)

        # New event should detect systemic pattern
        event = Event(
            event_type="evaluation.failed",
            cluster_name="ocpv06",
            failure_class="pods_crashlooping",
            lab_code="lab-new",
        )
        result = agent.process(event, bus)
        assert result.systemic
        assert result.correlated

    def test_cross_cluster_detected(self):
        bus = EventBus()
        agent = CorrelateAgent()

        for cluster in ["ocpv06", "ocpv07", "ocpv08"]:
            bus.history.append(Event(
                event_type="evaluation.failed",
                cluster_name=cluster,
                failure_class="guest_agent_not_connected",
                lab_code=f"lab-{cluster}",
            ))

        event = Event(
            event_type="evaluation.failed",
            cluster_name="ocpv09",
            failure_class="guest_agent_not_connected",
            lab_code="lab-new",
        )
        result = agent.process(event, bus)
        assert result.correlated
        assert result.metadata.get("correlation", {}).get("cross_cluster")


class TestTriageAgent:
    def test_critical_failure_high_priority(self):
        agent = TriageAgent()
        bus = EventBus()

        event = Event(event_type="evaluation.failed", failure_class="pods_crashlooping")
        result = agent.process(event, bus)
        assert result.priority >= 8
        assert result.metadata["triage_level"] == "critical"

    def test_low_severity_low_priority(self):
        agent = TriageAgent()
        bus = EventBus()

        event = Event(event_type="evaluation.failed", failure_class="guest_agent_not_connected")
        result = agent.process(event, bus)
        assert result.priority < 4
        assert result.metadata["triage_level"] == "low"

    def test_systemic_boosts_priority(self):
        agent = TriageAgent()
        bus = EventBus()

        event = Event(event_type="evaluation.failed", failure_class="route_missing", systemic=True)
        result = agent.process(event, bus)
        assert result.priority > 4  # Boosted from 4


class TestImpactAgent:
    def test_blast_radius_calculated(self):
        bus = EventBus()
        agent = ImpactAgent()

        for i in range(10):
            bus.history.append(Event(
                event_type="evaluation.failed" if i < 3 else "evaluation.passed",
                cluster_name="ocpv06",
                lab_code=f"lab-{i}",
                outcome="fail" if i < 3 else "pass",
            ))

        event = Event(
            event_type="evaluation.failed",
            cluster_name="ocpv06",
            lab_code="lab-new",
            priority=6,
        )
        result = agent.process(event, bus)
        assert result.blast_radius is not None
        assert result.blast_radius["total_labs"] > 0

    def test_low_priority_skipped(self):
        agent = ImpactAgent()
        event = Event(event_type="evaluation.failed", priority=2, cluster_name="ocpv06")
        assert not agent.should_process(event)


class TestFullPipeline:
    def test_default_pipeline_processes_event(self):
        bus = EventBus()
        for agent in create_default_pipeline():
            bus.register_nanoagent(agent)

        event = Event(
            event_type="evaluation.failed",
            failure_class="pods_crashlooping",
            cluster_name="ocpv06",
            lab_code="sandbox-test",
        )
        bus.emit(event)

        assert len(bus.history) == 1
        stored = bus.history[0]
        assert stored.priority > 0
        assert stored.metadata.get("triage_level")

    def test_routine_pass_filtered_in_pipeline(self):
        bus = EventBus()
        for agent in create_default_pipeline():
            bus.register_nanoagent(agent)

        delivered = []
        class Tracker(LogConsumer):
            def deliver(self, event):
                delivered.append(event)
        bus.register_consumer(Tracker())

        # First pass
        bus.emit(Event(event_type="evaluation.passed", lab_code="lab1", stage_id="s1", outcome="pass"))
        assert len(delivered) == 1

        # Second pass — filtered, consumer should NOT receive
        bus.emit(Event(event_type="evaluation.passed", lab_code="lab1", stage_id="s1", outcome="pass"))
        assert len(delivered) == 1  # Still 1

    def test_only_unclassified_would_reach_llm(self):
        bus = EventBus()
        for agent in create_default_pipeline():
            bus.register_nanoagent(agent)

        # Classified failure — handled deterministically
        e1 = Event(event_type="evaluation.failed", failure_class="pods_crashlooping",
                    cluster_name="c1", lab_code="l1")
        bus.emit(e1)
        assert not e1.filtered
        assert e1.metadata.get("triage_level")

        # Unclassified — this is what would go to LLM
        e2 = Event(event_type="failure.unclassified", failure_class=None,
                    cluster_name="c1", lab_code="l2")
        bus.emit(e2)
        assert not e2.filtered
        assert e2.metadata.get("triage_level")
