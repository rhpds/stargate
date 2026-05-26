"""Run CRUD endpoints."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.app import repository
from api.app.models import Run, RunStatus

router = APIRouter(prefix="/api/v1", tags=["runs"])


class CreateRunRequest(BaseModel):
    run_id: Optional[str] = None
    demo_id: str
    namespace: str
    requested_by: str
    rubric_version: str
    git_sha: Optional[str] = None


@router.post("/runs", response_model=Run, status_code=201)
async def create_run(req: CreateRunRequest):
    run_id = req.run_id or f"{req.demo_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    run = Run(
        run_id=run_id,
        demo_id=req.demo_id,
        namespace=req.namespace,
        requested_by=req.requested_by,
        status=RunStatus.PENDING,
        rubric_version=req.rubric_version,
        git_sha=req.git_sha,
    )
    existing = await repository.get_run(run_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Run {run_id} already exists")
    return await repository.create_run(run)


@router.get("/runs/{run_id}", response_model=Run)
async def get_run(run_id: str):
    run = await repository.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run


@router.get("/runs", response_model=list[Run])
async def list_runs(limit: int = 100, offset: int = 0):
    return await repository.list_runs(limit=limit, offset=offset)
