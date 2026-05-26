"""Local Tekton pipeline simulator — runs SDF pipeline logic without a cluster.

Simulates the pipeline flow:
  create-run -> (collect-evidence + evaluate-gate) per stage -> report

Uses oc JSON fixtures as evidence source and the rubric evaluator
for gate decisions. No API server needed — runs entirely in-process.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from api.app.models import StageOutcome
from api.app.rubric_evaluator import EvaluationResult, evaluate_rubric
from api.app.rubric_loader import load_rubrics_from_directory
from collectors.openshift.collect_resource_state import collect_namespace_state
from collectors.openshift.evidence_normalizer import normalize_evidence


@dataclass
class TaskResult:
    task_name: str
    status: str  # "succeeded", "failed", "skipped"
    results: Dict[str, str] = field(default_factory=dict)
    message: str = ""


@dataclass
class StageGateResult:
    stage_id: str
    outcome: StageOutcome
    failure_class: Optional[str] = None
    message: Optional[str] = None
    gate_passed: bool = True


@dataclass
class PipelineSimulationResult:
    run_id: str
    demo_id: str
    namespace: str
    status: str  # "succeeded", "failed"
    tasks: List[TaskResult] = field(default_factory=list)
    gates: List[StageGateResult] = field(default_factory=list)
    blocked_by: Optional[str] = None


PIPELINE_STAGES = [
    "run-created",
    "namespace-ready",
    "deployment-ready",
    "route-ready",
    "smoke-test-ready",
]


def simulate_pipeline(
    demo_id: str,
    namespace: str,
    oc_fixture_dir: Path,
    rubric_dir: Path,
    stages: Optional[List[str]] = None,
    extra_evidence: Optional[Dict[str, Dict]] = None,
) -> PipelineSimulationResult:
    """Simulate a full Tekton pipeline run using local fixtures.

    extra_evidence: optional dict mapping stage_id to additional evidence
    key/value pairs to merge into the normalized evidence for that stage.
    Use this for evidence that can't be derived from oc fixtures (e.g.
    smoke test results that require actual HTTP checks).
    """

    if stages is None:
        stages = PIPELINE_STAGES

    run_id = f"{demo_id}-sim"
    rubrics = {}
    for r in load_rubrics_from_directory(rubric_dir):
        rubrics[r.stage] = r

    create_task = TaskResult(
        task_name="create-run",
        status="succeeded",
        results={"run-id": run_id},
        message=f"Run {run_id} created",
    )

    tasks = [create_task]
    gates: List[StageGateResult] = []
    pipeline_status = "succeeded"
    blocked_by = None

    # Collect all evidence once from fixtures
    evidence_list = collect_namespace_state(oc_fixture_dir)

    for stage_id in stages:
        if blocked_by:
            # Pipeline is blocked — skip remaining stages
            tasks.append(TaskResult(
                task_name=f"collect-{stage_id}",
                status="skipped",
                message=f"Skipped: pipeline blocked by {blocked_by}",
            ))
            tasks.append(TaskResult(
                task_name=f"gate-{stage_id}",
                status="skipped",
                message=f"Skipped: pipeline blocked by {blocked_by}",
            ))
            gates.append(StageGateResult(
                stage_id=stage_id,
                outcome=StageOutcome.INDETERMINATE,
                gate_passed=False,
                message=f"Skipped: blocked by {blocked_by}",
            ))
            continue

        # Simulate collect-evidence task
        collect_task = TaskResult(
            task_name=f"collect-{stage_id}",
            status="succeeded",
            results={"evidence-count": str(len(evidence_list))},
            message=f"Collected {len(evidence_list)} evidence items",
        )
        tasks.append(collect_task)

        # Simulate evaluate-gate task
        rubric = rubrics.get(stage_id)
        if not rubric:
            gate_task = TaskResult(
                task_name=f"gate-{stage_id}",
                status="failed",
                message=f"No rubric found for stage {stage_id}",
            )
            tasks.append(gate_task)
            gates.append(StageGateResult(
                stage_id=stage_id,
                outcome=StageOutcome.FAIL,
                gate_passed=False,
                message=f"No rubric for {stage_id}",
            ))
            pipeline_status = "failed"
            blocked_by = stage_id
            continue

        normalized = normalize_evidence(stage_id, evidence_list)
        if extra_evidence and stage_id in extra_evidence:
            normalized.update(extra_evidence[stage_id])
        result = evaluate_rubric(rubric, normalized)

        gate_passed = result.outcome != StageOutcome.FAIL
        gate_status = "succeeded" if gate_passed else "failed"

        gate_task = TaskResult(
            task_name=f"gate-{stage_id}",
            status=gate_status,
            results={
                "outcome": result.outcome.value,
                "failure-class": result.failure_class or "",
            },
            message=result.message or "",
        )
        tasks.append(gate_task)

        gates.append(StageGateResult(
            stage_id=stage_id,
            outcome=result.outcome,
            failure_class=result.failure_class,
            message=result.message,
            gate_passed=gate_passed,
        ))

        if not gate_passed:
            pipeline_status = "failed"
            blocked_by = stage_id

    # Simulate report task (always runs, as a finally task)
    tasks.append(TaskResult(
        task_name="report",
        status="succeeded",
        message="Report generated",
    ))

    return PipelineSimulationResult(
        run_id=run_id,
        demo_id=demo_id,
        namespace=namespace,
        status=pipeline_status,
        tasks=tasks,
        gates=gates,
        blocked_by=blocked_by,
    )
