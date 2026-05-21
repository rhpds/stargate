"""Rubric Matrix Test — 7 scenarios × 11 stages = 77 cells.

RED/GREEN TDD: tests written FIRST, then evidence/rubric wired to pass.
Each cell validates: emulator evidence → rubric evaluator → outcome matches expected.
"""

import sys
import os
import pytest

# Add emulator to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "stargate-synthetic-client-emulator"))

from engine.rubric_evaluator import evaluate_rubric
from engine.rubric_loader import load_rubrics_from_directory
from pathlib import Path

RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "platform"

# Load all rubrics once
_rubrics = {}
for r in load_rubrics_from_directory(RUBRIC_DIR):
    _rubrics[r.id] = r


def _load_scenario(name):
    from emulator.scenarios import get_scenario
    return get_scenario(name)


# The expected outcome matrix: (scenario, stage, expected_outcome)
# 7 scenarios × 11 stages = 77 cells
MATRIX = [
    # healthy-baseline: all pass
    ("healthy-baseline", "cluster-health", "pass"),
    ("healthy-baseline", "run-created", "pass"),
    ("healthy-baseline", "provision-complete", "pass"),
    ("healthy-baseline", "namespace-ready", "pass"),
    ("healthy-baseline", "deployment-ready", "pass"),
    ("healthy-baseline", "storage-clone-ready", "pass"),
    ("healthy-baseline", "route-ready", "pass"),
    ("healthy-baseline", "vm-runtime-ready", "pass"),
    ("healthy-baseline", "smoke-test-ready", "pass"),
    ("healthy-baseline", "showroom-healthy", "pass"),
    ("healthy-baseline", "model-endpoint-ready", "pass"),

    # memory-pressure: cluster-health WARN, deployment-ready FAIL
    ("memory-pressure", "cluster-health", "warn"),
    ("memory-pressure", "run-created", "pass"),
    ("memory-pressure", "provision-complete", "pass"),
    ("memory-pressure", "namespace-ready", "pass"),
    ("memory-pressure", "deployment-ready", "fail"),
    ("memory-pressure", "storage-clone-ready", "pass"),
    ("memory-pressure", "route-ready", "pass"),
    ("memory-pressure", "vm-runtime-ready", "pass"),
    ("memory-pressure", "smoke-test-ready", "pass"),
    ("memory-pressure", "showroom-healthy", "pass"),
    ("memory-pressure", "model-endpoint-ready", "pass"),

    # node-failure: cluster-health FAIL, vm-runtime-ready WARN
    ("node-failure", "cluster-health", "fail"),
    ("node-failure", "run-created", "pass"),
    ("node-failure", "provision-complete", "pass"),
    ("node-failure", "namespace-ready", "pass"),
    ("node-failure", "deployment-ready", "pass"),
    ("node-failure", "storage-clone-ready", "pass"),
    ("node-failure", "route-ready", "pass"),
    ("node-failure", "vm-runtime-ready", "warn"),
    ("node-failure", "smoke-test-ready", "pass"),
    ("node-failure", "showroom-healthy", "pass"),
    ("node-failure", "model-endpoint-ready", "pass"),

    # gaudi-saturation: model-endpoint-ready FAIL, cluster-health WARN (4 hot gaudi nodes)
    ("gaudi-saturation", "cluster-health", "warn"),
    ("gaudi-saturation", "run-created", "pass"),
    ("gaudi-saturation", "provision-complete", "pass"),
    ("gaudi-saturation", "namespace-ready", "pass"),
    ("gaudi-saturation", "deployment-ready", "pass"),
    ("gaudi-saturation", "storage-clone-ready", "pass"),
    ("gaudi-saturation", "route-ready", "pass"),
    ("gaudi-saturation", "vm-runtime-ready", "pass"),
    ("gaudi-saturation", "smoke-test-ready", "pass"),
    ("gaudi-saturation", "showroom-healthy", "pass"),
    ("gaudi-saturation", "model-endpoint-ready", "fail"),

    # xeon-underutil: all pass
    ("xeon-underutil", "cluster-health", "pass"),
    ("xeon-underutil", "run-created", "pass"),
    ("xeon-underutil", "provision-complete", "pass"),
    ("xeon-underutil", "namespace-ready", "pass"),
    ("xeon-underutil", "deployment-ready", "pass"),
    ("xeon-underutil", "storage-clone-ready", "pass"),
    ("xeon-underutil", "route-ready", "pass"),
    ("xeon-underutil", "vm-runtime-ready", "pass"),
    ("xeon-underutil", "smoke-test-ready", "pass"),
    ("xeon-underutil", "showroom-healthy", "pass"),
    ("xeon-underutil", "model-endpoint-ready", "pass"),

    # mixed-contention: storage-clone-ready WARN, showroom-healthy FAIL, deployment-ready FAIL (crashloops)
    ("mixed-contention", "cluster-health", "pass"),
    ("mixed-contention", "run-created", "pass"),
    ("mixed-contention", "provision-complete", "pass"),
    ("mixed-contention", "namespace-ready", "pass"),
    ("mixed-contention", "deployment-ready", "fail"),
    ("mixed-contention", "storage-clone-ready", "warn"),
    ("mixed-contention", "route-ready", "pass"),
    ("mixed-contention", "vm-runtime-ready", "pass"),
    ("mixed-contention", "smoke-test-ready", "pass"),
    ("mixed-contention", "showroom-healthy", "fail"),
    ("mixed-contention", "model-endpoint-ready", "pass"),

    # provision-blocked: provision-complete FAIL
    ("provision-blocked", "cluster-health", "pass"),
    ("provision-blocked", "run-created", "pass"),
    ("provision-blocked", "provision-complete", "fail"),
    ("provision-blocked", "namespace-ready", "pass"),
    ("provision-blocked", "deployment-ready", "pass"),
    ("provision-blocked", "storage-clone-ready", "pass"),
    ("provision-blocked", "route-ready", "pass"),
    ("provision-blocked", "vm-runtime-ready", "pass"),
    ("provision-blocked", "smoke-test-ready", "pass"),
    ("provision-blocked", "showroom-healthy", "pass"),
    ("provision-blocked", "model-endpoint-ready", "pass"),
]


class TestRubricMatrix:
    """77-cell matrix: scenario × stage → expected outcome."""

    @pytest.mark.parametrize("scenario_name,stage_id,expected_outcome", MATRIX,
                             ids=[f"{s}-{st}" for s, st, _ in MATRIX])
    def test_rubric_evaluation(self, scenario_name, stage_id, expected_outcome):
        """Emulator evidence → rubric evaluator → outcome matches expected."""
        scenario = _load_scenario(scenario_name)
        evidence = scenario.generate_evidence()

        if stage_id not in evidence:
            pytest.skip(f"Scenario {scenario_name} does not generate evidence for {stage_id}")

        stage_evidence = evidence[stage_id]

        if stage_id not in _rubrics:
            pytest.skip(f"No rubric found for {stage_id}")

        rubric = _rubrics[stage_id]
        result = evaluate_rubric(rubric, stage_evidence)

        assert result.outcome.value == expected_outcome, (
            f"Scenario '{scenario_name}', stage '{stage_id}': "
            f"expected {expected_outcome}, got {result.outcome.value}. "
            f"Evidence: {stage_evidence}. "
            f"Failure class: {result.failure_class}. "
            f"Criteria: {[(c.name, c.passed) for c in result.criteria_results]}"
        )
