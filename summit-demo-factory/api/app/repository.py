"""Data access layer — asyncpg with in-memory fallback."""

import json
from datetime import datetime, timezone
from typing import List, Optional

from api.app.database import get_pool, is_memory_mode
from api.app.models import (
    Evidence,
    EvidenceResource,
    Run,
    RunStatus,
    Stage,
    StageOutcome,
    StageResult,
    StageStatus,
)

# --- In-memory storage (testing / no-DB mode) ---
_runs: dict[str, dict] = {}
_stages: dict[str, list[dict]] = {}
_evidence: dict[str, list[dict]] = {}


def reset_memory():
    """Clear in-memory storage (for testing)."""
    _runs.clear()
    _stages.clear()
    _evidence.clear()


# --- Run ---

async def create_run(run: Run) -> Run:
    if is_memory_mode():
        _runs[run.run_id] = run.model_dump(mode="json")
        return run
    pool = get_pool()
    await pool.execute(
        """INSERT INTO runs (run_id, demo_id, namespace, requested_by, status, rubric_version, git_sha, started_at, completed_at)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
        run.run_id, run.demo_id, run.namespace, run.requested_by,
        run.status.value, run.rubric_version, run.git_sha,
        run.started_at, run.completed_at,
    )
    return run


async def get_run(run_id: str) -> Optional[Run]:
    if is_memory_mode():
        data = _runs.get(run_id)
        return Run(**data) if data else None
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM runs WHERE run_id = $1", run_id)
    return _run_from_row(row) if row else None


async def list_runs(limit: int = 100, offset: int = 0) -> List[Run]:
    if is_memory_mode():
        items = list(_runs.values())
        items.reverse()
        return [Run(**d) for d in items[offset:offset + limit]]
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM runs ORDER BY id DESC LIMIT $1 OFFSET $2", limit, offset)
    return [_run_from_row(r) for r in rows]


async def update_run_status(run_id: str, status: RunStatus,
                            completed_at: Optional[datetime] = None) -> Optional[Run]:
    if is_memory_mode():
        data = _runs.get(run_id)
        if not data:
            return None
        data["status"] = status.value
        if status == RunStatus.RUNNING and not data.get("started_at"):
            data["started_at"] = datetime.now(timezone.utc).isoformat()
        if completed_at:
            data["completed_at"] = completed_at.isoformat()
        elif status in (RunStatus.COMPLETED, RunStatus.FAILED) and not data.get("completed_at"):
            data["completed_at"] = datetime.now(timezone.utc).isoformat()
        return Run(**data)
    pool = get_pool()
    now = datetime.now(timezone.utc)
    started = now if status == RunStatus.RUNNING else None
    comp = completed_at or (now if status in (RunStatus.COMPLETED, RunStatus.FAILED) else None)
    await pool.execute(
        """UPDATE runs SET status = $2,
           started_at = COALESCE(started_at, $3),
           completed_at = COALESCE(completed_at, $4)
           WHERE run_id = $1""",
        run_id, status.value, started, comp,
    )
    return await get_run(run_id)


def _run_from_row(row) -> Run:
    return Run(
        run_id=row["run_id"],
        demo_id=row["demo_id"],
        namespace=row["namespace"],
        requested_by=row["requested_by"],
        status=RunStatus(row["status"]),
        rubric_version=row["rubric_version"],
        git_sha=row["git_sha"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )


# --- Stage ---

async def create_stage(stage: Stage) -> Stage:
    if is_memory_mode():
        key = stage.run_id
        if key not in _stages:
            _stages[key] = []
        _stages[key].append(stage.model_dump(mode="json"))
        return stage
    pool = get_pool()
    result_outcome = stage.result.outcome.value if stage.result else None
    result_fc = stage.result.failure_class if stage.result else None
    result_msg = stage.result.message if stage.result else None
    await pool.execute(
        """INSERT INTO stages (run_id, stage_id, status, started_at, completed_at,
           duration_seconds, result_outcome, result_failure_class, result_message)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
        stage.run_id, stage.stage_id, stage.status.value,
        stage.started_at, stage.completed_at, stage.duration_seconds,
        result_outcome, result_fc, result_msg,
    )
    return stage


async def get_stage(run_id: str, stage_id: str) -> Optional[Stage]:
    if is_memory_mode():
        for s in _stages.get(run_id, []):
            if s["stage_id"] == stage_id:
                return _stage_from_dict(s)
        return None
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM stages WHERE run_id = $1 AND stage_id = $2", run_id, stage_id
    )
    return _stage_from_row(row) if row else None


async def list_stages(run_id: str) -> List[Stage]:
    if is_memory_mode():
        return [_stage_from_dict(s) for s in _stages.get(run_id, [])]
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM stages WHERE run_id = $1 ORDER BY id", run_id)
    return [_stage_from_row(r) for r in rows]


