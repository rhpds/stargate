"""Durable functional pipeline for external failures, diagnoses, delivery, and trends."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import (
    EvaluationRecord, ExternalTicket, InvestigationRecord, InvestigationSourceEvent,
    KnowledgeEntry, NotificationDelivery, PendingAction, SourceEvent, TrendSignal,
)

MAX_RAW_BYTES = 64 * 1024
SECRET_KEY = re.compile(r"(?i)(password|passwd|token|secret|api[_-]?key|authorization|credential|private[_-]?key)")
SECRET_TEXT = re.compile(r"(?i)(bearer\s+)[a-z0-9._~+\-/=]+|((?:token|password|secret|api[_-]?key)\s*[:=]\s*)\S+")


def gate_enabled(name: str, default: bool = False) -> bool:
    value = os.environ.get(f"STARGATE_GATE_{name.upper()}")
    return default if value is None else value.lower() in ("1", "true", "yes", "on")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sanitize_evidence(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if SECRET_KEY.search(str(k)) else sanitize_evidence(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_evidence(v) for v in value]
    if isinstance(value, str):
        return SECRET_TEXT.sub(lambda m: (m.group(1) or m.group(2) or "") + "[REDACTED]", value)
    return value


def bounded_evidence(value: Dict) -> Dict:
    clean = sanitize_evidence(value)
    raw = json.dumps(clean, sort_keys=True, default=str).encode()
    if len(raw) <= MAX_RAW_BYTES:
        return clean
    return {"truncated": True, "preview": raw[:MAX_RAW_BYTES].decode("utf-8", "ignore")}


def evidence_hash(value: Dict) -> str:
    clean = bounded_evidence(value)
    return hashlib.sha256(json.dumps(clean, sort_keys=True, default=str).encode()).hexdigest()


def _parse_time(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def ingest_aap_failures(db: Session, failures: Iterable[Dict]) -> Dict:
    """Idempotently persist normalized AAP failures and one evaluation each."""
    created = updated = evaluations = 0
    for raw in failures:
        clean = bounded_evidence(raw)
        digest = evidence_hash(clean)
        outcome = raw.get("outcome") or raw.get("status") or "fail"
        failure_class = raw.get("failure_class")
        if outcome == "fail" and (not failure_class or failure_class == "unclassified"):
            try:
                from engine.failure_class_loader import classify_by_pattern
                failure_class, _ = classify_by_pattern(
                    f"{raw.get('error', '')} {raw.get('failing_task', '')} {raw.get('role', '')}",
                    source="aap2_grafana",
                )
            except Exception:
                failure_class = "unclassified"
        instance = str(raw.get("controller") or "unknown")
        event_id = str(raw.get("event_id") or raw.get("job_event_id") or "")
        if not event_id:
            event_id = f"job-{raw.get('job_id', 'unknown')}-{digest[:16]}"
        now = _utcnow()
        record = db.query(SourceEvent).filter_by(
            source_system="aap", source_instance=instance, source_event_id=event_id,
        ).first()
        if record:
            record.last_seen_at = now
            if record.evidence_hash != digest:
                record.evidence_hash = digest
                record.raw_evidence = clean
                record.normalized_error = str(raw.get("error") or raw.get("error_msg") or "Unknown error")
                if record.state in ("diagnosed", "reviewed", "suppressed"):
                    record.state = "reopened"
            updated += 1
        else:
            record = SourceEvent(
                source_system="aap", source_instance=instance, source_event_id=event_id,
                evidence_hash=digest, outcome=outcome,
                state="new" if outcome == "fail" else "suppressed",
                job_id=str(raw.get("job_id") or ""),
                controller_url=raw.get("controller_url"), job_url=raw.get("job_url"),
                task=raw.get("failing_task") or raw.get("task"), play=raw.get("play"), role=raw.get("role"),
                guid=raw.get("guid") or raw.get("lab_code"), catalog_item=raw.get("catalog_item"),
                stage=raw.get("stage") or "aap-provisioning", action=raw.get("type"),
                provider=raw.get("provider"), cluster=raw.get("cluster"),
                failure_class=failure_class,
                normalized_error=str(raw.get("error") or raw.get("error_msg") or "Unknown error"),
                raw_evidence=clean, occurred_at=_parse_time(raw.get("finished") or raw.get("occurred_at")),
                first_seen_at=now, last_seen_at=now,
            )
            db.add(record)
            try:
                db.flush()
                created += 1
            except IntegrityError:
                db.rollback()
                record = db.query(SourceEvent).filter_by(
                    source_system="aap", source_instance=instance, source_event_id=event_id,
                ).one()
                record.last_seen_at = now
                updated += 1

        existing_eval = db.query(EvaluationRecord.id).filter(EvaluationRecord.source_event_id == record.id).first()
        if record.outcome == "fail" and not existing_eval:
            db.add(EvaluationRecord(
                run_id=f"source-aap-{record.id}", stage_id="aap-provisioning", outcome="fail",
                failure_class=record.failure_class, message=record.normalized_error[:2000],
                criteria_results={"source_event_id": record.id}, evaluated_at=now,
                lab_code=record.guid or record.catalog_item, cluster_name=record.cluster,
                source_event_id=record.id,
            ))
            evaluations += 1
        db.commit()
    return {"created": created, "updated": updated, "evaluations_created": evaluations}


def ingest_aap_collection_status(db: Session, statuses: Iterable[Dict]) -> int:
    """Persist one non-actionable evaluation for each unavailable controller/day."""
    created = 0
    now = _utcnow()
    for status in statuses:
        if status.get("status") != "collection-unavailable":
            continue
        controller = str(status.get("controller") or "unknown")
        event_id = f"collection-{now.date().isoformat()}"
        record = db.query(SourceEvent).filter_by(
            source_system="aap", source_instance=controller, source_event_id=event_id,
        ).first()
        if record:
            record.last_seen_at = now
            db.commit()
            continue
        evidence = bounded_evidence(status)
        record = SourceEvent(
            source_system="aap", source_instance=controller, source_event_id=event_id,
            evidence_hash=evidence_hash(evidence), outcome="collection-unavailable", state="suppressed",
            stage="aap-collection", failure_class="collection_unavailable",
            normalized_error=f"AAP collection unavailable: {status.get('error_type') or 'api'}",
            raw_evidence=evidence, first_seen_at=now, last_seen_at=now, occurred_at=now,
        )
        db.add(record)
        db.flush()
        db.add(EvaluationRecord(
            run_id=f"source-aap-collection-{record.id}", stage_id="aap-collection", outcome="fail",
            failure_class="collection_unavailable", message=record.normalized_error,
            criteria_results={"source_event_id": record.id, "actionable": False},
            evaluated_at=now, source_event_id=record.id,
        ))
        db.commit()
        created += 1
    return created


def claim_source_events(db: Session, investigation: InvestigationRecord, limit: int = 50, ttl_minutes: int = 30) -> List[int]:
    now = _utcnow()
    query = db.query(SourceEvent).filter(
        SourceEvent.state.in_(("new", "reopened")),
        (SourceEvent.claim_expires_at.is_(None)) | (SourceEvent.claim_expires_at < now),
    )
    if investigation.triggering_eval_id:
        source_id = db.query(EvaluationRecord.source_event_id).filter(EvaluationRecord.id == investigation.triggering_eval_id).scalar()
        if source_id:
            query = query.filter(SourceEvent.id == source_id)
    else:
        query = query.filter(
            SourceEvent.failure_class == investigation.failure_class,
            (SourceEvent.guid == investigation.lab_code) | (SourceEvent.catalog_item == investigation.lab_code),
        )
    events = query.order_by(SourceEvent.occurred_at.asc(), SourceEvent.id.asc()).with_for_update(skip_locked=True).limit(limit).all()
    claimed = []
    for event in events:
        event.state = "claimed"
        event.claimed_at = now
        event.claim_expires_at = now + timedelta(minutes=ttl_minutes)
        db.add(InvestigationSourceEvent(
            investigation_id=investigation.id, source_event_id=event.id, evidence_hash=event.evidence_hash,
            diagnosis_version=investigation.diagnosis_version or 1, claimed_at=now,
        ))
        claimed.append(event.id)
    if claimed:
        investigation.evidence_hash = hashlib.sha256("".join(sorted(e.evidence_hash for e in events)).encode()).hexdigest()
    db.commit()
    return claimed


def finish_source_event_claims(db: Session, investigation: InvestigationRecord, success: bool, reason: str = "") -> None:
    now = _utcnow()
    links = db.query(InvestigationSourceEvent).filter_by(investigation_id=investigation.id).all()
    for link in links:
        event = db.query(SourceEvent).filter_by(id=link.source_event_id).first()
        if not event:
            continue
        event.claim_expires_at = None
        if success:
            event.state, event.diagnosed_at, link.diagnosed_at = "diagnosed", now, now
        else:
            event.state, link.released_at, link.release_reason = "reopened", now, reason[:255]
    db.commit()


def find_knowledge(db: Session, catalog_item: str, failure_class: str, limit: int = 3) -> List[Dict]:
    signature = f"{catalog_item}:{failure_class}".lower()
    rows = db.query(KnowledgeEntry).filter(KnowledgeEntry.active.is_(True)).order_by(KnowledgeEntry.reviewed_at.desc()).all()
    matches = []
    for row in rows:
        score = 1.0 if row.signature == signature else 0.7 if failure_class.lower() in row.signature else 0.0
        if score:
            matches.append({"id": row.id, "signature": row.signature, "version": row.version, "score": score,
                            "root_cause": row.root_cause, "remediation": row.remediation,
                            "provenance": row.provenance})
    return matches[:limit]


def publish_reviewed_knowledge(db: Session, investigation_id: int, reviewer: str) -> KnowledgeEntry:
    inv = db.query(InvestigationRecord).filter_by(id=investigation_id).one()
    if inv.review_state != "reviewed" or not inv.root_cause or not inv.remediation_suggestion:
        raise ValueError("Only reviewed diagnoses with root cause and remediation may be published")
    signature = f"{inv.lab_code}:{inv.failure_class}".lower()
    prior = db.query(KnowledgeEntry).filter_by(signature=signature, active=True).order_by(KnowledgeEntry.version.desc()).first()
    version = (prior.version + 1) if prior else 1
    now = _utcnow()
    if prior:
        prior.active, prior.retired_at = False, now
    entry = KnowledgeEntry(
        signature=signature, version=version, active=True, root_cause=inv.root_cause,
        remediation=inv.remediation_suggestion, metadata_json={"lab_code": inv.lab_code, "failure_class": inv.failure_class},
        provenance={"investigation_id": inv.id, "job_id": inv.job_id, "evidence_hash": inv.evidence_hash},
        confidence=(inv.trust_dimensions or {}).get("confidence"), investigation_id=inv.id,
        reviewed_by=reviewer, reviewed_at=now,
    )
    db.add(entry); db.commit(); db.refresh(entry)
    return entry


def queue_slack_delivery(db: Session, investigation: InvestigationRecord) -> Optional[NotificationDelivery]:
    if investigation.review_state == "suppressed" or not investigation.analysis:
        return None
    verdict = ((investigation.trust_dimensions or {}).get("verdict") or "").upper()
    if verdict in ("TRANSIENT", "UNKNOWN"):
        return None
    dedup_key = f"investigation:{investigation.id}:v{investigation.diagnosis_version}"
    payload_hash = hashlib.sha256((investigation.analysis or "").encode()).hexdigest()
    existing = db.query(NotificationDelivery).filter_by(channel="slack", dedup_key=dedup_key).first()
    if existing:
        return existing
    row = NotificationDelivery(channel="slack", dedup_key=dedup_key, payload_hash=payload_hash,
        investigation_id=investigation.id, diagnosis_version=investigation.diagnosis_version,
        status="pending", attempt_count=0, created_at=_utcnow())
    db.add(row); db.commit(); db.refresh(row)
    return row


def deliver_slack(db: Session, delivery_id: int) -> Dict:
    row = db.query(NotificationDelivery).filter_by(id=delivery_id).with_for_update().first()
    if not row or row.status == "sent":
        return {"sent": bool(row and row.status == "sent"), "deduplicated": True}
    inv = db.query(InvestigationRecord).filter_by(id=row.investigation_id).one()
    webhook = os.environ.get("STARGATE_SLACK_WEBHOOK_URL", "")
    if not webhook:
        row.status, row.last_error = "failed_permanent", "Slack webhook not configured"; db.commit()
        return {"sent": False, "permanent": True}
    links = db.query(InvestigationSourceEvent).filter_by(investigation_id=inv.id).all()
    source = db.query(SourceEvent).filter_by(id=links[0].source_event_id).first() if links else None
    payload = {"text": f"StarGate actionable finding: {inv.failure_class}", "blocks": [
        {"type": "section", "text": {"type": "mrkdwn", "text":
            f"*{inv.failure_class}* — `{inv.lab_code}`\n*Task:* {(source.task if source else '?')}\n"
            f"*Job:* <{(source.job_url if source else '')}|Open controller job>\n*Root cause:* {inv.root_cause or 'See diagnosis'}\n"
            f"*Remediation:* {inv.remediation_suggestion or 'See finding'}"}},
    ]}
    row.status, row.attempt_count = "sending", row.attempt_count + 1; db.commit()
    try:
        req = urllib.request.Request(webhook, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        response = urllib.request.urlopen(req, timeout=10)
        row.status, row.sent_at = "sent", _utcnow()
        row.external_message_id = response.headers.get("x-slack-req-id")
        row.last_error = None; db.commit()
        return {"sent": True}
    except urllib.error.HTTPError as exc:
        row.last_error = str(exc)[:1000]
        row.status = "failed_permanent" if exc.code in (400, 401, 403, 404) else "retry"
    except Exception as exc:
        row.last_error, row.status = str(exc)[:1000], "retry"
    row.next_attempt_at = _utcnow() + timedelta(seconds=min(3600, 2 ** min(row.attempt_count, 10)))
    db.commit(); return {"sent": False, "status": row.status}


def create_jira_draft(db: Session, investigation: InvestigationRecord) -> Tuple[ExternalTicket, PendingAction]:
    signature = f"{investigation.lab_code}:{investigation.failure_class}".lower()
    ticket = db.query(ExternalTicket).filter_by(system="jira", dedup_signature=signature, active=True).first()
    links = db.query(InvestigationSourceEvent).filter_by(investigation_id=investigation.id).all()
    payload = {"summary": f"[{investigation.failure_class}] {investigation.lab_code}",
               "description": investigation.analysis, "root_cause": investigation.root_cause,
               "remediation": investigation.remediation_suggestion,
               "source_event_ids": [link.source_event_id for link in links]}
    now = _utcnow()
    if not ticket:
        ticket = ExternalTicket(system="jira", dedup_signature=signature, active=True, status="draft",
            investigation_id=investigation.id, diagnosis_version=investigation.diagnosis_version,
            source_event_ids=payload["source_event_ids"], draft_payload=payload, created_at=now, updated_at=now)
        db.add(ticket); db.flush()
    else:
        ticket.investigation_id = investigation.id
        ticket.diagnosis_version = investigation.diagnosis_version
        ticket.source_event_ids = sorted(set((ticket.source_event_ids or []) + payload["source_event_ids"]))
        ticket.draft_payload = payload
        ticket.updated_at = now
    action_type = "update_jira_ticket" if ticket.ticket_key else "create_jira_ticket"
    source_key = f"investigation:{investigation.id}:v{investigation.diagnosis_version}"
    existing_pending = db.query(PendingAction).filter_by(
        action_type=action_type, source_event_id=source_key, status="pending",
    ).first()
    if existing_pending:
        db.commit()
        return ticket, existing_pending
    pending = PendingAction(action_type=action_type, target=signature,
        parameters={"external_ticket_id": ticket.id}, confidence=1.0, proposed_by="stargate",
        source_event_id=source_key, status="pending", proposed_at=now)
    db.add(pending); db.commit(); db.refresh(ticket); db.refresh(pending)
    return ticket, pending


def execute_jira_ticket(db: Session, external_ticket_id: int) -> Dict:
    ticket = db.query(ExternalTicket).filter_by(id=external_ticket_id).one()
    base, token, project = (os.environ.get(k, "") for k in ("STARGATE_JIRA_URL", "STARGATE_JIRA_TOKEN", "STARGATE_JIRA_PROJECT"))
    if not base or not token or not project or not gate_enabled("jira_execution"):
        return {"created": False, "reason": "jira execution disabled or unconfigured"}
    issue_type = os.environ.get("STARGATE_JIRA_ISSUE_TYPE", "Task")
    body = {"fields": {"project": {"key": project}, "issuetype": {"name": issue_type},
                       "summary": ticket.draft_payload["summary"], "description": ticket.draft_payload.get("description") or ""}}
    endpoint = f"{base.rstrip('/')}/rest/api/2/issue"
    method = "POST"
    if ticket.ticket_key:
        endpoint = f"{endpoint}/{ticket.ticket_key}"
        method = "PUT"
    req = urllib.request.Request(endpoint, data=json.dumps(body).encode(), method=method,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        response = urllib.request.urlopen(req, timeout=15)
        result = json.loads(response.read() or b"{}")
        ticket.ticket_key = result.get("key") or ticket.ticket_key
        ticket.ticket_url = f"{base.rstrip('/')}/browse/{ticket.ticket_key}"
        ticket.status, ticket.updated_at, ticket.last_error = "created" if method == "POST" else "updated", _utcnow(), None
        db.commit(); return {"created": method == "POST", "updated": method == "PUT", "key": ticket.ticket_key, "url": ticket.ticket_url}
    except Exception as exc:
        ticket.status, ticket.last_error, ticket.updated_at = "error", str(exc)[:1000], _utcnow(); db.commit()
        return {"created": False, "error": ticket.last_error}


def _recent_agnosticv_change(catalog_item: str, since: datetime) -> Optional[Dict]:
    repo = os.environ.get("STARGATE_AGNOSTICV_DIR", "")
    if not repo or not os.path.isdir(os.path.join(repo, ".git")):
        return None
    try:
        result = subprocess.run(
            ["git", "-C", repo, "log", f"--since={since.isoformat()}", "--format=%H%x09%cI%x09%s", "--all", "--", f"*{catalog_item}*"],
            capture_output=True, text=True, timeout=10,
        )
        line = next((line for line in result.stdout.splitlines() if line), "")
        if not line:
            return None
        sha, committed_at, subject = (line.split("\t", 2) + ["", ""])[:3]
        return {"commit": sha, "committed_at": committed_at, "subject": subject,
                "interpretation": "temporal correlation only; not proven causality"}
    except Exception:
        return None


def _route_trend(db: Session, signal: TrendSignal, now: datetime) -> None:
    evaluation = db.query(EvaluationRecord).filter_by(run_id=f"trend-{signal.signal_key}").first()
    if evaluation:
        return
    evaluation = EvaluationRecord(run_id=f"trend-{signal.signal_key}", stage_id="trend-detection", outcome="fail",
        failure_class=signal.signal_type, message=json.dumps(signal.evidence, default=str)[:2000],
        criteria_results={"trend_signal_id": signal.id}, evaluated_at=now,
        lab_code=signal.catalog_item, cluster_name="babylon")
    db.add(evaluation); db.flush()
    if gate_enabled("diagnosis_claims"):
        db.add(InvestigationRecord(job_id=f"trend-{hashlib.sha256(signal.signal_key.encode()).hexdigest()[:12]}",
            lab_code=signal.catalog_item or "platform", cluster="babylon", namespace=signal.catalog_item,
            failure_class=signal.signal_type, trigger_type="auto_trend", status="queued",
            triggering_eval_id=evaluation.id, created_at=now))


def detect_trends(db: Session, now: Optional[datetime] = None) -> List[TrendSignal]:
    now = now or _utcnow(); current_start = now - timedelta(hours=24); baseline_start = now - timedelta(days=8)
    rows = db.query(SourceEvent.catalog_item, SourceEvent.failure_class,
        func.count(SourceEvent.id), func.min(SourceEvent.occurred_at), func.max(SourceEvent.occurred_at)).filter(
        SourceEvent.occurred_at >= baseline_start, SourceEvent.catalog_item.isnot(None),
        SourceEvent.outcome == "fail").group_by(
        SourceEvent.catalog_item, SourceEvent.failure_class).all()
    signals = []
    for catalog, failure_class, _, _, _ in rows:
        current_total = db.query(SourceEvent).filter(SourceEvent.catalog_item == catalog,
            SourceEvent.occurred_at >= current_start).count()
        current = db.query(SourceEvent).filter(SourceEvent.catalog_item == catalog, SourceEvent.failure_class == failure_class,
            SourceEvent.outcome == "fail", SourceEvent.occurred_at >= current_start).count()
        baseline_total = db.query(SourceEvent).filter(SourceEvent.catalog_item == catalog,
            SourceEvent.occurred_at >= baseline_start, SourceEvent.occurred_at < current_start).count()
        baseline = db.query(SourceEvent).filter(SourceEvent.catalog_item == catalog, SourceEvent.failure_class == failure_class,
            SourceEvent.outcome == "fail", SourceEvent.occurred_at >= baseline_start, SourceEvent.occurred_at < current_start).count()
        current_rate = current / max(current_total, 1) * 100
        baseline_rate = baseline / max(baseline_total, 1) * 100
        if current >= 5 and current_rate >= baseline_rate * 2 and current_rate - baseline_rate >= 5:
            key = f"rate:{catalog}:{failure_class}:{current_start.date()}"
            signal = db.query(TrendSignal).filter_by(signal_key=key).first()
            if not signal:
                signal = TrendSignal(signal_key=key, signal_type="failure_rate_increase", catalog_item=catalog,
                    failure_class=failure_class, current_rate=current_rate, baseline_rate=baseline_rate,
                    failure_count=current, evidence={"window_hours": 24, "baseline_days": 7}, detected_at=now)
                db.add(signal); db.flush(); _route_trend(db, signal, now); signals.append(signal)
        baseline_success = (baseline_total - baseline) / max(baseline_total, 1) * 100
        recent_outcomes = db.query(SourceEvent.outcome).filter(
            SourceEvent.catalog_item == catalog, SourceEvent.occurred_at >= current_start,
        ).order_by(SourceEvent.occurred_at.desc()).limit(3).all()
        if baseline_total >= 10 and baseline_success >= 90 and len(recent_outcomes) == 3 and all(row[0] == "fail" for row in recent_outcomes):
            key = f"regression:{catalog}:{failure_class}:{current_start.date()}"
            if not db.query(TrendSignal).filter_by(signal_key=key).first():
                change = _recent_agnosticv_change(catalog, now - timedelta(hours=2))
                signal = TrendSignal(signal_key=key, signal_type="catalog_regression", catalog_item=catalog,
                    failure_class=failure_class, current_rate=current_rate, baseline_rate=100 - baseline_success,
                    failure_count=current, evidence={"consecutive_failures": 3, "prior_success_rate": baseline_success,
                    "change_correlation": change or "no matching commit found within two-hour window"}, detected_at=now)
                db.add(signal); db.flush(); _route_trend(db, signal, now); signals.append(signal)
    db.commit()
    return signals
