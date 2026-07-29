"""Integration endpoints — external evidence, feedback, lab status."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from db import repository
from engine.models import Run, RunStatus
from api.schemas import DeepfieldIncidentRequest, ExternalEvidenceRequest, FeedbackRequest
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


@router.post("/integration/geolux-mpc-action", status_code=201)
def receive_geolux_mpc_action(req: dict, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Receive an MPC-recommended action from GeoLux and route it through the proof system.

    GeoLux's MPC controller recommends actions based on hypothesis generation,
    constraint classification, and geometric stability. This endpoint feeds
    those recommendations into StarGate's proof system to test whether they
    actually work before promoting them to the catalog.

    Flow: GeoLux MPC → this endpoint → proof system → if proven → catalog entry
    """
    import threading
    from engine.proof_orchestrator import run_proof_cycle
    from engine.proof_tracker import ProofTracker
    from api.routers._shared import EXECUTOR_KUBECONFIG
    from db.models import PendingAction, AuditLog

    action = req.get("recommended_action", {})
    action_type = action.get("action_type", "")
    cluster_id = req.get("cluster_id", "")
    failure_class = action.get("parameters", {}).get("failure_class", action_type)
    cycle_id = req.get("cycle_id", "")
    confidence = action.get("score", 0.5)

    if not action_type or action_type == "no_action":
        return {"status": "skipped", "reason": "no_action recommended"}

    # Log the MPC recommendation
    audit = AuditLog(
        action_type=f"geolux_mpc_{action_type}",
        target=cluster_id,
        parameters={
            "source": "geolux_mpc",
            "cycle_id": cycle_id,
            "recommended_action": action,
            "confidence": confidence,
        },
        proposed_by="geolux",
        status="received",
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.commit()

    import logging
    logging.getLogger("stargate").info(
        "GeoLux MPC action received: %s (cycle %s, confidence %.2f)",
        action_type, cycle_id, confidence,
    )

    # If we have a matching injector, route through the proof system
    from engine.failure_injector import INJECTORS
    if failure_class in INJECTORS:
        tracker = ProofTracker()
        tracker.record_injection(failure_class, {"source": "geolux_mpc", "cycle_id": cycle_id, "action": action})

        def _run_proof():
            try:
                from db.database import get_db as _get_db
                bg_db = next(_get_db())
                run_proof_cycle(failure_class=failure_class, kubeconfig=EXECUTOR_KUBECONFIG, mode="manual", db=bg_db)
                bg_db.close()
            except Exception as e:
                logging.getLogger("stargate").error("GeoLux MPC proof cycle failed: %s", e)

        thread = threading.Thread(target=_run_proof, daemon=True)
        thread.start()

        return {
            "status": "proof_cycle_started",
            "failure_class": failure_class,
            "action_type": action_type,
            "message": "MPC recommendation routed to proof system for validation.",
        }

    # No matching injector — queue as a proposal for human review
    pending = PendingAction(
        action_type=f"geolux_mpc_{action_type}",
        target=cluster_id,
        parameters={
            "source": "geolux_mpc",
            "cycle_id": cycle_id,
            "recommended_action": action,
        },
        confidence=confidence,
        proposed_by="geolux",
        source_event_id=cycle_id,
        status="pending",
        proposed_at=datetime.now(timezone.utc),
    )
    db.add(pending)
    db.commit()

    return {
        "status": "queued_for_approval",
        "pending_id": pending.id,
        "action_type": action_type,
        "message": "No matching proof injector — queued for human review.",
    }


@router.post("/integration/geolux-proposal", status_code=201)
def receive_geolux_proposal(body: "GeoluxProposalRequest", db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Receive a remediation proposal from GeoLux.

    GeoLux sends classification results and remediation recommendations
    back to StarGate. These are queued as PendingActions for human review
    through the standard approval queue.

    Expected body:
    {
        "source": "geolux",
        "event_id": "original stargate event id",
        "proposal": {
            "action_type": "cleanup_stuck",
            "target": "namespace-name",
            "failure_class": "pods_crashlooping",
            "confidence": 0.85,
            "reasoning": "GeoLux hypothesis: ...",
            "suggested_commands": ["oc delete pod ..."],
            "cluster": "ocpv05"
        }
    }
    """
    from api.schemas import GeoluxProposalRequest  # noqa: F811
    from db.models import PendingAction, AuditLog

    proposal = body.proposal
    action_type = proposal.get("action_type", "geolux_recommendation")
    target = proposal.get("target", "")
    confidence = float(proposal.get("confidence", 0.5))
    event_id = body.event_id

    if not target:
        raise HTTPException(status_code=422, detail="proposal.target is required")

    pending = PendingAction(
        action_type=action_type,
        target=target,
        parameters={
            "failure_class": proposal.get("failure_class"),
            "reasoning": proposal.get("reasoning"),
            "suggested_commands": proposal.get("suggested_commands", []),
            "cluster": proposal.get("cluster"),
            "source": "geolux",
        },
        confidence=confidence,
        proposed_by="geolux",
        source_event_id=event_id,
        status="pending",
        proposed_at=datetime.now(timezone.utc),
    )
    db.add(pending)

    audit = AuditLog(
        action_type=action_type,
        target=target,
        parameters={"source": "geolux", "confidence": confidence, "failure_class": proposal.get("failure_class")},
        proposed_by="geolux",
        status="proposed",
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.commit()

    import logging
    logging.getLogger("stargate").info(
        "GeoLux proposal received: %s on %s (confidence %.2f)",
        action_type, target, confidence,
    )

    return {
        "pending_id": pending.id,
        "action_type": action_type,
        "target": target,
        "confidence": confidence,
        "status": "queued_for_approval",
    }


@router.post("/integration/deepfield-incident", status_code=201)
def receive_deepfield_incident(body: "DeepfieldIncidentRequest", db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Receive an enriched incident from Deepfield's correlation + RCA pipeline.

    Deepfield sends correlated findings with root cause analysis,
    confidence scores, and remediation options. These are queued as
    PendingActions for human review — NO auto-remediation.
    """
    from api.schemas import DeepfieldIncidentRequest  # noqa: F811
    from db.models import PendingAction, AuditLog

    if not body.incident_id:
        raise HTTPException(status_code=422, detail="incident_id is required")
    if not body.namespace:
        raise HTTPException(status_code=422, detail="namespace is required")

    # Idempotency — check for duplicate incident_id
    existing = db.query(PendingAction).filter(
        PendingAction.source_event_id == body.incident_id,
        PendingAction.proposed_by == "deepfield",
    ).first()
    if existing:
        return {
            "pending_id": existing.id,
            "action_type": existing.action_type,
            "target": existing.target,
            "confidence": body.confidence,
            "status": "already_queued",
        }

    # Dedup — don't create if same namespace + failure_class already pending
    same_pending = db.query(PendingAction).filter(
        PendingAction.target == body.namespace,
        PendingAction.proposed_by == "deepfield",
        PendingAction.status == "pending",
        PendingAction.action_type == f"deepfield_{body.failure_class or 'investigation'}",
    ).first()
    if same_pending:
        return {
            "pending_id": same_pending.id,
            "action_type": same_pending.action_type,
            "target": same_pending.target,
            "confidence": body.confidence,
            "status": "already_pending_for_this_failure",
        }

    action_type = f"deepfield_{body.failure_class or 'investigation'}"

    pending = PendingAction(
        action_type=action_type,
        target=body.namespace,
        parameters={
            "source": "deepfield",
            "incident_id": body.incident_id,
            "cluster": body.cluster,
            "lab_code": body.lab_code,
            "failure_class": body.failure_class,
            "severity": body.severity,
            "rca_output": body.rca_output,
            "correlated_signals": body.correlated_signals[:10],
            "remediation_options": body.remediation_options,
            "evidence_chain": body.evidence_chain[:10],
            "signal_count": body.signal_count,
        },
        confidence=body.confidence,
        proposed_by="deepfield",
        source_event_id=body.incident_id,
        status="pending",
        proposed_at=datetime.now(timezone.utc),
    )
    db.add(pending)

    audit = AuditLog(
        action_type=action_type,
        target=body.namespace,
        parameters={
            "source": "deepfield",
            "incident_id": body.incident_id,
            "confidence": body.confidence,
            "failure_class": body.failure_class,
        },
        proposed_by="deepfield",
        status="proposed",
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.commit()

    import logging
    logging.getLogger("stargate").info(
        "Deepfield incident received: %s on %s (confidence %.2f, %d signals)",
        body.failure_class, body.namespace, body.confidence, body.signal_count,
    )

    return {
        "pending_id": pending.id,
        "action_type": action_type,
        "target": body.namespace,
        "confidence": body.confidence,
        "status": "queued_for_approval",
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
