"""Integration endpoints — external evidence, feedback, lab status."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from db import repository
from engine.models import Run, RunStatus
from api.schemas import ExternalEvidenceRequest, FeedbackRequest
from api.routers._shared import _event_bus, require_admin

router = APIRouter()


@router.post("/integration/external-evidence", status_code=201)
def receive_external_evidence(req: ExternalEvidenceRequest, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Receive evidence from Demolition or other external systems."""
    run_id = f"ext-{req.source}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    run = Run(
        run_id=run_id,
        demo_id=f"external-{req.source}",
        namespace=req.workshop_url or req.lab_code or "external",
        requested_by=req.source,
        status=RunStatus.COMPLETED if req.outcome == "pass" else RunStatus.FAILED,
        rubric_version="external",
    )
    repository.create_run(db, run)

    from db.models import RunRecord
    record = db.query(RunRecord).filter(RunRecord.run_id == run_id).first()
    if record:
        record.lab_code = req.lab_code
        record.cluster_name = req.cluster_name
        db.commit()

    from events.models import Event as StarGateEvent
    _event_bus.emit(StarGateEvent(
        event_type="evaluation.passed" if req.outcome == "pass" else "evaluation.failed",
        run_id=run_id,
        lab_code=req.lab_code,
        cluster_name=req.cluster_name,
        outcome=req.outcome,
        message=req.error_summary,
        metadata={
            "source": req.source,
            "session_id": req.session_id,
            "session_name": req.session_name,
            "steps_passed": req.steps_passed,
            "steps_failed": req.steps_failed,
        },
    ))

    return {"run_id": run_id, "source": req.source, "outcome": req.outcome}


@router.post("/integration/feedback/{run_id}")
def submit_feedback(run_id: str, req: FeedbackRequest, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Submit HITL feedback on an evaluation."""
    from db.models import EvaluationRecord

    evals = (
        db.query(EvaluationRecord)
        .filter(EvaluationRecord.run_id == run_id)
        .all()
    )

    if not evals:
        raise HTTPException(status_code=404, detail=f"No evaluations found for run {run_id}")

    updated = 0
    for ev in evals:
        if req.correct_classification is not None:
            ev.human_confirmed = req.correct_classification
        if req.corrected_class:
            ev.human_corrected_class = req.corrected_class
        if req.notes:
            ev.human_notes = req.notes
        updated += 1

    db.commit()

    return {
        "run_id": run_id,
        "evaluations_updated": updated,
        "feedback": {
            "action_taken": req.action_taken,
            "worked": req.worked,
            "correct_classification": req.correct_classification,
            "corrected_class": req.corrected_class,
            "reviewed_by": req.reviewed_by,
        },
    }


@router.get("/integration/lab-status/{lab_code}")
def get_lab_validation_status(lab_code: str, db: Session = Depends(get_db)):
    """Get the current validation status for a lab."""
    history = repository.get_evaluation_history(db, lab_code=lab_code, limit=10)
    failures = repository.get_failure_class_frequency(db, lab_code=lab_code)
    last_pass = repository.get_last_passing_run(db, lab_code=lab_code)

    if not history:
        raise HTTPException(status_code=404, detail=f"No evaluations found for {lab_code}")

    latest = history[0]
    return {
        "lab_code": lab_code,
        "latest_outcome": latest.get("outcome"),
        "latest_failure_class": latest.get("failure_class"),
        "latest_message": latest.get("message"),
        "latest_evaluated_at": latest.get("evaluated_at"),
        "latest_cluster": latest.get("cluster_name"),
        "total_evaluations": len(history),
        "failure_classes": failures,
        "last_passing_run": last_pass,
        "history": history,
    }
