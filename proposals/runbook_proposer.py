"""Runbook update proposer — generates proposed remediation catalog updates.

Analyzes failure patterns and proposes new remediation entries
or updates to existing ones. All proposals are reviewable diffs.
"""

from __future__ import annotations

from typing import Dict, List
from uuid import uuid4

import yaml

from proposals.models import RunbookUpdate
from engine.rubric_evaluator import EvaluationResult
from engine.models import StageOutcome


REMEDIATION_TEMPLATES = {
    "pods_crashlooping": {
        "id": "collect_crashloop_diagnostics",
        "risk": "low",
        "mode": "recommend_only",
        "scope": "namespace",
        "requires_approval": False,
        "commands": [
            "oc logs -n {namespace} {pod} --previous --tail=100",
            "oc get events -n {namespace} --sort-by=.lastTimestamp",
            "oc describe pod -n {namespace} {pod}",
        ],
    },
    "service_has_no_endpoints": {
        "id": "collect_selector_mismatch_diagnostics",
        "risk": "low",
        "mode": "recommend_only",
        "scope": "namespace",
        "requires_approval": False,
        "commands": [
            "oc get svc -n {namespace} -o yaml",
            "oc get pods -n {namespace} --show-labels",
            "oc get endpoints -n {namespace}",
        ],
    },
    "pods_not_ready": {
        "id": "collect_pod_readiness_diagnostics",
        "risk": "low",
        "mode": "recommend_only",
        "scope": "namespace",
        "requires_approval": False,
        "commands": [
            "oc get pods -n {namespace} -o wide",
            "oc describe pods -n {namespace}",
            "oc get events -n {namespace} --field-selector reason=Unhealthy",
        ],
    },
}


def propose_runbook_update(
    run_id: str,
    result: EvaluationResult,
    existing_remediation_ids: List[str] = None,
) -> RunbookUpdate | None:
    """Propose a new remediation catalog entry for a failure class."""
    if result.outcome != StageOutcome.FAIL:
        return None
    if not result.failure_class:
        return None

    template = REMEDIATION_TEMPLATES.get(result.failure_class)
    if not template:
        return _propose_generic_runbook(run_id, result)

    if existing_remediation_ids and template["id"] in existing_remediation_ids:
        return None

    return RunbookUpdate(
        proposal_id=f"runbook-{uuid4().hex[:8]}",
        source_run_id=run_id,
        source_stage_id=result.stage_id,
        target_id=template["id"],
        change_type="add_remediation",
        description=f"Add remediation '{template['id']}' for failure class '{result.failure_class}'",
        current_content="",
        proposed_content=yaml.dump(template, default_flow_style=False),
        rationale=(
            f"Stage {result.stage_id} failed with class '{result.failure_class}'. "
            f"This remediation collects diagnostic information to help resolve the issue."
        ),
        applicable_failure_classes=[result.failure_class],
    )


def _propose_generic_runbook(
    run_id: str,
    result: EvaluationResult,
) -> RunbookUpdate:
    """Propose a generic diagnostic remediation for unknown failure classes."""
    failed_criteria = [c.name for c in result.criteria_results if not c.passed]

    generic = {
        "id": f"investigate_{result.stage_id}_{result.failure_class or 'unknown'}",
        "risk": "low",
        "mode": "recommend_only",
        "scope": "namespace",
        "requires_approval": False,
        "commands": [
            "oc get all -n {namespace}",
            "oc get events -n {namespace} --sort-by=.lastTimestamp",
        ],
    }

    return RunbookUpdate(
        proposal_id=f"runbook-{uuid4().hex[:8]}",
        source_run_id=run_id,
        source_stage_id=result.stage_id,
        target_id=generic["id"],
        change_type="add_remediation",
        description=f"Add generic diagnostic remediation for {result.stage_id}",
        current_content="",
        proposed_content=yaml.dump(generic, default_flow_style=False),
        rationale=(
            f"Stage {result.stage_id} failed with unrecognized failure class "
            f"'{result.failure_class}'. Failed criteria: {', '.join(failed_criteria)}. "
            f"A generic diagnostic remediation can help gather information."
        ),
        applicable_failure_classes=[result.failure_class or "unknown"],
    )
