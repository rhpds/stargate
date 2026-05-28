"""Core CRUD/query endpoints — runs, stages, evidence, evaluation, labs, clusters, events, constraints."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from db.database import get_db
from db import repository
from engine.models import (
    Evidence,
    EvidenceResource,
    Run,
    RunStatus,
    Stage,
    StageOutcome,
    StageResult,
    StageStatus,
)
from engine.rubric_evaluator import evaluate_rubric

from api.schemas import (
    CreateRunRequest,
    SubmitEvidenceRequest,
    EvaluateRequest,
    EvaluateResponse,
)
from api.routers._shared import (
    _event_bus,
    _load_latest_babylon,
    _load_agnosticv_constraints,
    _load_rubric_for_stage,
    limiter,
    require_admin,
    RUBRIC_DIR,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

@router.post("/runs", status_code=201)
def create_run(req: CreateRunRequest, db: Session = Depends(get_db), _auth=Depends(require_admin)):
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
    existing = repository.get_run(db, run_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Run {run_id} already exists")

    # Store lab_code and cluster_name on the DB record
    from db.models import RunRecord
    result = repository.create_run(db, run)
    if req.lab_code or req.cluster_name:
        record = db.query(RunRecord).filter(RunRecord.run_id == run_id).first()
        if record:
            if req.lab_code:
                record.lab_code = req.lab_code
            if req.cluster_name:
                record.cluster_name = req.cluster_name
            db.commit()
    return result


@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = repository.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run


@router.get("/runs")
def list_runs(limit: int = Query(default=100, le=500), offset: int = 0, db: Session = Depends(get_db)):
    return repository.list_runs(db, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

@router.post("/runs/{run_id}/stages/{stage_id}/start", status_code=201)
def start_stage(run_id: str, stage_id: str, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    run = repository.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    existing = repository.get_stage(db, run_id, stage_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Stage {stage_id} already exists")
    if run.status == RunStatus.PENDING:
        repository.update_run_status(db, run_id, RunStatus.RUNNING)
    stage = Stage(
        run_id=run_id,
        stage_id=stage_id,
        status=StageStatus.RUNNING,
        started_at=datetime.now(timezone.utc),
    )
    return repository.create_stage(db, stage)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

@router.post("/runs/{run_id}/stages/{stage_id}/evidence", status_code=201)
def submit_evidence(run_id: str, stage_id: str, req: SubmitEvidenceRequest,
                    db: Session = Depends(get_db), _auth=Depends(require_admin)):
    run = repository.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    stage = repository.get_stage(db, run_id, stage_id)
    if not stage:
        raise HTTPException(status_code=404, detail=f"Stage {stage_id} not found")

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
    return repository.create_evidence(db, evidence)


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------

@router.post("/runs/{run_id}/stages/{stage_id}/evaluate", response_model=EvaluateResponse)
def evaluate_stage(run_id: str, stage_id: str, req: EvaluateRequest,
                   db: Session = Depends(get_db), _auth=Depends(require_admin)):
    run = repository.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    stage = repository.get_stage(db, run_id, stage_id)
    if not stage:
        raise HTTPException(status_code=404, detail=f"Stage {stage_id} not found")

    rubric = _load_rubric_for_stage(stage_id)
    if not rubric:
        raise HTTPException(status_code=404, detail=f"No rubric found for stage {stage_id}")

    if req.evidence is not None:
        evidence_data = req.evidence
    else:
        evidence_records = repository.list_evidence_for_stage(db, run_id, stage_id)
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
    repository.update_stage(db, run_id, stage_id, status=stage_status, result=stage_result)

    criteria = [
        {"name": c.name, "required": c.required, "passed": c.passed}
        for c in result.criteria_results
    ]

    # Get lab_code and cluster_name from the run's DB record
    from db.models import RunRecord
    run_record = db.query(RunRecord).filter(RunRecord.run_id == run_id).first()
    lab_code = run_record.lab_code if run_record else None
    cluster_name = run_record.cluster_name if run_record else None

    repository.create_evaluation(
        db, run_id, stage_id,
        outcome=result.outcome.value,
        failure_class=result.failure_class,
        message=result.message,
        criteria_results=criteria,
        lab_code=lab_code,
        cluster_name=cluster_name,
    )

    # Emit event
    from events.models import Event as StarGateEvent
    event_type = {
        "pass": "evaluation.passed",
        "warn": "evaluation.warned",
        "fail": "evaluation.failed",
    }.get(result.outcome.value, "evaluation.failed")

    if result.outcome.value == "fail" and not result.failure_class:
        event_type = "failure.unclassified"

    _event_bus.emit(StarGateEvent(
        event_type=event_type,
        run_id=run_id,
        stage_id=stage_id,
        lab_code=lab_code,
        cluster_name=cluster_name,
        outcome=result.outcome.value,
        failure_class=result.failure_class,
        message=result.message,
    ))

    return {
        "stage_id": result.stage_id,
        "outcome": result.outcome.value,
        "failure_class": result.failure_class,
        "message": result.message,
        "criteria": criteria,
    }


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}/report")
def get_run_report(run_id: str, db: Session = Depends(get_db)):
    run = repository.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    stages = repository.list_stages(db, run_id)
    stage_reports = []
    passed = failed = warned = pending_count = 0

    for s in stages:
        evidence_list = repository.list_evidence_for_stage(db, run_id, s.stage_id)
        outcome = s.result.outcome.value if s.result else None
        stage_reports.append({
            "stage_id": s.stage_id,
            "status": s.status.value,
            "outcome": outcome,
            "failure_class": s.result.failure_class if s.result else None,
            "message": s.result.message if s.result else None,
            "duration_seconds": s.duration_seconds,
            "evidence_count": len(evidence_list),
        })
        if s.status == StageStatus.PASSED:
            passed += 1
        elif s.status == StageStatus.FAILED:
            failed += 1
        elif s.status == StageStatus.WARNED:
            warned += 1
        else:
            pending_count += 1

    return {
        "run_id": run.run_id,
        "demo_id": run.demo_id,
        "namespace": run.namespace,
        "status": run.status.value,
        "rubric_version": run.rubric_version,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "stages": stage_reports,
        "passed": passed,
        "failed": failed,
        "warned": warned,
        "pending": pending_count,
    }


# ---------------------------------------------------------------------------
# Bundle (Stage 3 -- with history)
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}/bundle")
def get_bundle(run_id: str, db: Session = Depends(get_db)):
    run = repository.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    stages = repository.list_stages(db, run_id)

    # Current evaluation
    current_stages = []
    lab_code = None
    cluster_name = None

    for s in stages:
        stage_data = {
            "stage_id": s.stage_id,
            "outcome": s.result.outcome.value if s.result else None,
            "failure_class": s.result.failure_class if s.result else None,
            "message": s.result.message if s.result else None,
        }
        current_stages.append(stage_data)

    # Try to find lab_code and cluster_name from evaluations
    evals = repository.list_evaluations(db, limit=5)
    for ev in evals:
        if ev.run_id == run_id:
            lab_code = ev.lab_code
            cluster_name = ev.cluster_name
            break

    # History: past evaluations for the same lab
    history = []
    if lab_code:
        history = repository.get_evaluation_history(
            db, lab_code=lab_code, cluster_name=cluster_name, limit=20
        )

    # Failure class frequency
    failure_frequency = {}
    if lab_code:
        failure_frequency = repository.get_failure_class_frequency(
            db, lab_code=lab_code, cluster_name=cluster_name
        )

    # Last passing run
    last_pass = None
    if lab_code:
        last_pass = repository.get_last_passing_run(db, lab_code=lab_code)

    # Cluster context
    cluster_summary = None
    if cluster_name:
        cluster_summary = repository.get_cluster_failure_summary(db, cluster_name=cluster_name)

    # AgnosticV constraints
    agnosticv_constraints = _load_agnosticv_constraints(lab_code)

    return {
        "run_id": run.run_id,
        "lab_code": lab_code,
        "cluster_name": cluster_name,
        "current": {"stages": current_stages},
        "history": history,
        "failure_frequency": failure_frequency,
        "last_passing_run": last_pass,
        "cluster_summary": cluster_summary,
        "constraints": agnosticv_constraints,
    }


# ---------------------------------------------------------------------------
# History & Aggregation (labs / clusters)
# ---------------------------------------------------------------------------

@router.get("/labs/{lab_code}/history")
def get_lab_history(
    lab_code: str,
    cluster: Optional[str] = None,
    stage: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Get evaluation history for a lab."""
    return repository.get_evaluation_history(
        db, lab_code=lab_code, cluster_name=cluster, stage_id=stage, limit=limit
    )


