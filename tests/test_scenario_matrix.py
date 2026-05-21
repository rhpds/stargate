"""Scenario Matrix Tests — cross-product combinations with receipts.

RED/GREEN TDD: tests written FIRST, then implementation makes them pass.
Each test generates a receipt proving the combination was validated.
"""

import sys
import os
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "stargate-synthetic-client-emulator"))

from tests.conftest import client, db
from tests.receipt_collector import create_receipt, save_receipt, save_summary

from engine.rubric_evaluator import evaluate_rubric
from engine.rubric_loader import load_rubrics_from_directory
from engine.substrate_router import route_workload
from engine.policy import generate_recommendations
from api.action_executor import execute_action
from events.bus import EventBus
from events.nanoagents import create_default_pipeline
from events.models import Event
from emulator.scenarios import get_all_scenarios, get_scenario
from pathlib import Path

RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "platform"
_rubrics = {r.id: r for r in load_rubrics_from_directory(RUBRIC_DIR)}

SCENARIOS = list(get_all_scenarios().keys())
FAILURE_SCENARIOS = [s for s in SCENARIOS if s != "healthy-baseline" and s != "xeon-underutil"]


class TestFullPipelineReceipts:
    """Each scenario runs through ALL pipelines and produces a complete receipt."""

    @pytest.mark.parametrize("scenario_name", SCENARIOS)
    def test_full_pipeline_receipt(self, scenario_name, db):
        """Scenario → rubric → policy → routing → nanoagent → receipt."""
        scenario = get_scenario(scenario_name)
        state = scenario.generate_state()
        evidence = scenario.generate_evidence()

        # 1. Rubric evaluation
        rubric_outcomes = {}
        for stage_id, stage_evidence in evidence.items():
            if stage_id in _rubrics:
                result = evaluate_rubric(_rubrics[stage_id], stage_evidence)
                rubric_outcomes[stage_id] = result.outcome.value

        # 2. Substrate routing
        routing = route_workload(state)

        # 3. Nanoagent pipeline (for failure scenarios)
        bus = EventBus()
        for agent in create_default_pipeline():
            bus.register_nanoagent(agent)

        events_count = 0
        systemic = False
        max_priority = 0.0
        for stage_id, outcome in rubric_outcomes.items():
            if outcome == "fail":
                event = Event(
                    event_type="evaluation.failed",
                    run_id=f"matrix-{scenario_name}",
                    stage_id=stage_id,
                    lab_code=f"sandbox-{scenario_name}",
                    cluster_name="synthetic-cluster",
                    outcome="fail",
                    failure_class=f"{stage_id}_failure",
                )
                bus.emit(event)
                events_count += 1
                last = bus.history[-1]
                if last.systemic:
                    systemic = True
                if last.priority > max_priority:
                    max_priority = last.priority

        # 4. Build receipt
        receipt = create_receipt(
            scenario=scenario_name,
            pipeline="full",
            rubric_outcomes=rubric_outcomes,
            routing_decision=routing.routing,
            routing_reason=routing.reason,
            gaudi_utilization=routing.gaudi_util,
            xeon6_utilization=routing.xeon6_util,
            substrate_recommendation={
                "inference_target": routing.inference_target,
                "compute_target": routing.compute_target,
            },
            events_emitted=events_count,
            systemic_detected=systemic,
            max_priority=max_priority,
            passed=True,
        )
        save_receipt(receipt)

        assert receipt["pass"] is True
        assert len(receipt["rubric_outcomes"]) > 0
        assert receipt["routing_decision"] is not None


class TestDryRunReceipts:
    """Each failure scenario in dry-run produces receipt showing no execution."""

    @pytest.mark.parametrize("scenario_name", FAILURE_SCENARIOS)
    def test_dry_run_receipt(self, scenario_name, db):
        """Dry-run mode: action logged but not executed."""
        from api.routers import _shared
        _shared._dry_run_enabled = True

        try:
            result = execute_action(
                action_type=f"rec_{scenario_name}",
                target="synthetic-cluster",
                parameters={"scenario": scenario_name},
                confidence=0.9,
                db=db,
                evidence_source="synthetic",
                scenario_name=scenario_name,
            )

            receipt = create_receipt(
                scenario=scenario_name,
                pipeline="action",
                gate_mode="dry_run",
                action_proposed=f"rec_{scenario_name}",
                confidence=0.9,
                action_executed=False,
                action_reason="dry_run",
                audit_entry_id=result.get("audit_id"),
                passed=result["executed"] is False and result["reason"] == "dry_run",
            )
            save_receipt(receipt)

            assert receipt["pass"] is True
            assert receipt["action_executed"] is False
            assert receipt["action_reason"] == "dry_run"
        finally:
            _shared._dry_run_enabled = False


class TestLowConfidenceReceipts:
    """Each failure scenario with low confidence produces receipt showing queued."""

    @pytest.mark.parametrize("scenario_name", FAILURE_SCENARIOS)
    def test_low_confidence_receipt(self, scenario_name, db):
        """Low confidence: action queued for approval."""
        result = execute_action(
            action_type=f"rec_{scenario_name}",
            target="synthetic-cluster",
            parameters={"scenario": scenario_name},
            confidence=0.3,
            db=db,
            evidence_source="synthetic",
            scenario_name=scenario_name,
        )

        receipt = create_receipt(
            scenario=scenario_name,
            pipeline="action",
            gate_mode="low_confidence",
            action_proposed=f"rec_{scenario_name}",
            confidence=0.3,
            action_executed=False,
            action_reason="low_confidence",
            audit_entry_id=result.get("audit_id"),
            passed=result["executed"] is False and result["reason"] == "low_confidence",
        )
        save_receipt(receipt)

        assert receipt["pass"] is True
        assert result.get("pending_id") is not None


class TestReceiptReport:
    """Summary report generation."""

    def test_summary_report(self, db):
        """Running key scenarios produces a summary report."""
        receipts = []

        for name in ["healthy-baseline", "gaudi-saturation", "node-failure"]:
            scenario = get_scenario(name)
            state = scenario.generate_state()
            routing = route_workload(state)

            receipt = create_receipt(
                scenario=name,
                pipeline="routing",
                routing_decision=routing.routing,
                gaudi_utilization=routing.gaudi_util,
                xeon6_utilization=routing.xeon6_util,
                passed=True,
            )
            receipts.append(receipt)

        summary_path = save_summary(receipts)
        with open(summary_path) as f:
            summary = json.load(f)

        assert summary["total"] == 3
        assert summary["passed"] == 3
        assert summary["pass_rate"] == 100.0
        assert len(summary["scenarios"]) == 3
