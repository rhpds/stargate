"""Nanoagent Pipeline with Synthetic Data — failure scenarios trigger events correctly.

RED/GREEN TDD: tests written first, then wired to pass.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "stargate-synthetic-client-emulator"))

from events.bus import EventBus
from events.nanoagents import create_default_pipeline, FilterAgent, CorrelateAgent, TriageAgent, ImpactAgent
from events.models import Event


def _create_bus():
    bus = EventBus()
    for agent in create_default_pipeline():
        bus.register_nanoagent(agent)
    return bus


class TestNanoagentWithSyntheticData:
    def test_failure_scenario_emits_events(self):
        """node-failure → evaluation fails → event emitted → nanoagents process."""
        from emulator.scenarios import get_scenario
        from engine.rubric_evaluator import evaluate_rubric
        from engine.rubric_loader import load_rubrics_from_directory
        from pathlib import Path

        rubrics = {r.id: r for r in load_rubrics_from_directory(
            Path(__file__).parent.parent / "rubrics" / "platform"
        )}

        scenario = get_scenario("node-failure")
        evidence = scenario.generate_evidence()

        bus = _create_bus()

        # Evaluate cluster-health — should FAIL
        result = evaluate_rubric(rubrics["cluster-health"], evidence["cluster-health"])
        assert result.outcome.value == "fail"

        # Emit the failure event
        event = Event(
            event_type="evaluation.failed",
            run_id="syn-nanoagent-test",
            stage_id="cluster-health",
            lab_code="sandbox-syn-node-fail",
            cluster_name="synthetic-cluster",
            outcome="fail",
            failure_class=result.failure_class,
            message=result.message,
        )
        bus.emit(event)

        # Event should be in history
        assert len(bus.history) > 0
        last = bus.history[-1]
        assert last.failure_class == result.failure_class
        assert last.filtered is False  # first failure should not be filtered

    def test_systemic_failure_detected(self):
        """Multiple failures on same cluster → CorrelateAgent marks systemic."""
        bus = _create_bus()

        # Emit 10 failures with same class on same cluster
        for i in range(10):
            event = Event(
                event_type="evaluation.failed",
                run_id=f"syn-systemic-{i}",
                stage_id="cluster-health",
                lab_code=f"sandbox-lab-{i}",
                cluster_name="ocpv-synthetic",
                outcome="fail",
                failure_class="cluster_unreachable",
            )
            bus.emit(event)

        # At least one event should be marked systemic
        systemic = [e for e in bus.history if e.systemic]
        assert len(systemic) > 0, "Expected systemic flag on correlated failures"

    def test_high_priority_assigned(self):
        """Critical failure → TriageAgent assigns high priority."""
        bus = _create_bus()

        event = Event(
            event_type="evaluation.failed",
            run_id="syn-priority-test",
            stage_id="cluster-health",
            lab_code="sandbox-critical",
            cluster_name="ocpv-synthetic",
            outcome="fail",
            failure_class="cluster_unreachable",
        )
        bus.emit(event)

        last = bus.history[-1]
        assert last.priority >= 8.0, f"Expected high priority for cluster_unreachable, got {last.priority}"
        assert last.metadata.get("triage_level") in ("critical", "high")
