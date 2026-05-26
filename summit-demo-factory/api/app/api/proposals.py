"""AI proposal endpoints — failure summaries, rubric diffs, PR text."""

from typing import Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.app import repository
from api.app.models import StageOutcome
from api.app.rubric_evaluator import EvaluationResult
from api.app.api._helpers import load_rubric_for_stage

router = APIRouter(prefix="/api/v1", tags=["proposals"])


@router.post("/runs/{run_id}/proposals/summary")
async def generate_failure_summary(run_id: str):
    run = await repository.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    stages = await repository.list_stages(run_id)
    results = []
    for s in stages:
        if s.result:
            results.append(EvaluationResult(
                stage_id=s.stage_id,
                outcome=s.result.outcome,
                failure_class=s.result.failure_class,
                message=s.result.message,
            ))

    from api.app.ai.failure_summarizer import summarize_failures
    summary = summarize_failures(run_id, results)
    return {
        "proposal_id": summary.proposal_id,
        "status": summary.status.value,
        "approved": summary.approved,
        "requires_human_review": summary.requires_human_review,
        "failed_stages": summary.failed_stages,
        "summary": summary.summary,
        "root_cause_hypothesis": summary.root_cause_hypothesis,
        "recommended_actions": summary.recommended_actions,
        "confidence": summary.confidence,
    }


@router.post("/runs/{run_id}/proposals/rubric-diffs")
async def generate_rubric_diffs(run_id: str):
    run = await repository.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    stages = await repository.list_stages(run_id)
    diffs = []
    from api.app.ai.rubric_proposer import propose_new_failure_class

    for s in stages:
        if s.result and s.result.outcome == StageOutcome.FAIL:
            rubric = load_rubric_for_stage(s.stage_id)
            if rubric:
                eval_result = EvaluationResult(
                    stage_id=s.stage_id,
                    outcome=s.result.outcome,
                    failure_class=s.result.failure_class,
                    message=s.result.message,
                )
                diff = propose_new_failure_class(run_id, rubric, eval_result)
                if diff:
                    diffs.append({
                        "proposal_id": diff.proposal_id,
                        "status": diff.status.value,
                        "approved": diff.approved,
                        "rubric_id": diff.rubric_id,
                        "change_type": diff.change_type,
                        "description": diff.description,
                        "proposed_yaml": diff.proposed_yaml,
                        "rationale": diff.rationale,
                    })

    return {"proposals": diffs, "count": len(diffs)}


@router.post("/runs/{run_id}/proposals/pr-text")
async def generate_pr(run_id: str):
    run = await repository.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    stages = await repository.list_stages(run_id)
    from api.app.ai.failure_summarizer import summarize_failures
    from api.app.ai.rubric_proposer import propose_new_failure_class
    from api.app.ai.runbook_proposer import propose_runbook_update
    from api.app.ai.pr_generator import generate_pr_text

    proposals = []
    results = []
    for s in stages:
        if s.result:
            eval_result = EvaluationResult(
                stage_id=s.stage_id,
                outcome=s.result.outcome,
                failure_class=s.result.failure_class,
                message=s.result.message,
            )
            results.append(eval_result)

            if s.result.outcome == StageOutcome.FAIL:
                rubric = load_rubric_for_stage(s.stage_id)
                if rubric:
                    diff = propose_new_failure_class(run_id, rubric, eval_result)
                    if diff:
                        proposals.append(diff)
                update = propose_runbook_update(run_id, eval_result)
                if update:
                    proposals.append(update)

    if results:
        summary = summarize_failures(run_id, results)
        proposals.insert(0, summary)

    return generate_pr_text(proposals, run_id)
