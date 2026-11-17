"""Integration endpoints — external evidence, feedback, lab status."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from db import repository
from engine.models import Run, RunStatus
from api.schemas import (
    ExternalEvidenceRequest,
    FeedbackRequest,
    GeoluxProposalRequest,
    RotationSnapshotIngest,
    RotationCredentialsIngest,
)
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
def receive_geolux_proposal(body: GeoluxProposalRequest, db: Session = Depends(get_db), _auth=Depends(require_admin)):
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


# The Deepfield incident ingestion endpoint was removed Nov 16:
# Deepfield is an internal product, its incidents were 94% of the
# pending-action queue (10,195 rows), and the calibration study proved
# its confidence scores don't predict outcomes. Internal products stay
# out of the investigations path. Historical rows remain in the DB for
# the adjudication correlation; git history has the endpoint.

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


@router.post("/integration/rotation-snapshot", status_code=201)
def receive_rotation_snapshot(
    req: RotationSnapshotIngest,
    db: Session = Depends(get_db),
    _auth=Depends(require_admin),
):
    """Ingest the admin-run audit's verified-live counts.

    StarGate's cluster-reader SA cannot read Secrets, so verification stays an
    external, read-only audit that posts counts and hashes here — never values.
    Idempotent per (date, provider); unknown providers are created with ticket
    counters at zero and filled by the next Jira sync.
    """
    from db.models import RotationSnapshot

    verified_at = datetime.now(timezone.utc)
    for item in req.providers:
        record = (
            db.query(RotationSnapshot)
            .filter_by(snapshot_date=req.date, provider=item.provider)
            .first()
        )
        if record is None:
            record = RotationSnapshot(
                snapshot_date=req.date,
                provider=item.provider,
                tickets=0,
                closed=0,
                in_progress=0,
                new=0,
                unassigned=0,
            )
            db.add(record)
        record.verified_live = item.verified_live
        record.live_locations = item.live_locations
        record.untracked_live = item.untracked_live
        record.verified_at = verified_at

    db.commit()
    return {"date": req.date.isoformat(), "providers": len(req.providers)}


@router.post("/integration/rotation-credentials", status_code=201)
def receive_rotation_credentials(
    req: RotationCredentialsIngest,
    db: Session = Depends(get_db),
    _auth=Depends(require_admin),
):
    """Ingest per-credential coverage rows (hash ids, counts, locations).

    Aggregates say "50 verified for AWS"; these rows say which 50, where they
    live, and whether a ticket covers each one. No values are accepted or
    stored — only the sha256[:16] identifier the audit already publishes.
    """
    from db.models import RotationCredential, RotationTicket
    from collectors.rotation_sync import bucket_for

    # A ticketed credential inherits its ticket's provider — that join is
    # exact. Only untracked credentials need a name-based guess.
    wanted_keys = {
        key.strip()
        for item in req.credentials
        for key in (item.jira_keys or "").split(";")
        if key.strip()
    }
    ticket_provider = {}
    if wanted_keys:
        ticket_provider = {
            ticket.issue_key: ticket.provider
            for ticket in db.query(RotationTicket)
            .filter(RotationTicket.issue_key.in_(wanted_keys))
            .all()
        }

    verified_at = datetime.now(timezone.utc)
    for item in req.credentials:
        provider = ""
        for key in (item.jira_keys or "").split(";"):
            if key.strip() in ticket_provider:
                provider = ticket_provider[key.strip()]
                break
        if not provider:
            provider = bucket_for(item.provider or f"{item.credential} {item.example_location}")
        record = (
            db.query(RotationCredential)
            .filter_by(snapshot_date=req.date, credential_id=item.id)
            .first()
        )
        if record is None:
            record = RotationCredential(
                snapshot_date=req.date, credential_id=item.id
            )
            db.add(record)
        record.provider = provider
        record.credential = item.credential
        record.live_copies = item.live_copies
        record.clusters = item.clusters or None
        record.example_location = item.example_location or None
        record.coverage = item.coverage or None
        record.jira_keys = item.jira_keys or None
        record.verified_at = verified_at

    db.commit()
    return {"date": req.date.isoformat(), "credentials": len(req.credentials)}