async def update_stage(run_id: str, stage_id: str,
                       status: Optional[StageStatus] = None,
                       started_at: Optional[datetime] = None,
                       completed_at: Optional[datetime] = None,
                       duration_seconds: Optional[float] = None,
                       result: Optional[StageResult] = None) -> Optional[Stage]:
    if is_memory_mode():
        for s in _stages.get(run_id, []):
            if s["stage_id"] == stage_id:
                if status is not None:
                    s["status"] = status.value
                if started_at is not None:
                    s["started_at"] = started_at.isoformat()
                if completed_at is not None:
                    s["completed_at"] = completed_at.isoformat()
                if duration_seconds is not None:
                    s["duration_seconds"] = duration_seconds
                if result is not None:
                    s["result"] = result.model_dump(mode="json")
                return _stage_from_dict(s)
        return None
    pool = get_pool()
    stage = await get_stage(run_id, stage_id)
    if not stage:
        return None
    new_status = status.value if status else stage.status.value
    new_started = started_at or stage.started_at
    new_completed = completed_at or stage.completed_at
    new_duration = duration_seconds if duration_seconds is not None else stage.duration_seconds
    ro = result.outcome.value if result else (stage.result.outcome.value if stage.result else None)
    rfc = result.failure_class if result else (stage.result.failure_class if stage.result else None)
    rm = result.message if result else (stage.result.message if stage.result else None)
    await pool.execute(
        """UPDATE stages SET status=$3, started_at=$4, completed_at=$5,
           duration_seconds=$6, result_outcome=$7, result_failure_class=$8, result_message=$9
           WHERE run_id=$1 AND stage_id=$2""",
        run_id, stage_id, new_status, new_started, new_completed, new_duration, ro, rfc, rm,
    )
    return await get_stage(run_id, stage_id)


def _stage_from_row(row) -> Stage:
    result = None
    if row["result_outcome"]:
        result = StageResult(
            outcome=StageOutcome(row["result_outcome"]),
            failure_class=row["result_failure_class"],
            message=row["result_message"],
        )
    return Stage(
        run_id=row["run_id"],
        stage_id=row["stage_id"],
        status=StageStatus(row["status"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        duration_seconds=row["duration_seconds"],
        result=result,
    )


def _stage_from_dict(d: dict) -> Stage:
    return Stage(**d)


# --- Evidence ---

async def create_evidence(evidence: Evidence) -> Evidence:
    if is_memory_mode():
        key = f"{evidence.run_id}/{evidence.stage_id}"
        if key not in _evidence:
            _evidence[key] = []
        _evidence[key].append(evidence.model_dump(mode="json"))
        _evidence[evidence.evidence_id] = [evidence.model_dump(mode="json")]
        return evidence
    pool = get_pool()
    resource_json = json.dumps(evidence.resource.model_dump()) if evidence.resource else None
    await pool.execute(
        """INSERT INTO evidence (evidence_id, run_id, stage_id, type, source,
           resource, observed, result, timestamp, raw_ref)
           VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10)""",
        evidence.evidence_id, evidence.run_id, evidence.stage_id,
        evidence.type, evidence.source, resource_json,
        json.dumps(evidence.observed), evidence.result.value,
        evidence.timestamp, evidence.raw_ref,
    )
    return evidence


async def get_evidence(evidence_id: str) -> Optional[Evidence]:
    if is_memory_mode():
        items = _evidence.get(evidence_id, [])
        return Evidence(**items[0]) if items else None
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM evidence WHERE evidence_id = $1", evidence_id)
    return _evidence_from_row(row) if row else None


async def list_evidence_for_stage(run_id: str, stage_id: str) -> List[Evidence]:
    if is_memory_mode():
        key = f"{run_id}/{stage_id}"
        return [Evidence(**d) for d in _evidence.get(key, [])]
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT * FROM evidence WHERE run_id = $1 AND stage_id = $2 ORDER BY id",
        run_id, stage_id,
    )
    return [_evidence_from_row(r) for r in rows]


def _evidence_from_row(row) -> Evidence:
    resource = None
    if row["resource"]:
        data = row["resource"] if isinstance(row["resource"], dict) else json.loads(row["resource"])
        resource = EvidenceResource(**data)
    observed = row["observed"] if isinstance(row["observed"], dict) else json.loads(row["observed"])
    return Evidence(
        evidence_id=row["evidence_id"],
        run_id=row["run_id"],
        stage_id=row["stage_id"],
        type=row["type"],
        source=row["source"],
        resource=resource,
        observed=observed,
        result=StageOutcome(row["result"]),
        timestamp=row["timestamp"],
        raw_ref=row["raw_ref"],
    )