@router.get("/labs/{lab_code}/failures")
def get_lab_failures(
    lab_code: str,
    cluster: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get failure class frequency for a lab."""
    return repository.get_failure_class_frequency(db, lab_code=lab_code, cluster_name=cluster)


@router.get("/clusters/{cluster_name}/summary")
def get_cluster_summary(cluster_name: str, db: Session = Depends(get_db)):
    """Get aggregated failure data for a cluster."""
    return repository.get_cluster_failure_summary(db, cluster_name=cluster_name)


@router.get("/clusters/{cluster_name}/failures")
def get_cluster_failures(cluster_name: str, db: Session = Depends(get_db)):
    """Get failure class frequency for a cluster."""
    return repository.get_failure_class_frequency(db, cluster_name=cluster_name)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@router.get("/events")
def get_events(
    event_type: Optional[str] = None,
    cluster: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Query events -- combines in-memory (current session) with persisted DB (survives restarts)."""
    from db.models import EventLog

    # Try DB first for durable history
    query = db.query(EventLog).filter(EventLog.filtered == False)
    if event_type:
        query = query.filter(EventLog.event_type == event_type)
    if cluster:
        query = query.filter(EventLog.cluster_name == cluster)
    db_events = query.order_by(EventLog.id.desc()).limit(limit).all()

    if db_events:
        return [
            {
                "event_id": e.event_id,
                "event_type": e.event_type,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "run_id": e.run_id,
                "stage_id": e.stage_id,
                "lab_code": e.lab_code,
                "cluster_name": e.cluster_name,
                "outcome": e.outcome,
                "failure_class": e.failure_class,
                "message": e.message,
                "priority": e.priority,
                "metadata": e.metadata_json or {},
                "filtered": e.filtered,
                "correlated": False,
                "systemic": e.systemic,
                "deduplicated": False,
                "blast_radius": e.blast_radius,
            }
            for e in db_events
        ]

    # Fallback to in-memory
    events = _event_bus.get_recent(event_type=event_type, limit=limit)
    if cluster:
        events = [e for e in events if e.get("cluster_name") == cluster]
    return events


@router.get("/events/summary")
def get_events_summary(db: Session = Depends(get_db)):
    """Summary of event activity -- from DB for durability."""
    from db.models import EventLog
    from sqlalchemy import func

    total = db.query(func.count(EventLog.id)).scalar() or 0
    filtered = db.query(func.count(EventLog.id)).filter(EventLog.filtered == True).scalar() or 0
    systemic = db.query(func.count(EventLog.id)).filter(EventLog.systemic == True).scalar() or 0
    escalated = 0  # Would need metadata_json query

    by_type: Dict = {}
    type_counts = db.query(EventLog.event_type, func.count(EventLog.id)).group_by(EventLog.event_type).all()
    for event_type, count in type_counts:
        by_type[event_type] = count

    # Fall back to in-memory if DB empty
    if total == 0:
        history = _event_bus.history
        total = len(history)
        filtered = sum(1 for e in history if e.filtered)
        for e in history:
            by_type[e.event_type] = by_type.get(e.event_type, 0) + 1
        systemic = sum(1 for e in history if e.systemic)
        escalated = sum(1 for e in history if e.metadata.get("escalate"))

    return {
        "total_events": total,
        "filtered": filtered,
        "delivered": total - filtered,
        "systemic": systemic,
        "escalated": escalated,
        "by_type": by_type,
        "filter_rate": round(filtered / max(total, 1) * 100, 1),
    }


@router.post("/events/consumers")
def register_consumer(body: Dict, _auth=Depends(require_admin)):
    """Register a webhook consumer."""
    url = body.get("url")
    event_types = body.get("event_types")
    if not url:
        raise HTTPException(status_code=422, detail="url is required")
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=422, detail="url must use http or https")
    blocked = ("metadata.google", "169.254.169.254", "kubernetes.default", ".svc", "localhost", "127.0.0.1", "::1")
    if any(b in (parsed.hostname or "") for b in blocked):
        raise HTTPException(status_code=422, detail="url targets a blocked internal address")
    from events.consumers import WebhookConsumer
    consumer = WebhookConsumer(url=url, event_types=event_types)
    _event_bus.register_consumer(consumer)
    return {"registered": True, "url": url, "event_types": event_types}


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

@router.get("/constraints/{lab_id}")
def get_lab_constraints(lab_id: str):
    """Get AgnosticV constraints for a lab."""
    constraints = _load_agnosticv_constraints(lab_id)
    if not constraints:
        raise HTTPException(status_code=404, detail=f"No constraints found for {lab_id}")
    return constraints


@router.get("/constraints")
def list_all_constraints():
    """List constraints for all Summit 2026 labs."""
    agnosticv_dir = Path(__file__).parent.parent.parent.parent / "github review" / "agnosticv"
    if not agnosticv_dir.exists():
        return {"error": "AgnosticV repo not found"}
    from constraints.agnosticv_loader import load_all_constraints
    return load_all_constraints(agnosticv_dir)
