"""Feedback Loop Tests — Signal → Decision → Action → Verify → Learn.

RED/GREEN TDD: tests written FIRST. action_simulator and feedback_loop don't exist yet.
Each test validates a step in the closed loop for each failure scenario.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "stargate-synthetic-client-emulator"))

from tests.conftest import client, db

from emulator.scenarios import get_all_scenarios, get_scenario
from engine.rubric_evaluator import evaluate_rubric
from engine.rubric_loader import load_rubrics_from_directory
from engine.substrate_router import route_workload
from pathlib import Path

RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "platform"
_rubrics = {r.id: r for r in load_rubrics_from_directory(RUBRIC_DIR)}

SCENARIOS = list(get_all_scenarios().keys())
FAILURE_SCENARIOS = [s for s in SCENARIOS if s not in ("healthy-baseline", "xeon-underutil")]


def _evaluate_stages(evidence):
    """Evaluate all stages that have rubrics."""
    outcomes = {}
    for stage_id, stage_evidence in evidence.items():
        if stage_id in _rubrics:
            result = evaluate_rubric(_rubrics[stage_id], stage_evidence)
            outcomes[stage_id] = result.outcome.value
    return outcomes


# ===========================================================================
# Phase A: Shadow Mode — Emulator State Transform
# ===========================================================================

class TestBeforeState:
    """SIGNAL: Before state has the expected failures."""

    @pytest.mark.parametrize("scenario_name", FAILURE_SCENARIOS)
    def test_before_state_has_failures(self, scenario_name):
        """Before state produces at least one rubric failure."""
        scenario = get_scenario(scenario_name)
        evidence = scenario.generate_evidence()
        outcomes = _evaluate_stages(evidence)
        failures = [s for s, o in outcomes.items() if o in ("fail", "warn")]
        assert len(failures) > 0, f"{scenario_name}: expected failures, got all pass"


class TestDecision:
    """DECISION: LLM/policy produces actionable recommendations."""

    @pytest.mark.parametrize("scenario_name", FAILURE_SCENARIOS)
    def test_recommendations_or_expected_exist(self, scenario_name):
        """Each failure scenario has either policy recommendations or expected recommendations."""
        from engine.action_simulator import build_policy_inputs
        from engine.policy import generate_recommendations

        scenario = get_scenario(scenario_name)
        state = scenario.generate_state()
        labs, pools, cluster_states, sessions = build_policy_inputs(scenario_name, state)
        result = generate_recommendations(labs, pools, cluster_states, sessions)

        has_policy_recs = result["total"] > 0
        has_expected_recs = len(scenario.expected_recommendations) > 0
        assert has_policy_recs or has_expected_recs, (
            f"{scenario_name}: no policy or expected recommendations"
        )

    @pytest.mark.parametrize("scenario_name", FAILURE_SCENARIOS)
    def test_routing_decision_made(self, scenario_name):
        """Substrate router makes a routing decision."""
        scenario = get_scenario(scenario_name)
        state = scenario.generate_state()
        routing = route_workload(state)
        assert routing.routing is not None
        assert routing.reason


class TestAction:
    """ACTION: Simulated action transforms state correctly."""

    @pytest.mark.parametrize("scenario_name", FAILURE_SCENARIOS)
    def test_action_simulator_exists(self, scenario_name):
        """Action simulator can be imported and called."""
        from engine.action_simulator import simulate_action
        scenario = get_scenario(scenario_name)
        state = scenario.generate_state()
        routing = route_workload(state)
        result = simulate_action(scenario.expected_recommendations[0], state, routing)
        assert isinstance(result, dict)
        assert "nodes" in result


class TestVerify:
    """VERIFY: After simulated action, re-evaluation produces all PASS."""

    EMULATOR_STAGES = [
        "cluster-health", "namespace-ready", "deployment-ready", "route-ready",
        "storage-clone-ready", "vm-runtime-ready", "provision-complete",
        "showroom-healthy", "model-endpoint-ready",
    ]

    @pytest.mark.parametrize("scenario_name", FAILURE_SCENARIOS)
    def test_after_state_resolves_failures(self, scenario_name):
        """After simulated action, all rubric stages pass."""
        from engine.action_simulator import simulate_action
        from emulator.generators.evidence import generate_stage_evidence

        scenario = get_scenario(scenario_name)
        state = scenario.generate_state()
        routing = route_workload(state)

        after_state = simulate_action(scenario.expected_recommendations[0], state, routing)

        after_evidence = {}
        for stage_id in self.EMULATOR_STAGES:
            if stage_id in _rubrics:
                after_evidence[stage_id] = generate_stage_evidence(stage_id, after_state)

        after_outcomes = _evaluate_stages(after_evidence)

        failures_remaining = {s: o for s, o in after_outcomes.items() if o == "fail"}
        assert len(failures_remaining) == 0, (
            f"{scenario_name}: after action '{scenario.expected_recommendations[0]}', "
            f"still failing: {failures_remaining}"
        )


class TestLearn:
    """LEARN: Feedback recorded with before/after comparison."""

    @pytest.mark.parametrize("scenario_name", FAILURE_SCENARIOS)
    def test_feedback_loop_result(self, scenario_name, db):
        """Full feedback loop produces a complete result."""
        from engine.feedback_loop import run_feedback_loop
        result = run_feedback_loop(scenario_name, db)
        assert result.scenario == scenario_name
        assert result.resolved is True
        assert len(result.before_outcomes) > 0
        assert len(result.after_outcomes) > 0
        assert len(result.recommendations) > 0

    @pytest.mark.parametrize("scenario_name", FAILURE_SCENARIOS)
    def test_before_has_failures_after_passes(self, scenario_name, db):
        """Before outcomes have failures, after outcomes are all pass."""
        from engine.feedback_loop import run_feedback_loop
        result = run_feedback_loop(scenario_name, db)
        before_fails = [s for s, o in result.before_outcomes.items() if o in ("fail", "warn")]
        after_fails = [s for s, o in result.after_outcomes.items() if o == "fail"]
        assert len(before_fails) > 0, "Before should have failures"
        assert len(after_fails) == 0, f"After should have no failures, got: {after_fails}"

    @pytest.mark.parametrize("scenario_name", FAILURE_SCENARIOS)
    def test_routing_in_result(self, scenario_name, db):
        """Result includes substrate routing decision."""
        from engine.feedback_loop import run_feedback_loop
        result = run_feedback_loop(scenario_name, db)
        assert result.routing is not None
        assert "routing" in result.routing


class TestHealthyBaseline:
    """Healthy baseline: no failures, no action, still passes."""

    def test_no_action_needed(self):
        """healthy-baseline has no failures and no recommendations."""
        scenario = get_scenario("healthy-baseline")
        evidence = scenario.generate_evidence()
        outcomes = _evaluate_stages(evidence)
        failures = [s for s, o in outcomes.items() if o == "fail"]
        assert len(failures) == 0

    def test_baseline_loop_result(self, db):
        """Feedback loop on healthy-baseline shows resolved=True with no action."""
        from engine.feedback_loop import run_feedback_loop
        result = run_feedback_loop("healthy-baseline", db)
        assert result.resolved is True
        assert len(result.recommendations) == 0


class TestFullReport:
    """Summary report across all scenarios."""

    def test_all_scenarios_loop(self, db):
        """Running all scenarios through the feedback loop produces results."""
        from engine.feedback_loop import run_feedback_loop
        results = []
        for name in SCENARIOS:
            result = run_feedback_loop(name, db)
            results.append(result)
        assert len(results) == 7
        resolved = sum(1 for r in results if r.resolved)
        assert resolved == 7, f"Only {resolved}/7 scenarios resolved"
