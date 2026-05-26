"""Rubric diff proposer — generates proposed rubric changes from failure patterns.

Analyzes repeated failures and proposes rubric improvements:
- New failure classes for unclassified failures
- New exit criteria to catch issues earlier
- Reordering failure classes by frequency

All proposals are marked proposed/unapproved. No direct mutation.
"""

from __future__ import annotations

from typing import Dict, List
from uuid import uuid4

import yaml

from api.app.ai.models import RubricDiff
from api.app.models import Rubric
from api.app.rubric_evaluator import EvaluationResult
from api.app.models import StageOutcome


def propose_new_failure_class(
    run_id: str,
    rubric: Rubric,
    result: EvaluationResult,
) -> RubricDiff | None:
    """Propose a new failure class when a failure is unclassified."""
    if result.outcome != StageOutcome.FAIL:
        return None
    if result.failure_class is not None:
        return None

    failed_criteria = [c for c in result.criteria_results if not c.passed and c.required]
    if not failed_criteria:
        return None

    class_name = "_and_".join(c.name for c in failed_criteria) + "_failed"
    conditions = [f"{c.name} == false" for c in failed_criteria]

    new_class = {
        class_name: {
            "when": conditions,
            "recommended_action": f"investigate_{class_name}",
        }
    }

    current_classes = {k: {"when": v.when, "recommended_action": v.recommended_action}
                       for k, v in rubric.failure_classes.items()}
    proposed_classes = dict(current_classes)
    proposed_classes.update(new_class)

    return RubricDiff(
        proposal_id=f"rubric-diff-{uuid4().hex[:8]}",
        source_run_id=run_id,
        source_stage_id=result.stage_id,
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        change_type="add_failure_class",
        description=f"Add failure class '{class_name}' to classify unclassified failure in stage {result.stage_id}",
        current_yaml=yaml.dump({"failure_classes": current_classes}, default_flow_style=False),
        proposed_yaml=yaml.dump({"failure_classes": proposed_classes}, default_flow_style=False),
        rationale=(
            f"Stage {result.stage_id} failed without a matching failure class. "
            f"Failed criteria: {', '.join(c.name for c in failed_criteria)}. "
            f"Adding a class enables targeted remediation."
        ),
        supporting_evidence=[{
            "stage_id": result.stage_id,
            "failed_criteria": [c.name for c in failed_criteria],
            "outcome": result.outcome.value,
        }],
    )


def propose_additional_criterion(
    run_id: str,
    rubric: Rubric,
    criterion_name: str,
    required: bool,
    rationale: str,
) -> RubricDiff:
    """Propose adding a new exit criterion to a rubric."""
    current_criteria = [{"name": c.name, "required": c.required} for c in rubric.exit_criteria]
    proposed_criteria = list(current_criteria) + [{"name": criterion_name, "required": required}]

    return RubricDiff(
        proposal_id=f"rubric-diff-{uuid4().hex[:8]}",
        source_run_id=run_id,
        source_stage_id=rubric.stage,
        rubric_id=rubric.id,
        rubric_version=rubric.version,
        change_type="add_exit_criterion",
        description=f"Add exit criterion '{criterion_name}' (required={required}) to rubric {rubric.id}",
        current_yaml=yaml.dump({"exit_criteria": current_criteria}, default_flow_style=False),
        proposed_yaml=yaml.dump({"exit_criteria": proposed_criteria}, default_flow_style=False),
        rationale=rationale,
        supporting_evidence=[],
    )
