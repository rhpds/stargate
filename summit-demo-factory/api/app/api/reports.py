"""Run report and bottleneck analysis endpoints."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.app import repository
from api.app.models import StageStatus

router = APIRouter(prefix="/api/v1", tags=["reports"])


class RunReportStage(BaseModel):
    stage_id: str
    status: str
    outcome: Optional[str] = None
    failure_class: Optional[str] = None
    message: Optional[str] = None
    duration_seconds: Optional[float] = None
    evidence_count: int = 0


class RunReport(BaseModel):
    run_id: str
    demo_id: str
    namespace: str
    status: str
    rubric_version: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    stages: List[RunReportStage] = []
    passed: int = 0
    failed: int = 0
    warned: int = 0
    pending: int = 0


class BottleneckEntry(BaseModel):
    stage_id: str
    duration_seconds: Optional[float] = None
    status: str


@router.get("/runs/{run_id}/report", response_model=RunReport)
async def get_run_report(run_id: str):
    run = await repository.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    stages = await repository.list_stages(run_id)
    stage_reports = []
    passed = failed = warned = pending_count = 0

    for s in stages:
        evidence_list = await repository.list_evidence_for_stage(run_id, s.stage_id)
        outcome = s.result.outcome.value if s.result else None
        stage_reports.append(RunReportStage(
            stage_id=s.stage_id,
            status=s.status.value,
            outcome=outcome,
            failure_class=s.result.failure_class if s.result else None,
            message=s.result.message if s.result else None,
            duration_seconds=s.duration_seconds,
            evidence_count=len(evidence_list),
        ))
        if s.status == StageStatus.PASSED:
            passed += 1
        elif s.status == StageStatus.FAILED:
            failed += 1
        elif s.status == StageStatus.WARNED:
            warned += 1
        else:
            pending_count += 1

    return RunReport(
        run_id=run.run_id,
        demo_id=run.demo_id,
        namespace=run.namespace,
        status=run.status.value,
        rubric_version=run.rubric_version,
        started_at=run.started_at,
        completed_at=run.completed_at,
        stages=stage_reports,
        passed=passed,
        failed=failed,
        warned=warned,
        pending=pending_count,
    )


@router.get("/runs/{run_id}/bottlenecks", response_model=List[BottleneckEntry])
async def get_bottlenecks(run_id: str):
    run = await repository.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    stages = await repository.list_stages(run_id)
    entries = [
        BottleneckEntry(
            stage_id=s.stage_id,
            duration_seconds=s.duration_seconds,
            status=s.status.value,
        )
        for s in stages
        if s.duration_seconds is not None
    ]
    entries.sort(key=lambda e: e.duration_seconds or 0, reverse=True)
    return entries
