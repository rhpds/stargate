"""Admin LLM sub-router — metrics, timeline, recent calls, evaluation,
feedback, drift, auto-investigate, investigations, synthetic integration,
approval queue, audit, validation, phase-D/chaos testing, receipts."""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from db.database import get_db
from db import repository
from api.routers._shared import (
    limiter,
    require_admin,
    require_admin_read,
)

router = APIRouter()
logger = logging.getLogger("stargate.admin.llm")


# ---------------------------------------------------------------------------
# LLM Admin — metrics, timeline, recent calls, evaluation, feedback, drift
# ---------------------------------------------------------------------------

@router.get("/admin/llm/metrics", dependencies=[Depends(require_admin_read)])
def admin_llm_metrics(db: Session = Depends(get_db), cluster: str = None):
    """Aggregated LLM usage metrics. Optionally filtered by cluster."""
    from db.models import LLMMetric
    from sqlalchemy import func

    query = db.query(LLMMetric)
    if cluster:
        query = query.filter(LLMMetric.cluster_name == cluster)

    total = query.count()
    if total == 0:
        return {
            "total_calls": 0, "total_tokens": 0, "total_cost_estimate": 0,
            "calls_by_endpoint": {}, "avg_latency_ms": {}, "p95_latency_ms": {},
            "error_rate": 0, "errors_by_type": {}, "tokens_by_endpoint": {},
            "calls_last_hour": 0, "calls_last_24h": 0, "avg_confidence": None,
            "period": cluster or "all time",
        }

    all_metrics = query.order_by(LLMMetric.called_at.desc()).all()
    now = datetime.now(timezone.utc)
    one_hour = now - timedelta(hours=1)
    one_day = now - timedelta(days=1)

    calls_by_ep: Dict[str, int] = {}
    latencies_by_ep: Dict[str, List] = {}
    tokens_by_ep: Dict[str, int] = {}
    errors_by_type: Dict[str, int] = {}
    total_tokens = 0
    total_cost = 0.0
    errors = 0
    confidences = []

    for m in all_metrics:
        calls_by_ep[m.endpoint] = calls_by_ep.get(m.endpoint, 0) + 1
        if m.endpoint not in latencies_by_ep:
            latencies_by_ep[m.endpoint] = []
        latencies_by_ep[m.endpoint].append(m.latency_ms)
        if m.total_tokens:
            tokens_by_ep[m.endpoint] = tokens_by_ep.get(m.endpoint, 0) + m.total_tokens
            total_tokens += m.total_tokens
        if m.cost_estimate:
            total_cost += m.cost_estimate
        if not m.success:
            errors += 1
            et = m.error_type or "unknown"
            errors_by_type[et] = errors_by_type.get(et, 0) + 1
        if m.confidence is not None:
            confidences.append(m.confidence)

    avg_latency = {ep: int(sum(lats) / len(lats)) for ep, lats in latencies_by_ep.items()}
    p95_latency = {ep: int(sorted(lats)[int(len(lats) * 0.95)]) if lats else 0 for ep, lats in latencies_by_ep.items()}

    calls_1h = sum(1 for m in all_metrics if m.called_at and m.called_at.replace(tzinfo=timezone.utc) > one_hour)
    calls_24h = sum(1 for m in all_metrics if m.called_at and m.called_at.replace(tzinfo=timezone.utc) > one_day)

    return {
        "total_calls": total,
        "total_tokens": total_tokens,
        "total_cost_estimate": round(total_cost, 4),
        "calls_by_endpoint": calls_by_ep,
        "avg_latency_ms": avg_latency,
        "p95_latency_ms": p95_latency,
        "error_rate": round(errors / max(total, 1), 3),
        "errors_by_type": errors_by_type,
        "tokens_by_endpoint": tokens_by_ep,
        "calls_last_hour": calls_1h,
        "calls_last_24h": calls_24h,
        "avg_confidence": round(sum(confidences) / len(confidences), 3) if confidences else None,
        "period": "all time",
    }


