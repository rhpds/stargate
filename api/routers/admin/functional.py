"""Read/review APIs for the gated functional-alignment pipeline."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.routers._shared import require_admin, require_admin_read
from db.database import get_db

router = APIRouter(prefix="/admin/functional", tags=["functional-alignment"])


def _row(obj, fields):
    result = {}
    for field in fields:
        value = getattr(obj, field, None)
        result[field] = value.isoformat() if isinstance(value, datetime) else value
    return result


@router.get("/source-events", dependencies=[Depends(require_admin_read)])
def source_events(state: Optional[str] = None, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    from db.models import SourceEvent
    query = db.query(SourceEvent)
    if state:
        query = query.filter(SourceEvent.state == state)
    rows = query.order_by(SourceEvent.last_seen_at.desc()).limit(limit).all()
    fields = ("id", "source_system", "source_instance", "source_event_id", "evidence_hash", "state",
              "job_id", "job_url", "task", "play", "role", "guid", "catalog_item", "stage", "action",
              "provider", "cluster", "failure_class", "normalized_error", "occurred_at", "first_seen_at",
              "last_seen_at", "claimed_at", "diagnosed_at", "reviewed_at")
    return {"items": [_row(item, fields) for item in rows]}


@router.get("/source-events/{event_id}/diagnosis", dependencies=[Depends(require_admin_read)])
def event_diagnosis(event_id: int, db: Session = Depends(get_db)):
    from db.models import InvestigationRecord, InvestigationSourceEvent, SourceEvent
    event = db.query(SourceEvent).filter_by(id=event_id).first()
    if not event:
        raise HTTPException(404, "Source event not found")
    links = db.query(InvestigationSourceEvent).filter_by(source_event_id=event_id).all()
    investigations = [db.query(InvestigationRecord).filter_by(id=link.investigation_id).first() for link in links]
    return {"source_event_id": event.id, "state": event.state, "investigations": [
        {"id": inv.id, "job_id": inv.job_id, "status": inv.status, "diagnosis_version": inv.diagnosis_version,
         "review_state": inv.review_state, "evidence_hash": inv.evidence_hash}
        for inv in investigations if inv
    ]}


@router.get("/notifications", dependencies=[Depends(require_admin_read)])
def notifications(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    from db.models import NotificationDelivery
    fields = ("id", "channel", "dedup_key", "payload_hash", "investigation_id", "diagnosis_version",
              "status", "attempt_count", "external_message_id", "last_error", "next_attempt_at", "created_at", "sent_at")
    rows = db.query(NotificationDelivery).order_by(NotificationDelivery.id.desc()).limit(limit).all()
    return {"items": [_row(item, fields) for item in rows]}


@router.get("/tickets", dependencies=[Depends(require_admin_read)])
def tickets(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    from db.models import ExternalTicket
    fields = ("id", "system", "dedup_signature", "active", "ticket_key", "ticket_url", "status",
              "investigation_id", "diagnosis_version", "source_event_ids", "draft_payload", "last_error",
              "created_at", "updated_at")
    rows = db.query(ExternalTicket).order_by(ExternalTicket.id.desc()).limit(limit).all()
    return {"items": [_row(item, fields) for item in rows]}


@router.post("/investigations/{investigation_id}/review", dependencies=[Depends(require_admin)])
def review_investigation(investigation_id: int, body: dict, db: Session = Depends(get_db)):
    from db.models import InvestigationRecord, InvestigationSourceEvent, SourceEvent
    state = body.get("state")
    if state not in ("reviewed", "suppressed"):
        raise HTTPException(422, "state must be reviewed or suppressed")
    inv = db.query(InvestigationRecord).filter_by(id=investigation_id).first()
    if not inv or inv.status != "complete":
        raise HTTPException(404, "Completed investigation not found")
    inv.review_state, inv.reviewed_by, inv.reviewed_at = state, body.get("reviewed_by", "admin"), datetime.now(timezone.utc)
    for link in db.query(InvestigationSourceEvent).filter_by(investigation_id=inv.id).all():
        event = db.query(SourceEvent).filter_by(id=link.source_event_id).first()
        if event:
            event.state = "reviewed" if state == "reviewed" else "suppressed"
            event.reviewed_at = inv.reviewed_at
    db.commit()
    return {"id": inv.id, "review_state": inv.review_state, "reviewed_at": inv.reviewed_at.isoformat()}


@router.post("/investigations/{investigation_id}/publish-knowledge", dependencies=[Depends(require_admin)])
def publish_knowledge(investigation_id: int, body: dict, db: Session = Depends(get_db)):
    from engine.functional_alignment import publish_reviewed_knowledge
    try:
        entry = publish_reviewed_knowledge(db, investigation_id, body.get("reviewed_by", "admin"))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return {"id": entry.id, "signature": entry.signature, "version": entry.version, "active": entry.active}


@router.get("/knowledge", dependencies=[Depends(require_admin_read)])
def knowledge(active: Optional[bool] = True, db: Session = Depends(get_db)):
    from db.models import KnowledgeEntry
    query = db.query(KnowledgeEntry)
    if active is not None:
        query = query.filter(KnowledgeEntry.active == active)
    fields = ("id", "signature", "version", "active", "root_cause", "remediation", "metadata_json",
              "provenance", "confidence", "investigation_id", "reviewed_by", "reviewed_at", "retired_at",
              "acceptance_count", "rejection_count")
    return {"items": [_row(item, fields) for item in query.order_by(KnowledgeEntry.reviewed_at.desc()).all()]}


@router.get("/trends", dependencies=[Depends(require_admin_read)])
def trends(status: Optional[str] = "open", db: Session = Depends(get_db)):
    from db.models import TrendSignal
    query = db.query(TrendSignal)
    if status:
        query = query.filter(TrendSignal.status == status)
    fields = ("id", "signal_key", "signal_type", "catalog_item", "failure_class", "current_rate",
              "baseline_rate", "failure_count", "evidence", "status", "detected_at", "resolved_at")
    return {"items": [_row(item, fields) for item in query.order_by(TrendSignal.detected_at.desc()).all()]}


@router.get("/gates", dependencies=[Depends(require_admin_read)])
def gates():
    from engine.functional_alignment import gate_enabled
    names = ("source_ingestion", "diagnosis_claims", "slack_delivery", "jira_drafting",
             "jira_execution", "knowledge_retrieval", "trend_detection")
    return {"gates": {name: gate_enabled(name) for name in names}}


@router.post("/gates/{gate}/receipt", dependencies=[Depends(require_admin)])
def record_gate_receipt(gate: str, body: dict, db: Session = Depends(get_db)):
    """Persist stage-gate evidence; configuration promotion remains deployment-controlled."""
    from db.models import Receipt
    required = ("rubric_score", "critical_passed", "severity_one_open", "duplicate_count", "rollback_verified")
    missing = [key for key in required if key not in body]
    if missing:
        raise HTTPException(422, f"Missing receipt fields: {', '.join(missing)}")
    eligible = (
        float(body["rubric_score"]) >= 90
        and bool(body["critical_passed"])
        and int(body["severity_one_open"]) == 0
        and int(body["duplicate_count"]) == 0
        and bool(body["rollback_verified"])
    )
    receipt = Receipt(receipt_type="functional_alignment_gate", phase=gate,
                      data={**body, "promotion_eligible": eligible}, passed=eligible,
                      generated_at=datetime.now(timezone.utc))
    db.add(receipt); db.commit(); db.refresh(receipt)
    return {"id": receipt.id, "gate": gate, "promotion_eligible": eligible}


@router.get("/gates/receipts", dependencies=[Depends(require_admin_read)])
def gate_receipts(db: Session = Depends(get_db)):
    from db.models import Receipt
    rows = db.query(Receipt).filter_by(receipt_type="functional_alignment_gate").order_by(Receipt.id.desc()).all()
    return {"items": [{"id": row.id, "gate": row.phase, "passed": row.passed,
                       "data": row.data, "generated_at": row.generated_at.isoformat()} for row in rows]}
