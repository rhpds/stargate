"""Stage lifecycle endpoints."""

from datetime import datetime, timezone
from typing import Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.app import repository
from api.app.models import (
    Evidence,
    EvidenceResource,
    RunStatus,
    Stage,
    StageOutcome,
    StageResult,
    StageStatus,
)
from api.app.rubric_evaluator import evaluate_rubric
from api.app.api._helpers import load_rubric_for_stage
from api.app.schema_validator import validate_evidence as validate_evidence_schema, SchemaValidationError

router = APIRouter(prefix="/api/v1", tags=["stages"])


class SubmitEvidenceRequest(BaseModel):
    evidence_id: Optional[str] = None
    type: str
    source: str
    resource: Optional[Dict] = None
    observed: Dict
    result: str
    timestamp: Optional[str] = None
    raw_ref: Optional[str] = None


class EvaluateStageRequest(BaseModel):
    evidence: Optional[Dict] = None


@router.post("/runs/{run_id}/stages/{stage_id}/start", response_model=Stage, status_code=201)
async def start_stage(run_id: str, stage_id: str):
    run = await repository.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    existing = await repository.get_stage(run_id, stage_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Stage {stage_id} already exists for run {run_id}")

    if run.status == RunStatus.PENDING:
        await repository.update_run_status(run_id, RunStatus.RUNNING)

    stage = Stage(
        run_id=run_id,
        stage_id=stage_id,
        status=StageStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    return await repository.create_stage(stage)


@router.post("/runs/{run_id}/stages/{stage_id}/evidence", response_model=Evidence, status_code=201)
async def submit_evidence(run_id: str, stage_id: str, req: SubmitEvidenceRequest):
    run = await repository.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    stage = await repository.get_stage(run_id, stage_id)
    if not stage:
        raise HTTPException(status_code=404, detail=f"Stage {stage_id} not found for run {run_id}")

    if stage.status in (StageStatus.PASSED, StageStatus.FAILED, StageStatus.WARNED):
        raise HTTPException(status_code=409, detail=f"Stage {stage_id} is already completed ({stage.status.value})")

    evidence_id = req.evidence_id or f"ev-{uuid4().hex[:8]}"
    ts = datetime.fromisoformat(req.timestamp) if req.timestamp else datetime.now(timezone.utc)
    resource = EvidenceResource(**req.resource) if req.resource else None

    evidence = Evidence(
        evidence_id=evidence_id,
        run_id=run_id,
        stage_id=stage_id,
        type=req.type,
        source=req.source,
        resource=resource,
        observed=req.observed,
        result=StageOutcome(req.result),
        timestamp=ts,
        raw_ref=req.raw_ref,
    )

    try:
        evidence_dict = evidence.model_dump(mode="json")
        if evidence_dict.get("timestamp") and not isinstance(evidence_dict["timestamp"], str):
            evidence_dict["timestamp"] = evidence.timestamp.isoformat()
        validate_evidence_schema(evidence_dict)
    except SchemaValidationError as e:
        raise HTTPException(status_code=422, detail=f"Evidence schema validation failed: {e.errors}")

    return await repository.create_evidence(evidence)


@router.post("/runs/{run_id}/stages/{stage_id}/evaluate")
async def evaluate_stage(run_id: str, stage_id: str, req: EvaluateStageRequest):
    run = await repository.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    stage = await repository.get_stage(run_id, stage_id)
    if not stage:
        raise HTTPException(status_code=404, detail=f"Stage {stage_id} not found for run {run_id}")

    rubric = load_rubric_for_stage(stage_id)
    if not rubric:
        raise HTTPException(status_code=404, detail=f"No rubric found for stage {stage_id}")

    if req.evidence is not None:
        evidence_data = req.evidence
    else:
        evidence_records = await repository.list_evidence_for_stage(run_id, stage_id)
        evidence_data = {}
        for ev in evidence_records:
            evidence_data.update(ev.observed)

    result = evaluate_rubric(rubric, evidence_data)

    stage_status = StageStatus.PASSED
    if result.outcome == StageOutcome.FAIL:
        stage_status = StageStatus.FAILED
    elif result.outcome == StageOutcome.WARN:
        stage_status = StageStatus.WARNED

    stage_result = StageResult(
        outcome=result.outcome,
        failure_class=result.failure_class,
        message=result.message,
    )
    await repository.update_stage(run_id, stage_id, status=stage_status, result=stage_result)

    from api.app.integrations.event_publisher import publish_evaluation
    await publish_evaluation("evaluation_result", {
        "run_id": run_id,
        "stage_id": stage_id,
        "outcome": result.outcome.value,
        "failure_class": result.failure_class,
        "message": result.message,
        "namespace": run.namespace,
        "demo_id": run.demo_id,
    })

    return {
        "stage_id": result.stage_id,
        "outcome": result.outcome.value,
        "failure_class": result.failure_class,
        "message": result.message,
        "criteria": [
            {"name": c.name, "required": c.required, "passed": c.passed}
            for c in result.criteria_results
        ],
    }


@router.post("/runs/{run_id}/stages/{stage_id}/complete", response_model=Stage)
async def complete_stage(run_id: str, stage_id: str):
    stage = await repository.get_stage(run_id, stage_id)
    if not stage:
        raise HTTPException(status_code=404, detail=f"Stage {stage_id} not found for run {run_id}")

    now = datetime.now(timezone.utc)
    duration = None
    if stage.started_at:
        started = stage.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        duration = (now - started).total_seconds()

    if stage.status not in (StageStatus.RUNNING, StageStatus.PASSED, StageStatus.WARNED, StageStatus.FAILED):
        raise HTTPException(status_code=409, detail=f"Stage {stage_id} is in status {stage.status.value}, cannot complete")

    if stage.status == StageStatus.RUNNING and not stage.result:
        raise HTTPException(status_code=409, detail=f"Stage {stage_id} has not been evaluated yet")

    status = stage.status
    if status == StageStatus.RUNNING:
        if stage.result.outcome == StageOutcome.FAIL:
            status = StageStatus.FAILED
        elif stage.result.outcome == StageOutcome.WARN:
            status = StageStatus.WARNED
        else:
            status = StageStatus.PASSED

    return await repository.update_stage(
        run_id, stage_id,
        status=status,
        completed_at=now,
        duration_seconds=duration,
    )