@router.get("/admin/llm/metrics/timeline", dependencies=[Depends(require_admin_read)])
def admin_llm_timeline(hours: int = 24, db: Session = Depends(get_db)):
    """Hourly breakdown of LLM metrics for charts."""
    from db.models import LLMMetric

    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)
    metrics = db.query(LLMMetric).filter(LLMMetric.called_at >= start).order_by(LLMMetric.called_at).all()

    buckets: Dict[str, Dict] = {}
    for h in range(hours):
        hour_key = (start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:00")
        buckets[hour_key] = {"calls": 0, "latency_sum": 0, "tokens": 0, "errors": 0}

    for m in metrics:
        hour_key = m.called_at.strftime("%Y-%m-%dT%H:00") if m.called_at else None
        if hour_key and hour_key in buckets:
            b = buckets[hour_key]
            b["calls"] += 1
            b["latency_sum"] += m.latency_ms
            b["tokens"] += m.total_tokens or 0
            if not m.success:
                b["errors"] += 1

    hour_keys = sorted(buckets.keys())
    return {
        "hours": hour_keys,
        "calls": [buckets[h]["calls"] for h in hour_keys],
        "latency_avg": [int(buckets[h]["latency_sum"] / max(buckets[h]["calls"], 1)) for h in hour_keys],
        "tokens": [buckets[h]["tokens"] for h in hour_keys],
        "errors": [buckets[h]["errors"] for h in hour_keys],
    }


@router.get("/admin/llm/recent", dependencies=[Depends(require_admin_read)])
def admin_llm_recent(limit: int = 50, endpoint: str = None, cluster: str = None, db: Session = Depends(get_db)):
    """Recent LLM calls with details. Filter by endpoint and/or cluster."""
    from db.models import LLMMetric
    query = db.query(LLMMetric)
    if endpoint:
        query = query.filter(LLMMetric.endpoint == endpoint)
    if cluster:
        query = query.filter(LLMMetric.cluster_name == cluster)
    metrics = query.order_by(LLMMetric.called_at.desc()).limit(limit).all()
    return [
        {
            "id": m.id,
            "endpoint": m.endpoint,
            "model": m.model,
            "prompt_tokens": m.prompt_tokens,
            "completion_tokens": m.completion_tokens,
            "total_tokens": m.total_tokens,
            "cost_estimate": m.cost_estimate,
            "latency_ms": m.latency_ms,
            "success": m.success,
            "finish_reason": m.finish_reason,
            "error_type": m.error_type,
            "confidence": m.confidence,
            "lab_code": m.lab_code,
            "cluster_name": m.cluster_name,
            "failure_class": m.failure_class,
            "response_preview": m.response_preview,
            "called_at": m.called_at.isoformat() if m.called_at else None,
        }
        for m in metrics
    ]


@router.get("/admin/llm/evaluation", dependencies=[Depends(require_admin_read)])
def admin_llm_evaluation(db: Session = Depends(get_db)):
    """Feedback loop metrics — approval rates, confidence calibration."""
    from db.models import ProposedClassification

    proposals = db.query(ProposedClassification).all()
    total = len(proposals)
    reviewed = [p for p in proposals if p.reviewed]
    approved = [p for p in reviewed if p.approved]
    rejected = [p for p in reviewed if p.approved is False]

    conf_buckets: Dict[str, Dict] = {}
    for bucket_start in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
        bucket_end = bucket_start + 0.1
        label = f"{bucket_start:.1f}-{bucket_end:.1f}"
        in_bucket = [p for p in reviewed if p.confidence is not None and bucket_start <= p.confidence < bucket_end]
        bucket_approved = sum(1 for p in in_bucket if p.approved)
        conf_buckets[label] = {
            "total": len(in_bucket),
            "approved": bucket_approved,
            "rate": round(bucket_approved / max(len(in_bucket), 1) * 100, 1),
        }

    corrections: Dict[str, int] = {}
    for p in rejected:
        key = f"{p.proposed_class} → corrected"
        corrections[key] = corrections.get(key, 0) + 1

    return {
        "total_proposals": total,
        "reviewed": len(reviewed),
        "approved": len(approved),
        "rejected": len(rejected),
        "pending_review": total - len(reviewed),
        "approval_rate": round(len(approved) / max(len(reviewed), 1) * 100, 1),
        "avg_confidence_approved": round(sum(p.confidence or 0 for p in approved) / max(len(approved), 1), 3),
        "avg_confidence_rejected": round(sum(p.confidence or 0 for p in rejected) / max(len(rejected), 1), 3),
        "confidence_calibration": [
            {"bucket": k, **v} for k, v in conf_buckets.items() if v["total"] > 0
        ],
        "top_corrections": [{"class": k, "count": v} for k, v in sorted(corrections.items(), key=lambda x: -x[1])[:10]],
    }


@router.post("/admin/llm/feedback", dependencies=[Depends(require_admin)])
def admin_llm_feedback(req: dict, db: Session = Depends(get_db)):
    """Submit feedback on an LLM response."""
    from db.models import LLMFeedback
    fb = LLMFeedback(
        llm_metric_id=req.get("llm_metric_id"),
        endpoint=req.get("endpoint", "unknown"),
        helpful=req.get("helpful", False),
        notes=req.get("notes"),
        submitted_by=req.get("submitted_by", "ops-user"),
        submitted_at=datetime.now(timezone.utc),
    )
    db.add(fb)
    db.commit()
    return {"id": fb.id, "status": "submitted"}


@router.get("/admin/llm/drift", dependencies=[Depends(require_admin_read)])
def admin_llm_drift(db: Session = Depends(get_db)):
    """Drift detection — compare recent 7 days vs prior 7 days."""
    from db.models import LLMMetric, ProposedClassification

    now = datetime.now(timezone.utc)
    recent_start = now - timedelta(days=7)
    prior_start = now - timedelta(days=14)

    recent = db.query(LLMMetric).filter(LLMMetric.called_at >= recent_start).all()
    prior = db.query(LLMMetric).filter(LLMMetric.called_at >= prior_start, LLMMetric.called_at < recent_start).all()

    def _stats(metrics):
        if not metrics:
            return {"calls": 0, "avg_latency": 0, "error_rate": 0, "avg_tokens": 0, "total_cost": 0}
        errors = sum(1 for m in metrics if not m.success)
        latencies = [m.latency_ms for m in metrics]
        tokens = [m.total_tokens or 0 for m in metrics]
        cost = sum(m.cost_estimate or 0 for m in metrics)
        return {
            "calls": len(metrics),
            "avg_latency": int(sum(latencies) / len(latencies)),
            "p95_latency": int(sorted(latencies)[int(len(latencies) * 0.95)]) if latencies else 0,
            "error_rate": round(errors / len(metrics), 3),
            "avg_tokens": int(sum(tokens) / len(tokens)),
            "total_cost": round(cost, 4),
        }

    recent_stats = _stats(recent)
    prior_stats = _stats(prior)

    recent_proposals = db.query(ProposedClassification).filter(
        ProposedClassification.proposed_at >= recent_start
    ).all()
    prior_proposals = db.query(ProposedClassification).filter(
        ProposedClassification.proposed_at >= prior_start,
        ProposedClassification.proposed_at < recent_start,
    ).all()

    def _approval_rate(proposals):
        reviewed = [p for p in proposals if p.reviewed]
        if not reviewed:
            return None
        return round(sum(1 for p in reviewed if p.approved) / len(reviewed) * 100, 1)

    recent_approval = _approval_rate(recent_proposals)
    prior_approval = _approval_rate(prior_proposals)

    alerts = []
    if prior_stats["calls"] > 0 and recent_stats["calls"] > 0:
        latency_change = (recent_stats["avg_latency"] - prior_stats["avg_latency"]) / max(prior_stats["avg_latency"], 1)
        if latency_change > 0.5:
            alerts.append({"type": "latency", "severity": "warning", "message": f"Avg latency increased {latency_change*100:.0f}% vs prior week"})
        if recent_stats["error_rate"] > 0.05:
            alerts.append({"type": "error_rate", "severity": "critical", "message": f"Error rate is {recent_stats['error_rate']*100:.1f}% (threshold: 5%)"})
        if recent_stats["error_rate"] > prior_stats["error_rate"] * 2 and prior_stats["error_rate"] > 0:
            alerts.append({"type": "error_spike", "severity": "warning", "message": "Error rate doubled vs prior week"})

    if recent_approval is not None and prior_approval is not None:
        if prior_approval - recent_approval > 10:
            alerts.append({"type": "approval_drop", "severity": "warning", "message": f"Approval rate dropped from {prior_approval}% to {recent_approval}%"})

    status = "stable"
    if any(a["severity"] == "critical" for a in alerts):
        status = "degraded"
    elif alerts:
        status = "drifting"

    return {
        "status": status,
        "alerts": alerts,
        "recent": {**recent_stats, "period": "last 7 days", "approval_rate": recent_approval},
        "prior": {**prior_stats, "period": "prior 7 days", "approval_rate": prior_approval},
    }


@router.get("/admin/llm/ab-test", dependencies=[Depends(require_admin_read)])
def admin_llm_ab_test(db: Session = Depends(get_db)):
    """Compare LLM metrics by prompt version for A/B testing."""
    from db.models import LLMMetric

    metrics = db.query(LLMMetric).filter(LLMMetric.prompt_version.isnot(None)).all()
    if not metrics:
        return {"versions": {}, "message": "No prompt versions tracked yet. Pass prompt_version to call_llm()."}

    versions: Dict[str, Dict] = {}
    for m in metrics:
        v = m.prompt_version or "unknown"
        if v not in versions:
            versions[v] = {"calls": 0, "successes": 0, "latencies": [], "tokens": [], "costs": []}
        vd = versions[v]
        vd["calls"] += 1
        if m.success:
            vd["successes"] += 1
        vd["latencies"].append(m.latency_ms)
        if m.total_tokens:
            vd["tokens"].append(m.total_tokens)
        if m.cost_estimate:
            vd["costs"].append(m.cost_estimate)

    result = {}
    for v, vd in versions.items():
        lats = vd["latencies"]
        result[v] = {
            "calls": vd["calls"],
            "success_rate": round(vd["successes"] / max(vd["calls"], 1) * 100, 1),
            "avg_latency_ms": int(sum(lats) / max(len(lats), 1)),
            "p95_latency_ms": int(sorted(lats)[int(len(lats) * 0.95)]) if lats else 0,
            "avg_tokens": int(sum(vd["tokens"]) / max(len(vd["tokens"]), 1)) if vd["tokens"] else 0,
            "total_cost": round(sum(vd["costs"]), 4),
        }

    return {"versions": result}


@router.get("/admin/llm/config", dependencies=[Depends(require_admin_read)])
def admin_llm_config():
    """Return current LLM runtime configuration."""
    from api.llm import LLM_MODEL, LLM_URL, load_prompt
    classify = load_prompt("classify")
    remediation = load_prompt("remediation")
    exec_summary = load_prompt("executive-summary")
    host = LLM_URL.split("//")[1].split("/")[0] if "//" in LLM_URL else LLM_URL
    return {
        "model": LLM_MODEL,
        "api_endpoint": host,
        "prompts": {
            "classify": {"max_tokens": classify.get("max_tokens", 500), "temperature": classify.get("temperature", 0.1), "version": classify.get("version"), "timeout": 30},
            "remediation": {"max_tokens": remediation.get("max_tokens", 1200), "temperature": remediation.get("temperature", 0.2), "version": remediation.get("version"), "timeout": 30},
            "executive-summary": {"max_tokens": exec_summary.get("max_tokens", 2000), "temperature": exec_summary.get("temperature", 0.3), "version": exec_summary.get("version"), "timeout": 90},
        },
    }


@router.get("/admin/llm/ground-truth", dependencies=[Depends(require_admin_read)])
def admin_llm_ground_truth(db: Session = Depends(get_db)):
    """Return labeled ground truth dataset from approved proposals and confirmed evaluations."""
    from engine.ground_truth import build_ground_truth
    entries = build_ground_truth(db)
    return {"total": len(entries), "entries": entries}


@router.get("/admin/llm/accuracy", dependencies=[Depends(require_admin_read)])
def admin_llm_accuracy(db: Session = Depends(get_db)):
    """Measure LLM classification accuracy against reviewed proposals."""
    from engine.ground_truth import measure_accuracy
    return measure_accuracy(db)


@router.get("/admin/llm/auto")
def admin_llm_auto_status():
    """Get auto-LLM analysis status (enabled/disabled)."""
    from engine.auto_llm import is_enabled
    return {"enabled": is_enabled()}


@router.post("/admin/llm/auto", dependencies=[Depends(require_admin)])
def admin_llm_auto_toggle(req: dict):
    """Enable or disable auto-LLM analysis. Body: {"enabled": true/false}"""
    from engine.auto_llm import set_enabled, is_enabled
    enabled = req.get("enabled")
    if enabled is None:
        set_enabled(not is_enabled())
    else:
        set_enabled(bool(enabled))
    return {"enabled": is_enabled()}


@router.get("/admin/auto-investigate")
def admin_auto_investigate_status():
    """Get auto-investigation status (enabled/disabled + current config)."""
    enabled = os.environ.get("STARGATE_AUTO_INVESTIGATE", "false").lower() == "true"
    return {
        "enabled": enabled,
        "max_per_catalog_hour": int(os.environ.get("STARGATE_INVESTIGATE_MAX_PER_CATALOG_HOUR", "3")),
        "max_per_day": int(os.environ.get("STARGATE_INVESTIGATE_MAX_PER_DAY", "50")),
        "dedup_hours": int(os.environ.get("STARGATE_INVESTIGATE_DEDUP_HOURS", "4")),
        "skip_self_resolve_pct": int(os.environ.get("STARGATE_INVESTIGATE_SKIP_SELF_RESOLVE_PCT", "50")),
    }


@router.post("/admin/auto-investigate", dependencies=[Depends(require_admin)])
def admin_auto_investigate_toggle(req: dict):
    """Toggle auto-investigation. Body: {"enabled": true/false}"""
    enabled = req.get("enabled")
    if enabled is not None:
        os.environ["STARGATE_AUTO_INVESTIGATE"] = "true" if enabled else "false"
    else:
        current = os.environ.get("STARGATE_AUTO_INVESTIGATE", "false").lower() == "true"
        os.environ["STARGATE_AUTO_INVESTIGATE"] = "false" if current else "true"
    return admin_auto_investigate_status()


@router.get("/admin/investigations", dependencies=[Depends(require_admin_read)])
def admin_investigations_list(
    lab_code: Optional[str] = None,
    cluster: Optional[str] = None,
    status: Optional[str] = None,
    trigger_type: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List recent investigations with optional filters."""
    from db.models import InvestigationRecord
    q = db.query(InvestigationRecord)
    if lab_code:
        q = q.filter(InvestigationRecord.lab_code == lab_code)
    if cluster:
        q = q.filter(InvestigationRecord.cluster == cluster)
    if status:
        q = q.filter(InvestigationRecord.status == status)
    if trigger_type:
        q = q.filter(InvestigationRecord.trigger_type == trigger_type)
    records = q.order_by(InvestigationRecord.created_at.desc()).limit(limit).all()
    return {
        "total": len(records),
        "investigations": [
            {
                "job_id": r.job_id,
                "lab_code": r.lab_code,
                "cluster": r.cluster,
                "failure_class": r.failure_class,
                "trigger_type": r.trigger_type,
                "status": r.status,
                "iterations": r.iterations,
                "model_used": r.model_used,
                "cost_estimate": r.cost_estimate,
                "root_cause": r.root_cause,
                "has_analysis": bool(r.analysis),
                "fallback": r.fallback,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            }
            for r in records
        ],
    }


@router.get("/admin/investigations/stats", dependencies=[Depends(require_admin_read)])
def admin_investigations_stats(db: Session = Depends(get_db)):
    """Aggregated investigation stats for today."""
    from db.models import InvestigationRecord
    from db.repository import count_investigations_today
    from sqlalchemy import func

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    today_count = count_investigations_today(db)
    queue_depth = db.query(InvestigationRecord).filter(InvestigationRecord.status == "queued").count()

    by_trigger = db.query(
        InvestigationRecord.trigger_type, func.count(),
    ).filter(InvestigationRecord.created_at >= today_start).group_by(
        InvestigationRecord.trigger_type,
    ).all()

    avg_cost = db.query(func.avg(InvestigationRecord.cost_estimate)).filter(
        InvestigationRecord.created_at >= today_start,
        InvestigationRecord.cost_estimate.isnot(None),
    ).scalar()

    return {
        "today": today_count,
        "queue_depth": queue_depth,
        "by_trigger_type": {t: c for t, c in by_trigger},
        "avg_cost_today": round(avg_cost, 4) if avg_cost else None,
        "max_per_day": int(os.environ.get("STARGATE_INVESTIGATE_MAX_PER_DAY", "50")),
    }


@router.get("/admin/audit-trail", dependencies=[Depends(require_admin_read)])
def admin_audit_trail(limit: int = 50, db: Session = Depends(get_db)):
    """Recent audit trail entries — all actions proposed, approved, executed, or failed."""
    from db.models import AuditLog
    entries = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
    return {
        "total": len(entries),
        "entries": [
            {
                "id": e.id,
                "action_type": e.action_type,
                "target": e.target,
                "status": e.status,
                "confidence": (e.parameters or {}).get("confidence"),
                "evidence_source": (e.parameters or {}).get("evidence_source"),
                "executed_at": e.executed_at.isoformat() if e.executed_at else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ],
    }


# ===========================================================================
# Synthetic integration endpoints
# ===========================================================================

@router.post("/admin/evidence-source", dependencies=[Depends(require_admin)])
def set_evidence_source(req: dict):
    """Toggle between real and synthetic evidence sources."""
    import api.routers._shared as _shared
    source = req.get("source", "")
    if source not in ("real", "synthetic"):
        raise HTTPException(status_code=400, detail="source must be 'real' or 'synthetic'")
    _shared._evidence_source = source
    _shared._synthetic_scenario = req.get("scenario") if source == "synthetic" else None
    return {"source": _shared._evidence_source, "scenario": _shared._synthetic_scenario}


@router.get("/admin/evidence-source", dependencies=[Depends(require_admin_read)])
def get_evidence_source():
    """Get current evidence source state."""
    import api.routers._shared as _shared
    return {"source": _shared._evidence_source, "scenario": _shared._synthetic_scenario}


@router.post("/admin/dry-run", dependencies=[Depends(require_admin)])
def set_dry_run(req: dict):
    """Toggle dry-run mode."""
    import api.routers._shared as _shared
    _shared._dry_run_enabled = bool(req.get("enabled", False))
    return {"dry_run": _shared._dry_run_enabled}


@router.get("/admin/approval-queue", dependencies=[Depends(require_admin_read)])
def get_approval_queue(db: Session = Depends(get_db)):
    """Get pending and recently resolved actions."""
    from db.models import PendingAction

    pending = db.query(PendingAction).filter(
        PendingAction.status == "pending",
        PendingAction.target != "stargate-test",
    ).order_by(PendingAction.id.desc()).all()

    recently_resolved = db.query(PendingAction).filter(
        PendingAction.status == "auto_resolved",
        PendingAction.target != "stargate-test",
    ).order_by(PendingAction.id.desc()).limit(20).all()

    def _serialize(p):
        return {
            "id": p.id,
            "action_type": p.action_type,
            "target": p.target,
            "confidence": p.confidence,
            "proposed_by": getattr(p, 'proposed_by', None) or "stargate",
            "proposed_at": p.proposed_at.isoformat() if p.proposed_at else None,
            "status": p.status,
            "reviewed_at": p.reviewed_at.isoformat() if getattr(p, 'reviewed_at', None) else None,
            "dismiss_reason": (p.parameters or {}).get("dismiss_reason"),
            "parameters": p.parameters,
        }

    return {
        "pending": [_serialize(p) for p in pending],
        "resolved": [_serialize(p) for p in recently_resolved],
    }


@router.post("/admin/approval-queue/{action_id}/approve", dependencies=[Depends(require_admin)])
def approve_action(action_id: int, db: Session = Depends(get_db)):
    """Approve a pending action."""
    from db.models import PendingAction
    action = db.query(PendingAction).filter(PendingAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    action.status = "approved"
    action.reviewed_at = datetime.now(timezone.utc)
    action.reviewed_by = "admin"
    db.commit()

    execution_result = None
    try:
        from api.action_executor import execute_action
        execution_result = execute_action(
            action_type=action.action_type,
            target=action.target,
            parameters=action.parameters or {},
            confidence=1.0,
            db=db,
        )
    except Exception as e:
        execution_result = {"error": str(e)}

    return {"id": action.id, "status": "approved", "execution": execution_result}


@router.post("/admin/approval-queue/{action_id}/reject", dependencies=[Depends(require_admin)])
def reject_action(action_id: int, req: dict = None, db: Session = Depends(get_db)):
    """Reject/dismiss a pending action with optional reason."""
    from db.models import PendingAction
    action = db.query(PendingAction).filter(PendingAction.id == action_id).first()
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    reason = (req or {}).get("reason", "dismissed")
    action.status = "dismissed"
    action.reviewed_at = datetime.now(timezone.utc)
    action.reviewed_by = "admin"
    if action.parameters is None:
        action.parameters = {}
    action.parameters["dismiss_reason"] = reason
    db.commit()
    return {"id": action.id, "status": "dismissed", "reason": reason}


@router.get("/admin/audit", dependencies=[Depends(require_admin_read)])
def get_audit_trail(limit: int = 50, db: Session = Depends(get_db)):
    """Get audit trail entries."""
    from db.models import AuditLog
    entries = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(limit).all()
    return {
        "entries": [
            {
                "id": e.id,
                "action_type": e.action_type,
                "target": e.target,
                "parameters": e.parameters,
                "status": e.status,
                "proposed_by": e.proposed_by,
                "approved_by": e.approved_by,
                "executed_at": e.executed_at.isoformat() if e.executed_at else None,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in entries
        ]
    }


@router.post("/admin/validate", dependencies=[Depends(require_admin)])
def validate_scenarios(db: Session = Depends(get_db)):
    """Run all synthetic scenarios and compare against expected outcomes."""
    results = []
    try:
        from emulator.scenarios import get_all_scenarios
        scenarios = get_all_scenarios()
    except ImportError:
        return {"total": 0, "passed": 0, "failed": 0, "results": [], "error": "Emulator not found — pip install the stargate-synthetic-client-emulator package"}

    for name, scenario in sorted(scenarios.items()):
        evidence = scenario.generate_evidence()
        expected = scenario.expected_recommendations

        from api.routers._shared import _load_rubric_for_stage
        from engine.rubric_evaluator import evaluate_rubric
        computed_outcomes = {}
        for stage_id, ev in evidence.items():
            rubric = _load_rubric_for_stage(stage_id)
            if rubric:
                result = evaluate_rubric(rubric, ev)
                computed_outcomes[stage_id] = result.outcome.value
            else:
                bools = [v for v in ev.values() if isinstance(v, bool)]
                computed_outcomes[stage_id] = "pass" if bools and all(bools) else "fail" if bools else "pass"

        validation = scenario.validate_outcomes(computed_outcomes)

        match = validation["match"]
        results.append({
            "scenario": name,
            "match": match,
            "expected_recommendations": expected,
            "stages_evaluated": len(evidence),
            "mismatches": validation.get("mismatches", []),
        })

    passed = sum(1 for r in results if r["match"])
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }


@router.post("/admin/run-phase-d-test", dependencies=[Depends(require_admin)])
def run_phase_d_test(db: Session = Depends(get_db)):
    """Phase D proof: emulator → policy → mock validate → execute → verify → receipt.

    Runs entirely in stargate-test namespace. Does NOT touch production workloads.
    """
    steps = []

    try:
        result = validate_scenarios(db)
        steps.append({
            "step": "mock_validate",
            "description": "Validate all emulator scenarios against expected recommendations",
            "passed": result.get("passed", 0),
            "failed": result.get("failed", 0),
            "total": result.get("total", 0),
            "success": result.get("failed", 0) == 0,
        })
    except Exception as e:
        steps.append({"step": "mock_validate", "success": False, "error": str(e)})

    try:
        from engine.mock_cluster import MockCluster
        from engine.oc_executor import map_action_to_commands

        mc = MockCluster()
        test_actions = [
            ("cluster_capacity", {"deployment": "test-app", "replicas": 3, "image": "registry.access.redhat.com/ubi9/ubi-minimal:latest"}),
            ("cleanup_stuck", {"pods": ["test-pod-1", "test-pod-2"]}),
            ("smoke_test_failing", {"deployment": "showroom"}),
        ]
        mock_results = []
        for action_type, params in test_actions:
            commands = map_action_to_commands(action_type, "stargate-test", params)
            for cmd in commands:
                r = mc.execute(cmd)
                mock_results.append({"command": cmd, "success": r["success"]})

        all_ok = all(r["success"] for r in mock_results)
        steps.append({
            "step": "mock_execute",
            "description": "Validate oc commands through MockCluster",
            "commands_tested": len(mock_results),
            "success": all_ok,
            "state_after": mc.get_state("stargate-test"),
            "audit_trail": len(mc.history),
        })
    except Exception as e:
        steps.append({"step": "mock_execute", "success": False, "error": str(e)})

    try:
        from engine.feedback_loop import run_feedback_loop
        loop_result = run_feedback_loop("mixed-contention", db=db, force_execute=True)
        steps.append({
            "step": "feedback_loop",
            "description": "Full feedback loop: scenario → evaluate → recommend → execute → verify",
            "scenario": "mixed-contention",
            "success": loop_result.success if hasattr(loop_result, 'success') else True,
            "recommendations": len(loop_result.recommendations) if hasattr(loop_result, 'recommendations') else 0,
            "actions_taken": len(loop_result.actions_taken) if hasattr(loop_result, 'actions_taken') else 0,
        })
    except Exception as e:
        steps.append({"step": "feedback_loop", "success": False, "error": str(e)})

    receipt = {
        "type": "phase-d-test-namespace",
        "phase": "D",
        "gate": "Synthetic emulator proof — mock + test namespace execution",
        "evidence": f"{len(steps)} steps completed, {sum(1 for s in steps if s.get('success'))} passed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps_summary": [{s["step"]: s.get("success", False)} for s in steps],
    }

    try:
        repository.save_receipt(db, "phase-d-test", "D", receipt, all(s.get("success", False) for s in steps))
    except Exception:
        pass

    return {
        "phase": "D",
        "steps": steps,
        "passed": all(s.get("success", False) for s in steps),
        "receipt": receipt,
    }


@router.post("/admin/run-chaos-test", dependencies=[Depends(require_admin)])
def run_chaos_test(db: Session = Depends(get_db)):
    """Chaos test: deploy broken workloads → evaluate → LLM diagnose → fix → verify recovery.

    Runs entirely in stargate-test namespace. Each scenario deploys a deliberately broken
    workload, confirms the rubric detects the failure, optionally asks the LLM to classify,
    applies the fix, and verifies recovery.
    """
    from engine.chaos_scenarios import CHAOS_SCENARIOS, run_chaos_scenario

    kubeconfig = os.environ.get("KUBECONFIG", "")
    results = []
    for scenario in CHAOS_SCENARIOS:
        result = run_chaos_scenario(scenario, kubeconfig, db=db)
        results.append(result)

    passed = sum(1 for r in results if r.get("passed"))
    receipt = {
        "type": "chaos-test-remediation",
        "phase": "D",
        "gate": "LLM remediation accuracy — real broken workloads fixed by AI",
        "scenarios": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "evidence": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        repository.save_receipt(db, "chaos-test-remediation", "D", receipt, passed == len(results))
    except Exception:
        pass

    return {"results": results, "receipt": receipt}


@router.get("/admin/receipts", dependencies=[Depends(require_admin_read)])
def get_receipts(receipt_type: str = None, phase: str = None, limit: int = 50, db: Session = Depends(get_db)):
    """Get persisted receipts from database."""
    return {"receipts": repository.get_receipts(db, receipt_type=receipt_type, phase=phase, limit=limit)}


@router.get("/admin/receipts/{receipt_type}", dependencies=[Depends(require_admin_read)])
def get_latest_receipt(receipt_type: str, db: Session = Depends(get_db)):
    """Get the latest receipt of a given type."""
    receipt = repository.get_latest_receipt(db, receipt_type)
    if not receipt:
        raise HTTPException(status_code=404, detail=f"No receipt found for type '{receipt_type}'")
    return receipt
