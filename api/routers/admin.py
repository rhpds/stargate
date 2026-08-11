"""Admin router — scheduler management, scan history, and LLM observability endpoints."""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from db.database import get_db
from db import repository
from api.routers._shared import (
    limiter,
    _scheduler,
    _scheduler_lock,
    _load_latest_scan,
    _load_latest_babylon,
    _shutdown_event,
    require_admin,
    require_admin_read,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Scheduler management
# ---------------------------------------------------------------------------

@router.post("/admin/scheduler/start", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
def admin_scheduler_start(
    request: Request,
    tier1: int = 300,
    tier2: int = 900,
    tier3: int = 3600,
    batch: int = 5,

):
    """Start the scanner scheduler."""
    from api.routers._shared import _scheduler as _sched
    import api.routers._shared as _shared

    with _scheduler_lock:
        if _shared._scheduler is not None:
            return {"status": "already_running", "workers": len(_shared._scheduler.workers)}

        from cli.scheduler import Scheduler
        from cli.scan import CLUSTERS

        _shared._scheduler = Scheduler(
            clusters=CLUSTERS,
            api_url="http://localhost:8090",
            tier1=tier1,
            tier2=tier2,
            tier3=tier3,
            tier3_batch=batch,
        )
        available, unavailable = _shared._scheduler.start()
        _shared._scheduler._start_result = {"available": available, "unavailable": unavailable}
        return {
            "status": "started",
            "available": available,
            "unavailable": unavailable,
        }


@router.post("/admin/scheduler/stop", dependencies=[Depends(require_admin)])
def admin_scheduler_stop():
    """Stop the scanner scheduler."""
    import api.routers._shared as _shared

    with _scheduler_lock:
        if _shared._scheduler is None:
            return {"status": "not_running"}
        _shared._scheduler.stop()
        _shared._scheduler = None
        return {"status": "stopped"}


@router.get("/admin/scheduler/status", dependencies=[Depends(require_admin_read)])
def admin_scheduler_status():
    """Get scheduler worker status."""
    import api.routers._shared as _shared

    if _shared._scheduler is None:
        scan_dir = Path(__file__).parent.parent.parent / "scan-history"
        scan_files = sorted(scan_dir.glob("scan-*.json"), reverse=True)
        last_scan = None
        if scan_files:
            try:
                fname = scan_files[0].stem
                last_scan = __import__("datetime").datetime.strptime(
                    fname, "scan-%Y%m%d-%H%M%S"
                ).replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                pass

        # Load latest scan per cluster even when stopped
        latest_scans: Dict[str, Dict] = {}
        for scan_file in sorted(scan_dir.glob("scan-*.json"), reverse=True):
            try:
                fname = scan_file.stem
                file_ts = datetime.strptime(fname, "scan-%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
                with open(scan_file) as f:
                    scans_data = json.load(f)
                for s in scans_data:
                    cname = s.get("cluster", "")
                    if cname and cname not in latest_scans:
                        latest_scans[cname] = {
                            "scan_time": file_ts.isoformat(),
                            "status": s.get("status"),
                            "avg_cpu_pct": s.get("avg_cpu_pct"),
                            "total_vms": s.get("total_vms"),
                            "vms_per_node": s.get("vms_per_node"),
                            "health_rate": s.get("health_rate"),
                            "sandbox_active": s.get("sandbox_active"),
                            "sandbox_failing": s.get("sandbox_failing"),
                            "sandbox_crashloop": s.get("sandbox_crashloop"),
                            "hot_nodes": s.get("hot_nodes"),
                            "issues": s.get("issues", []),
                        }
            except (ValueError, json.JSONDecodeError):
                continue

        return {
            "running": False,
            "workers": [],
            "last_scan": last_scan,
            "scan_files": len(list(scan_dir.glob("scan-*.json"))),
            "latest_scans": latest_scans,
        }

    workers = []
    for wt in _shared._scheduler.workers:
        w = {
            "cluster": wt.worker.state.name,
            "running": wt.running,
            "ticks": wt.tick_count,
            "errors": wt.error_count,
            "offset": wt.offset,
            "tier1_interval": wt.worker.TIER1_INTERVAL,
            "tier2_interval": wt.worker.TIER2_INTERVAL,
            "tier3_interval": wt.worker.TIER3_INTERVAL,
        }

        state = wt.worker.state
        w["last_node_scan"] = state.last_node_scan if state.last_node_scan else None
        w["last_pod_scan"] = state.last_pod_scan if state.last_pod_scan else None
        w["last_ns_scan"] = state.last_ns_scan if state.last_ns_scan else None
        w["active_sandboxes"] = len(state.known_sandboxes) if hasattr(state, "known_sandboxes") else 0
        w["failing_sandboxes"] = len(state.failing_sandboxes) if hasattr(state, "failing_sandboxes") else 0

        if wt.last_result:
            r = wt.last_result
            nodes = r.get("nodes", {})
            pods = r.get("pods", {})
            ns_data = r.get("namespaces", {})
            w["avg_cpu"] = nodes.get("avg_cpu", 0)
            w["hot_nodes"] = nodes.get("hot_nodes", 0)
            w["node_status"] = nodes.get("status", "unknown")
            w["total_vms"] = pods.get("total_vms", 0)
            w["vms_per_node"] = pods.get("vms_per_node", 0)
            w["crashloops"] = pods.get("crashloops", 0)
            w["new_failures"] = len(pods.get("new_failures", []))
            w["recovered"] = len(pods.get("recovered", []))
            w["ns_scanned"] = ns_data.get("total_scanned", 0)
            w["ns_available"] = ns_data.get("total_available", 0)
            if pods.get("new_failures"):
                w["recent_failures"] = pods["new_failures"][:5]
        else:
            w["node_status"] = "pending"

        workers.append(w)

    babylon = None
    if hasattr(_shared._scheduler, "_babylon_result") and _shared._scheduler._babylon_result:
        br = _shared._scheduler._babylon_result
        if "error" not in br:
            pools = br.get("pools", {})
            prov = br.get("provisioning", {})
            babylon = {
                "total_pools": pools.get("total_pools", 0),
                "exhausted": len(pools.get("exhausted", [])),
                "low": len(pools.get("low", [])),
                "total_subjects": prov.get("total", 0),
                "started": prov.get("started", 0),
                "failed": prov.get("failed", 0),
            }

    # Include latest scan snapshot per cluster (from scan-history files)
    scan_dir = Path(__file__).parent.parent.parent / "scan-history"
    latest_scans: Dict[str, Dict] = {}
    for scan_file in sorted(scan_dir.glob("scan-*.json"), reverse=True):
        try:
            fname = scan_file.stem
            file_ts = datetime.strptime(fname, "scan-%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
            with open(scan_file) as f:
                scans = json.load(f)
            for s in scans:
                cname = s.get("cluster", "")
                if cname and cname not in latest_scans:
                    latest_scans[cname] = {
                        "scan_time": file_ts.isoformat(),
                        "status": s.get("status"),
                        "avg_cpu_pct": s.get("avg_cpu_pct"),
                        "total_vms": s.get("total_vms"),
                        "vms_per_node": s.get("vms_per_node"),
                        "health_rate": s.get("health_rate"),
                        "sandbox_active": s.get("sandbox_active"),
                        "sandbox_failing": s.get("sandbox_failing"),
                        "sandbox_crashloop": s.get("sandbox_crashloop"),
                        "hot_nodes": s.get("hot_nodes"),
                        "issues": s.get("issues", []),
                    }
        except (ValueError, json.JSONDecodeError):
            continue

    # Overlay live worker data onto latest_scans when fresher
    for wt in _shared._scheduler.workers:
        if wt.tick_count == 0 or not wt.last_result:
            continue
        cname = wt.worker.state.name
        r = wt.last_result
        nodes = r.get("nodes", {})
        pods = r.get("pods", {})
        latest_scans[cname] = {
            "scan_time": datetime.now(timezone.utc).isoformat(),
            "status": nodes.get("status", "unknown"),
            "avg_cpu_pct": nodes.get("avg_cpu"),
            "total_vms": pods.get("total_vms", 0),
            "vms_per_node": pods.get("vms_per_node", 0),
            "health_rate": pods.get("health_rate", 0),
            "sandbox_active": pods.get("sandbox_active", 0),
            "sandbox_failing": pods.get("sandbox_failing", 0),
            "sandbox_crashloop": pods.get("crashloops", 0),
            "hot_nodes": nodes.get("hot_nodes", 0),
            "issues": nodes.get("issues", []),
            "source": "live",
        }

    start_result = getattr(_shared._scheduler, "_start_result", {})

    return {
        "running": True,
        "workers": workers,
        "babylon": babylon,
        "worker_count": len(workers),
        "available_clusters": start_result.get("available", []),
        "unavailable_clusters": start_result.get("unavailable", []),
        "latest_scans": latest_scans,
    }


# ---------------------------------------------------------------------------
# Scan history
# ---------------------------------------------------------------------------

@router.get("/admin/scan-history", dependencies=[Depends(require_admin_read)])
def admin_scan_history(limit: int = 50):
    """Return scan history timeline from scan-history files."""
    scan_dir = Path(__file__).parent.parent.parent / "scan-history"
    scan_files = sorted(scan_dir.glob("scan-*.json"), reverse=True)[:limit]

    timeline = []
    for scan_file in reversed(scan_files):
        try:
            fname = scan_file.stem
            file_ts = datetime.strptime(fname, "scan-%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
            with open(scan_file) as f:
                scans = json.load(f)
            entry = {
                "timestamp": file_ts.isoformat(),
                "clusters": {},
            }
            for s in scans:
                cname = s.get("cluster", "")
                if cname:
                    entry["clusters"][cname] = {
                        "status": s.get("status"),
                        "avg_cpu_pct": s.get("avg_cpu_pct"),
                        "total_vms": s.get("total_vms", 0),
                        "vms_per_node": s.get("vms_per_node", 0),
                        "health_rate": s.get("health_rate", 0),
                        "sandbox_active": s.get("sandbox_active", 0),
                        "sandbox_failing": s.get("sandbox_failing", 0),
                    }
            timeline.append(entry)
        except (ValueError, json.JSONDecodeError):
            continue

    return {"timeline": timeline, "total_files": len(list(scan_dir.glob("scan-*.json")))}


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
    from datetime import timedelta

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
    from datetime import timedelta

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

    # Approval rate drift
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

    # Determine drift status
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
        from fastapi import HTTPException
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
        from fastapi import HTTPException
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

        # Evaluate each stage using the actual rubric evaluator
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
    from datetime import datetime, timezone

    steps = []

    # Step 1: Mock validate all scenarios
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

    # Step 2: Mock execute — validate commands through MockCluster
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

    # Step 3: Run feedback loop in mock mode
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

    # Step 4: Generate receipt
    receipt = {
        "type": "phase-d-test-namespace",
        "phase": "D",
        "gate": "Synthetic emulator proof — mock + test namespace execution",
        "evidence": f"{len(steps)} steps completed, {sum(1 for s in steps if s.get('success'))} passed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps_summary": [{s["step"]: s.get("success", False)} for s in steps],
    }

    try:
        from db import repository
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
    import os
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
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"No receipt found for type '{receipt_type}'")
    return receipt


# ---------------------------------------------------------------------------
# Per-lab auto-remediation config
# ---------------------------------------------------------------------------

from api.constants import VALID_EXECUTION_MODES


@router.get("/admin/remediation/config", dependencies=[Depends(require_admin_read)])
def list_remediation_configs(db: Session = Depends(get_db)):
    """List all per-lab remediation configs, joined with lab display names."""
    from db.models import LabMapping
    configs = repository.get_all_lab_remediation_configs(db)
    mappings = {m.lab_code: m.ci_name for m in db.query(LabMapping).all()}
    return {
        "configs": [
            {
                "lab_code": c.lab_code,
                "display_name": mappings.get(c.lab_code, c.lab_code),
                "execution_mode": c.execution_mode,
                "max_actions_per_hour": c.max_actions_per_hour,
                "enabled_by": c.enabled_by,
                "enabled_at": c.enabled_at.isoformat() if c.enabled_at else None,
                "notes": c.notes,
            }
            for c in configs
        ],
    }


@router.get("/admin/remediation/config/{lab_code}", dependencies=[Depends(require_admin_read)])
def get_remediation_config(lab_code: str, db: Session = Depends(get_db)):
    """Get remediation config for a specific lab."""
    config = repository.get_lab_remediation_config(db, lab_code)
    if not config:
        return {"lab_code": lab_code, "execution_mode": "recommend_only", "max_actions_per_hour": 5, "configured": False}
    return {
        "lab_code": config.lab_code,
        "execution_mode": config.execution_mode,
        "max_actions_per_hour": config.max_actions_per_hour,
        "enabled_by": config.enabled_by,
        "enabled_at": config.enabled_at.isoformat() if config.enabled_at else None,
        "notes": config.notes,
        "configured": True,
    }


@router.put("/admin/remediation/config/{lab_code}", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
def update_remediation_config(lab_code: str, request: Request, body: "RemediationConfigRequest", db: Session = Depends(get_db)):
    """Create or update remediation config for a lab."""
    from fastapi import HTTPException
    from api.schemas import RemediationConfigRequest  # noqa: F811

    if body.execution_mode not in VALID_EXECUTION_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid execution_mode. Must be one of: {VALID_EXECUTION_MODES}")

    config = repository.upsert_lab_remediation_config(
        db,
        lab_code=lab_code,
        execution_mode=body.execution_mode,
        max_actions_per_hour=body.max_actions_per_hour,
        enabled_by=body.enabled_by,
        notes=body.notes,
    )

    from db.models import AuditLog
    db.add(AuditLog(
        action_type="remediation_config_change",
        target=lab_code,
        parameters={"execution_mode": mode, "max_actions_per_hour": max_actions},
        proposed_by=body.get("enabled_by", "admin"),
        status="executed",
        executed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    ))
    db.commit()

    return {
        "lab_code": config.lab_code,
        "execution_mode": config.execution_mode,
        "max_actions_per_hour": config.max_actions_per_hour,
        "enabled_by": config.enabled_by,
        "enabled_at": config.enabled_at.isoformat() if config.enabled_at else None,
        "notes": config.notes,
    }


@router.delete("/admin/remediation/config/{lab_code}", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
def delete_remediation_config(lab_code: str, request: Request, db: Session = Depends(get_db)):
    """Reset a lab to default recommend_only mode."""
    deleted = repository.delete_lab_remediation_config(db, lab_code)
    if not deleted:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"No config found for lab '{lab_code}'")

    from db.models import AuditLog
    db.add(AuditLog(
        action_type="remediation_config_reset",
        target=lab_code,
        parameters={"execution_mode": "recommend_only"},
        proposed_by="admin",
        status="executed",
        executed_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    ))
    db.commit()

    return {"lab_code": lab_code, "execution_mode": "recommend_only", "deleted": True}


@router.get("/admin/remediation/activity", dependencies=[Depends(require_admin_read)])
def get_remediation_activity(limit: int = 50, db: Session = Depends(get_db)):
    """Get recent remediation-related audit log entries."""
    return {"activity": repository.get_remediation_activity(db, limit=limit)}


@router.get("/admin/remediation/recommendations", dependencies=[Depends(require_admin_read)])
def get_remediation_recommendations(limit: int = 20, cluster: str = None, db: Session = Depends(get_db)):
    """Auto-generated remediation recommendations based on current failures."""
    from db.models import EvaluationRecord
    from sqlalchemy import func
    from datetime import timedelta

    from api.constants import WARNING_CLASSES as _REC_WARN
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    query = db.query(
        EvaluationRecord.lab_code,
        EvaluationRecord.cluster_name,
        EvaluationRecord.failure_class,
        func.count(EvaluationRecord.id).label("count"),
        func.max(EvaluationRecord.evaluated_at).label("last_seen"),
        func.max(EvaluationRecord.message).label("sample_message"),
    ).filter(
        EvaluationRecord.outcome == "fail",
        EvaluationRecord.failure_class.isnot(None),
        EvaluationRecord.failure_class.notin_(_REC_WARN),
        EvaluationRecord.lab_code.isnot(None),
        EvaluationRecord.evaluated_at >= cutoff,
    )
    if cluster:
        query = query.filter(EvaluationRecord.cluster_name == cluster)

    rows = query.group_by(
        EvaluationRecord.lab_code, EvaluationRecord.cluster_name, EvaluationRecord.failure_class,
    ).order_by(func.count(EvaluationRecord.id).desc()).limit(limit * 3).all()

    import yaml
    from pathlib import Path as _P
    catalog_path = _P(__file__).parent.parent.parent / "remediations" / "catalog.yaml"
    catalog_actions = {}
    if catalog_path.exists():
        with open(catalog_path) as f:
            cat = yaml.safe_load(f) or []
        for entry in cat:
            for cond in entry.get("allowed_when", []):
                if "failure_class ==" in cond:
                    fc = cond.split("==")[1].strip()
                    if fc not in catalog_actions:
                        catalog_actions[fc] = {
                            "id": entry["id"],
                            "mode": entry.get("mode", "recommend_only"),
                            "risk": entry.get("risk", "unknown"),
                            "commands": entry.get("commands", []),
                        }

    from api.constants import is_ecosystem_ns as _is_ecosystem_ns
    from engine.failure_class_loader import get_class as _get_fc
    _SEV_LEVELS = ["low", "medium", "high", "critical"]
    recommendations = []
    for lab_code, cluster_name, failure_class, count, last_seen, sample_message in rows:
        is_eco = _is_ecosystem_ns(lab_code)
        catalog = catalog_actions.get(failure_class, {})
        fc_def = _get_fc(failure_class) or {}
        base = fc_def.get("severity", "medium")
        base_idx = _SEV_LEVELS.index(base) if base in _SEV_LEVELS else 1
        bump = 1 if count >= 50 else 0
        severity = _SEV_LEVELS[min(base_idx + bump, 3)]
        recommendations.append({
            "namespace": lab_code,
            "cluster": cluster_name,
            "failure_class": failure_class,
            "count": count,
            "severity": severity,
            "last_seen": last_seen.isoformat() if last_seen else None,
            "sample_message": (sample_message or "")[:200],
            "is_ecosystem": is_eco,
            "catalog_action": catalog.get("id"),
            "catalog_mode": catalog.get("mode", "unknown"),
            "catalog_risk": catalog.get("risk", "unknown"),
            "catalog_commands": [cmd.replace("{namespace}", lab_code) for cmd in catalog.get("commands", [])[:2]],
        })

    recommendations.sort(key=lambda r: (not r["is_ecosystem"], -r["count"]))
    return {
        "recommendations": recommendations[:limit],
        "total": len(recommendations),
        "ecosystem_count": sum(1 for r in recommendations if r["is_ecosystem"]),
    }


@router.post("/admin/remediation/preview", dependencies=[Depends(require_admin)])
@limiter.limit("30/minute")
def preview_remediation(request: Request, body: "RemediationPreviewRequest", db: Session = Depends(get_db)):
    """Preview what remediation would do — shows every gate check and exact commands without executing."""
    import os
    import re
    from api.schemas import RemediationPreviewRequest  # noqa: F811
    from api.routers._shared import _dry_run_enabled, CONFIDENCE_THRESHOLD, TEST_NAMESPACE, EXECUTION_TARGET
    from api.action_executor import _get_lab_execution_mode, _check_rate_limit
    from api.constants import is_ecosystem_ns as _is_ecosystem_ns
    from engine.catalog_loader import load_catalog, ACTION_TO_FAILURE_CLASSES

    namespace = body.namespace
    failure_class = body.failure_class
    cluster = body.cluster
    lab_code = body.lab_code or namespace

    # Derive action_type from failure_class
    action_type = body.action_type or ""
    if not action_type:
        for at, fcs in ACTION_TO_FAILURE_CLASSES.items():
            if failure_class in fcs:
                action_type = at
                break
        if not action_type:
            action_type = "cleanup_stuck"

    # Template substitution helper
    _safe_name = re.compile(r"^[a-zA-Z0-9._\-]*$")
    def _sub(cmd: str) -> str:
        return cmd.replace("{namespace}", namespace).replace("{pod}", "{pod}").replace("{deployment}", "{deployment}")

    # --- Gate -1: Namespace allowlist ---
    from api.constants import REMEDIATION_ALLOWED_PREFIXES
    ns_allowed = namespace == TEST_NAMESPACE or any(
        namespace.startswith(p) for p in REMEDIATION_ALLOWED_PREFIXES
    )

    # --- Gate 0: Lab execution mode ---
    mode = _get_lab_execution_mode(db, lab_code)
    is_test = namespace == TEST_NAMESPACE

    # --- Load ALL matching catalog entries for this failure class ---
    catalog_entries = []
    executable_entries = []
    try:
        catalog = load_catalog()
        for entry in catalog:
            entry_classes = set()
            for cond in entry.allowed_when:
                parts = cond.split("==")
                if len(parts) == 2 and parts[0].strip() == "failure_class":
                    entry_classes.add(parts[1].strip())
            if failure_class in entry_classes:
                entry_info = {
                    "id": entry.id,
                    "mode": entry.mode.value,
                    "risk": entry.risk.value,
                    "execution_method": entry.execution_method,
                    "commands": [_sub(cmd) for cmd in entry.commands],
                    "forbidden_when": entry.forbidden_when,
                    "would_execute": entry.mode.value != "recommend_only",
                }
                catalog_entries.append(entry_info)
                if entry.mode.value != "recommend_only":
                    executable_entries.append(entry_info)
    except Exception:
        pass

    # Commands that would actually run (from executable catalog entries)
    commands_to_run = []
    for entry in executable_entries:
        commands_to_run.extend(entry["commands"])

    # --- Gate 0b: Risk check ---
    allowed_risk = "any"
    if mode == "low_risk_auto":
        allowed_risk = "low"
    elif mode == "full_auto":
        allowed_risk = "medium"

    from engine.models import RemediationRisk
    RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    max_risk_val = RISK_ORDER.get(allowed_risk, 999)
    risk_filtered = [e for e in executable_entries if RISK_ORDER.get(e["risk"], 0) <= max_risk_val]
    risk_ok = mode == "recommend_only" or len(risk_filtered) > 0

    # --- Gate 0c: Rate limit ---
    rate_limited = False
    max_per_hour = 5
    actions_this_hour = 0
    try:
        from db import repository as repo
        config = repo.get_lab_remediation_config(db, lab_code)
        max_per_hour = config.max_actions_per_hour if config else 5
        actions_this_hour = repo.count_recent_actions(db, lab_code, hours=1)
        rate_limited = actions_this_hour >= max_per_hour
    except Exception:
        pass

    # --- Gate 1: Dry-run ---
    dry_run = _dry_run_enabled

    # --- Gate 2: Confidence ---
    confidence = 1.0

    # --- Build gate summary ---
    gates = [
        {
            "gate": "Namespace Allowlist",
            "description": f"Is '{namespace}' in the remediation namespace allowlist?",
            "allowed_prefixes": [p.strip() for p in REMEDIATION_ALLOWED_PREFIXES if p.strip()],
            "passed": ns_allowed,
            "result": "PASS — namespace is in ecosystem" if ns_allowed else f"BLOCKED — '{namespace}' is not in the allowlist",
        },
        {
            "gate": "Ecosystem Check",
            "description": f"Is '{namespace}' an ecosystem namespace?",
            "passed": _is_ecosystem_ns(namespace),
            "result": "PASS — ecosystem namespace" if _is_ecosystem_ns(namespace) else "INFO — not an ecosystem namespace (monitoring only)",
        },
        {
            "gate": "Lab Execution Mode",
            "description": f"What is the execution mode for lab '{lab_code}'?",
            "mode": mode,
            "passed": mode != "recommend_only" or is_test,
            "result": f"{'PASS' if mode != 'recommend_only' or is_test else 'BLOCKED'} — mode is '{mode}'",
        },
        {
            "gate": "Risk Assessment",
            "description": f"Are catalog commands available at risk level <= {allowed_risk}?",
            "allowed_risk": allowed_risk,
            "catalog_entries_total": len(catalog_entries),
            "executable_entries": len(executable_entries),
            "passed": risk_ok,
            "result": f"{'PASS' if risk_ok else 'BLOCKED'} — {len(executable_entries)} executable entries, {len(risk_filtered)} at risk <= {allowed_risk}",
        },
        {
            "gate": "Rate Limit",
            "description": f"Has '{lab_code}' exceeded {max_per_hour} actions/hour?",
            "actions_this_hour": actions_this_hour,
            "max_per_hour": max_per_hour,
            "passed": not rate_limited,
            "result": f"{'PASS' if not rate_limited else 'BLOCKED'} — {actions_this_hour}/{max_per_hour} actions this hour",
        },
        {
            "gate": "Dry-Run Mode",
            "description": "Is the global dry-run flag enabled?",
            "passed": not dry_run,
            "result": f"{'PASS' if not dry_run else 'BLOCKED'} — dry-run is {'OFF' if not dry_run else 'ON'}",
        },
        {
            "gate": "Confidence Threshold",
            "description": f"Is confidence ({confidence}) >= threshold ({CONFIDENCE_THRESHOLD})?",
            "confidence": confidence,
            "threshold": CONFIDENCE_THRESHOLD,
            "passed": confidence >= CONFIDENCE_THRESHOLD,
            "result": f"{'PASS' if confidence >= CONFIDENCE_THRESHOLD else 'QUEUED'} — confidence {confidence} vs threshold {CONFIDENCE_THRESHOLD}",
        },
    ]

    all_passed = all(g["passed"] for g in gates)
    first_block = next((g for g in gates if not g["passed"]), None)

    return {
        "namespace": namespace,
        "failure_class": failure_class,
        "cluster": cluster,
        "action_type": action_type,
        "lab_code": lab_code,
        "execution_target": EXECUTION_TARGET,
        "would_execute": all_passed,
        "blocked_by": first_block["gate"] if first_block else None,
        "gates": gates,
        "catalog_entries": catalog_entries,
        "commands_to_run": commands_to_run,
    }


@router.post("/admin/remediation/execute", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
def execute_remediation(request: Request, body: "RemediationExecuteRequest", db: Session = Depends(get_db)):
    """Manually trigger remediation for a specific namespace + failure class.

    This is the human-in-the-loop "Remediate Now" button — not auto-execution.
    Requires explicit operator action. Logs everything to audit trail.
    """
    from api.schemas import RemediationExecuteRequest  # noqa: F811
    from api.action_executor import execute_action
    from engine.catalog_loader import ACTION_TO_FAILURE_CLASSES

    namespace = body.namespace
    failure_class = body.failure_class
    cluster = body.cluster
    lab_code = body.lab_code or namespace

    action_type = body.action_type or ""
    if not action_type:
        for at, fcs in ACTION_TO_FAILURE_CLASSES.items():
            if failure_class in fcs:
                action_type = at
                break
        if not action_type:
            action_type = "cleanup_stuck"

    # Discover target pods/deployments for command substitution
    params: dict = {
        "failure_class": failure_class,
        "cluster": cluster,
        "triggered_by": "manual_ui",
    }
    try:
        from engine.rollback import _run_oc
        from api.routers._shared import EXECUTOR_KUBECONFIG
        if failure_class in ("pods_crashlooping", "pods_not_ready"):
            pod_output = _run_oc(["get", "pods", "-n", namespace, "--no-headers", "-o", "custom-columns=NAME:.metadata.name,STATUS:.status.phase"], EXECUTOR_KUBECONFIG, timeout=10)
            pods = [line.split()[0] for line in pod_output.strip().splitlines() if line.strip()]
            if pods:
                params["pod"] = pods[0]
                params["pods"] = pods[:3]
        if failure_class in ("readiness_probe_failed", "health_check_failed", "smoke_test_failed"):
            dep_output = _run_oc(["get", "deployments", "-n", namespace, "--no-headers", "-o", "custom-columns=NAME:.metadata.name"], EXECUTOR_KUBECONFIG, timeout=10)
            deps = [line.strip() for line in dep_output.strip().splitlines() if line.strip()]
            if deps:
                params["deployment"] = deps[0]
    except Exception:
        pass

    result = execute_action(
        action_type=action_type,
        target=namespace,
        parameters=params,
        confidence=1.0,
        db=db,
        lab_code=lab_code,
    )

    return {
        "namespace": namespace,
        "failure_class": failure_class,
        "cluster": cluster,
        **result,
    }


# ---------------------------------------------------------------------------
# Synthetic remediation proof system
# ---------------------------------------------------------------------------

@router.post("/admin/proof/run")
def run_proof(req: dict, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Start a proof cycle asynchronously. Returns immediately, poll /admin/proof/matrix for results."""
    import threading
    from engine.proof_orchestrator import run_proof_cycle
    from api.routers._shared import EXECUTOR_KUBECONFIG
    from engine.proof_tracker import ProofTracker

    failure_class = req.get("failure_class", "")
    mode = req.get("mode", "manual")

    if not failure_class:
        raise HTTPException(status_code=400, detail="failure_class is required")

    tracker = ProofTracker()
    tracker.record_injection(failure_class, {"status": "running", "message": "Proof cycle started"})

    def _run_in_background():
        try:
            from db.database import get_db as _get_db
            bg_db = next(_get_db())
            run_proof_cycle(failure_class=failure_class, kubeconfig=EXECUTOR_KUBECONFIG, mode=mode, db=bg_db)
            bg_db.close()
        except Exception as e:
            import logging
            logging.getLogger("stargate").error("Proof cycle failed: %s", e)
            tracker = ProofTracker()
            fc = tracker._get_fc(failure_class)
            fc["status"] = "FAILED"
            fc["history"].append({"event": "error", "error": str(e)})
            tracker._save()

    thread = threading.Thread(target=_run_in_background, daemon=True)
    thread.start()

    return {"status": "started", "failure_class": failure_class, "message": "Proof cycle running — poll the matrix for updates."}


@router.get("/admin/proof/matrix")
def get_proof_matrix(_auth=Depends(require_admin_read)):
    """Get the current proof matrix — all failure classes and their gate status."""
    from engine.proof_tracker import ProofTracker
    tracker = ProofTracker()
    return {
        "matrix": tracker.get_matrix(),
        "summary": tracker.get_summary(),
    }


@router.get("/admin/proof/explain/{failure_class}")
def explain_proof(failure_class: str, _auth=Depends(require_admin_read)):
    """LLM-generated explanation of why a proof cycle passed or failed."""
    from engine.proof_tracker import ProofTracker
    from engine.sub_classifier import get_sub_class_info
    import os, urllib.request

    tracker = ProofTracker()
    matrix = tracker.get_matrix()
    fc_data = matrix.get("failure_classes", {}).get(failure_class, {})

    if not fc_data:
        return {"explanation": "No proof data available for this failure class. Run a proof cycle first."}

    status = fc_data.get("status", "UNTESTED")
    cycles = fc_data.get("cycles_completed", 0)
    gate = fc_data.get("gate", "manual")
    last_cycle = fc_data.get("last_cycle", {})
    steps = last_cycle.get("steps", {})

    sub_info = get_sub_class_info(failure_class)

    verify_status = steps.get("verify", {}).get("status", "unknown")
    verify_cmds = steps.get("verify", {}).get("commands", [])
    remediate_cmds = steps.get("remediate", {}).get("commands", [])

    verify_output = ""
    for cmd in verify_cmds[-2:]:
        verify_output += f"{cmd.get('command','')}\n{cmd.get('output','')[:300]}\n"

    remediate_output = ""
    for cmd in remediate_cmds[-2:]:
        remediate_output += f"{cmd.get('command','')}\n{cmd.get('output','')[:200]}\n"

    prompt = f"""You are an SRE reviewing a remediation proof cycle result. Explain in 2-3 sentences what happened and what it means. Be specific and actionable.

Failure class: {failure_class}
Sub-class: {sub_info.get('sub_class', 'unknown')}
Workload type: {sub_info.get('workload', 'unknown')}
Proof status: {status}
Verify result: {verify_status}
Gate: {gate}
Cycles completed: {cycles}

Remediation action output:
{remediate_output[:400]}

Verification output:
{verify_output[:400]}

If the proof FAILED, explain why the catalog action didn't fix the root cause and what a better fix would be.
If it PASSED, explain what worked.
Keep it to 2-3 sentences max."""

    llm_url = os.environ.get("STARGATE_LLM_URL", "")
    model = os.environ.get("STARGATE_LLM_MODEL", "llama-scout-17b")
    api_key = os.environ.get("STARGATE_LLM_API_KEY", "")

    verify_failed = verify_status in ("failed", "error") or any(
        "ErrImagePull" in str(c.get("output", "")) or "CrashLoopBackOff" in str(c.get("output", ""))
        or "BackOff" in str(c.get("output", "")) or "Error" in str(c.get("output", ""))
        for c in verify_cmds
    )

    if not llm_url:
        if verify_failed or status == "FAILED":
            return {"explanation": f"The catalog action for {failure_class} was executed but verification shows the failure persisted — the prescribed fix doesn't address the root cause. The verify output still shows the original error state. A different remediation strategy is needed for this failure class."}
        return {"explanation": f"The catalog action for {failure_class} was executed and verification confirmed the failure was resolved. The namespace returned to a healthy state after remediation."}

    try:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 200,
            "temperature": 0.2,
        }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        req_obj = urllib.request.Request(
            f"{llm_url}/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers=headers,
        )
        resp = urllib.request.urlopen(req_obj, timeout=15)
        result = json.loads(resp.read().decode())
        explanation = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        return {"explanation": explanation, "model": model}
    except Exception as e:
        if verify_failed or status == "FAILED":
            return {"explanation": f"The catalog action for {failure_class} was executed but verification shows the failure persisted — the prescribed fix doesn't address the root cause. A different remediation strategy is needed."}
        return {"explanation": f"The catalog action for {failure_class} was executed and verification confirmed the failure was resolved."}


@router.post("/admin/proof/continue")
def continue_proof(req: dict, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Phase 2: remediate → verify → cleanup after HITL approval."""
    from engine.proof_orchestrator import continue_proof_cycle
    from api.routers._shared import EXECUTOR_KUBECONFIG

    failure_class = req.get("failure_class", "")
    if not failure_class:
        raise HTTPException(status_code=400, detail="failure_class is required")

    result = continue_proof_cycle(
        failure_class=failure_class,
        kubeconfig=EXECUTOR_KUBECONFIG,
        db=db,
    )
    return result


@router.get("/admin/proof/history/{failure_class}")
def get_proof_history(failure_class: str, _auth=Depends(require_admin_read)):
    """Get full cycle history with command-level detail for a specific failure class."""
    from engine.proof_tracker import ProofTracker
    from fastapi import HTTPException
    tracker = ProofTracker()
    matrix = tracker.get_matrix()
    fc_data = matrix.get("failure_classes", {}).get(failure_class)
    if not fc_data:
        raise HTTPException(status_code=404, detail=f"No proof data for {failure_class}")
    return fc_data


@router.get("/admin/pipeline/matrix")
def get_pipeline_matrix(_auth=Depends(require_admin_read)):
    """Get the cross-system proof pipeline rubric matrix.

    Tracks each failure class through detect→hypothesize→classify→recommend→prove→trust
    across Deepfield, GeoLux, and StarGate with TDD/EDD/CDD/BDD at each stage.
    """
    from engine.pipeline_rubric import PipelineRubricTracker
    tracker = PipelineRubricTracker()
    return {
        "matrix": tracker.get_matrix(),
        "overview": tracker.get_overview(),
    }


@router.get("/admin/pipeline/summary/{failure_class}")
def get_pipeline_summary(failure_class: str, _auth=Depends(require_admin_read)):
    """Get pipeline rubric summary for a specific failure class."""
    from engine.pipeline_rubric import PipelineRubricTracker
    tracker = PipelineRubricTracker()
    return tracker.get_fc_summary(failure_class)


@router.post("/admin/pipeline/evaluate")
def evaluate_pipeline_stage(req: dict, _auth=Depends(require_admin)):
    """Record a stage evaluation in the pipeline rubric matrix."""
    from engine.pipeline_rubric import PipelineRubricTracker
    tracker = PipelineRubricTracker()
    tracker.record_stage(
        failure_class=req.get("failure_class", ""),
        stage=req.get("stage", ""),
        system=req.get("system", ""),
        dimensions=req.get("dimensions", {}),
        evidence=req.get("evidence"),
    )
    return {"status": "recorded"}


@router.get("/admin/mining/patterns")
def get_mining_patterns(db: Session = Depends(get_db), _auth=Depends(require_admin_read)):
    """Mine historical failure patterns from the evaluation database.

    Uses aggregation queries only — no full record loads.
    Results cached for 6 hours to avoid re-mining.
    """
    from engine.historical_miner import mine_and_cache
    return mine_and_cache(db)


@router.post("/admin/mining/feed-geolux")
def feed_mining_to_geolux(req: dict = None, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Feed top mined patterns to GeoLux as evidence for hypothesis generation."""
    from engine.historical_miner import mine_and_cache, feed_patterns_to_geolux
    max_feed = (req or {}).get("max_feed", 5)
    patterns = mine_and_cache(db)
    results = feed_patterns_to_geolux(patterns, max_feed=max_feed)
    return {"fed": len(results), "results": results}


@router.post("/admin/shadow/run")
def run_shadow_cycle(db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Run one shadow mode cycle — feed recent failures to GeoLux, track resolution."""
    from engine.historical_miner import run_shadow_cycle as _run_shadow
    return _run_shadow(db)


@router.get("/admin/shadow/status")
def get_shadow_status(_auth=Depends(require_admin_read)):
    """Get shadow mode status and recent log."""
    from engine.historical_miner import SHADOW_STATE_FILE
    if not SHADOW_STATE_FILE.exists():
        return {"status": "not_started", "shadow_log": []}
    try:
        import json
        state = json.loads(SHADOW_STATE_FILE.read_text())
        log = state.get("shadow_log", [])
        resolved = sum(1 for e in log if e.get("resolved"))
        unresolved = sum(1 for e in log if e.get("resolved") is False or e.get("resolved") is None)
        return {
            "status": "running" if state.get("last_run") else "not_started",
            "last_run": state.get("last_run"),
            "last_processed_id": state.get("last_processed_id", 0),
            "total_entries": len(log),
            "resolved": resolved,
            "unresolved": unresolved,
            "recent": log[-10:],
        }
    except Exception:
        return {"status": "error"}


@router.get("/admin/shadow/incidents")
def get_shadow_incidents(_auth=Depends(require_admin_read)):
    """Get Deepfield incident resolution tracking."""
    from engine.historical_miner import SHADOW_STATE_FILE
    if not SHADOW_STATE_FILE.exists():
        return {"status": "not_started", "incident_log": []}
    try:
        import json
        state = json.loads(SHADOW_STATE_FILE.read_text())
        log = state.get("incident_log", [])
        resolved = sum(1 for e in log if e.get("resolved"))
        with_rca = sum(1 for e in log if e.get("has_rca"))
        return {
            "total": len(log),
            "resolved": resolved,
            "unresolved": len(log) - resolved,
            "with_rca": with_rca,
            "incidents": log[-20:],
        }
    except Exception:
        return {"status": "error"}


@router.get("/admin/resolution/profiles")
def get_resolution_profiles(_auth=Depends(require_admin_read)):
    """Get resolution profiles from shadow mode data."""
    from engine.resolution_classifier import build_resolution_profiles
    return build_resolution_profiles()


@router.get("/admin/monitoring-gaps")
def detect_monitoring_gaps(db: Session = Depends(get_db), _auth=Depends(require_admin_read)):
    """Run all monitoring gap detectors — stuck teardowns, resource leaks, operator health."""
    from api.routers._shared import EXECUTOR_KUBECONFIG
    from collectors.cleanup.collect_stuck_teardowns import detect_stuck_teardowns
    from collectors.cleanup.collect_leaks import detect_resource_leaks
    from collectors.cleanup.collect_operator_health import detect_operator_issues

    results = {}

    try:
        results["stuck_teardowns"] = detect_stuck_teardowns(kubeconfig=EXECUTOR_KUBECONFIG)
    except Exception as e:
        results["stuck_teardowns"] = {"error": str(e)}

    try:
        results["resource_leaks"] = detect_resource_leaks(kubeconfig=EXECUTOR_KUBECONFIG)
    except Exception as e:
        results["resource_leaks"] = {"error": str(e)}

    try:
        results["operator_health"] = detect_operator_issues(kubeconfig=EXECUTOR_KUBECONFIG)
    except Exception as e:
        results["operator_health"] = {"error": str(e)}

    return results


@router.get("/admin/provision-readiness-mismatches")
def get_provision_readiness_mismatches(
    hours: int = 24,
    db: Session = Depends(get_db),
    _auth=Depends(require_admin_read),
):
    """Find namespaces where provisioning succeeded but readiness failed.

    Correlates evaluations: namespaces with readiness failures (non-AAP stages)
    but no AAP provisioning failures in the same time window — meaning AAP
    reported success but the sandbox still broke.
    """
    from db.models import EvaluationRecord
    from sqlalchemy import func
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    # Namespaces with readiness failures (non-AAP stages)
    failing_ns = (
        db.query(
            EvaluationRecord.lab_code,
            EvaluationRecord.cluster_name,
            func.count(EvaluationRecord.id).label("failure_count"),
            func.max(EvaluationRecord.evaluated_at).label("last_failure"),
        )
        .filter(
            EvaluationRecord.evaluated_at >= cutoff,
            EvaluationRecord.outcome == "fail",
            EvaluationRecord.stage_id != "aap-provisioning",
            EvaluationRecord.lab_code.isnot(None),
            EvaluationRecord.lab_code != "",
            EvaluationRecord.lab_code.like("sandbox-%"),
        )
        .group_by(EvaluationRecord.lab_code, EvaluationRecord.cluster_name)
        .all()
    )

    # Namespaces with AAP provisioning failures in the same window
    aap_failed_ns = set(
        row[0] for row in
        db.query(EvaluationRecord.lab_code)
        .filter(
            EvaluationRecord.evaluated_at >= cutoff,
            EvaluationRecord.stage_id == "aap-provisioning",
            EvaluationRecord.outcome == "fail",
        )
        .distinct()
        .all()
    )

    # Collect distinct failure classes per namespace
    mismatch_ns = {row.lab_code for row in failing_ns if row.lab_code not in aap_failed_ns}
    fc_rows = (
        db.query(EvaluationRecord.lab_code, EvaluationRecord.failure_class)
        .filter(
            EvaluationRecord.evaluated_at >= cutoff,
            EvaluationRecord.outcome == "fail",
            EvaluationRecord.lab_code.in_(mismatch_ns),
            EvaluationRecord.failure_class.isnot(None),
        )
        .distinct()
        .all()
    ) if mismatch_ns else []

    fc_by_ns: dict = {}
    for r in fc_rows:
        fc_by_ns.setdefault(r.lab_code, []).append(r.failure_class)

    mismatches = []
    for row in failing_ns:
        if row.lab_code in aap_failed_ns:
            continue
        mismatches.append({
            "namespace": row.lab_code,
            "cluster": row.cluster_name or "",
            "failure_count": row.failure_count,
            "last_failure": row.last_failure.isoformat() if row.last_failure else None,
            "failure_classes": fc_by_ns.get(row.lab_code, []),
        })

    mismatches.sort(key=lambda x: x["failure_count"], reverse=True)

    return {
        "hours": hours,
        "total_mismatches": len(mismatches),
        "total_with_aap_failures": len(aap_failed_ns),
        "mismatches": mismatches[:50],
    }


@router.get("/admin/correlated-view")
def get_correlated_view(cluster: str = None, limit: int = 20, db: Session = Depends(get_db), _auth=Depends(require_admin_read)):
    """Cross-correlated view — failures enriched with Deepfield RCA, shadow status, proof status."""
    from db.models import PendingAction, EvaluationRecord
    from sqlalchemy import func
    from datetime import timedelta
    from engine.proof_tracker import ProofTracker
    from engine.historical_miner import SHADOW_STATE_FILE

    # Get recent failures (same as recommendations endpoint)
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    # Aggregate failures by namespace + failure_class (lab namespaces only, exclude warnings)
    from api.constants import WARNING_CLASSES as _CORR_WARN
    from sqlalchemy import or_ as _or
    _CORR_LAB_PREFIXES = ("sandbox-", "showroom-", "user-", "ocp4-cluster-")
    _corr_lab_filter = _or(*[EvaluationRecord.lab_code.like(f"{p}%") for p in _CORR_LAB_PREFIXES])
    failures = db.query(
        EvaluationRecord.lab_code,
        EvaluationRecord.cluster_name,
        EvaluationRecord.failure_class,
        func.count().label('count'),
        func.max(EvaluationRecord.evaluated_at).label('last_seen'),
    ).filter(
        EvaluationRecord.outcome == 'fail',
        EvaluationRecord.failure_class.isnot(None),
        EvaluationRecord.failure_class.notin_(_CORR_WARN),
        EvaluationRecord.evaluated_at > one_hour_ago,
        _corr_lab_filter,
    )
    if cluster:
        failures = failures.filter(EvaluationRecord.cluster_name == cluster)

    failures = failures.group_by(
        EvaluationRecord.lab_code,
        EvaluationRecord.cluster_name,
        EvaluationRecord.failure_class,
    ).order_by(func.count().desc()).limit(limit).all()

    # Load Deepfield incidents for matching
    deepfield_incidents = db.query(PendingAction).filter(
        PendingAction.proposed_by == 'deepfield',
    ).all()
    # Index by namespace for fast lookup
    incidents_by_ns = {}
    for inc in deepfield_incidents:
        ns = inc.target
        if ns not in incidents_by_ns:
            incidents_by_ns[ns] = []
        incidents_by_ns[ns].append(inc)

    # Load proof status
    proof_tracker = ProofTracker()
    proof_data = proof_tracker.get_matrix().get('failure_classes', {})

    # Load shadow data
    shadow_data = {}
    if SHADOW_STATE_FILE.exists():
        try:
            state = json.loads(SHADOW_STATE_FILE.read_text())
            for entry in state.get('shadow_log', []):
                key = f"{entry.get('namespace')}:{entry.get('failure_class')}"
                shadow_data[key] = entry
            for entry in state.get('incident_log', []):
                key = f"{entry.get('namespace')}:{entry.get('failure_class')}"
                shadow_data[key] = entry
        except Exception:
            pass

    # Build correlated results
    results = []
    for lab_code, cluster_name, failure_class, count, last_seen in failures:
        entry = {
            "namespace": lab_code,
            "cluster": cluster_name,
            "failure_class": failure_class,
            "count": count,
            "last_seen": last_seen.isoformat() if last_seen else None,
        }

        # Match Deepfield incident
        matching_incidents = incidents_by_ns.get(lab_code, [])
        # Find best match by failure_class
        incident_match = None
        for inc in matching_incidents:
            inc_fc = (inc.parameters or {}).get('failure_class', '')
            if inc_fc and failure_class and inc_fc in failure_class:
                incident_match = inc
                break
        if not incident_match and matching_incidents:
            incident_match = matching_incidents[0]  # fallback to any incident on this namespace

        if incident_match:
            params = incident_match.parameters or {}
            entry["deepfield"] = {
                "status": incident_match.status,
                "confidence": incident_match.confidence,
                "has_rca": bool(params.get('rca_output')),
                "signal_count": params.get('signal_count', 0),
                "severity": params.get('severity'),
                "action_type": incident_match.action_type,
                "proposed_at": incident_match.proposed_at.isoformat() if incident_match.proposed_at else None,
            }
        else:
            entry["deepfield"] = None

        # Proof status for this failure class
        proof_fc = proof_data.get(failure_class, {})
        if proof_fc:
            entry["proof"] = {
                "status": proof_fc.get('status', 'UNTESTED'),
                "cycles": proof_fc.get('cycles_completed', 0),
                "gate": proof_fc.get('gate', 'manual'),
            }
        else:
            entry["proof"] = {"status": "UNTESTED", "cycles": 0, "gate": "manual"}

        # Shadow tracking
        shadow_key = f"{lab_code}:{failure_class}"
        shadow_entry = shadow_data.get(shadow_key)
        if shadow_entry:
            entry["shadow"] = {
                "tracked": True,
                "resolved": shadow_entry.get('resolved'),
                "resolution_cause": shadow_entry.get('resolution_cause', {}).get('cause') if isinstance(shadow_entry.get('resolution_cause'), dict) else None,
            }
        else:
            entry["shadow"] = {"tracked": False}

        results.append(entry)

    return {
        "total": len(results),
        "correlated": results,
    }


@router.get("/admin/namespace-detail/{namespace}")
def namespace_detail(namespace: str, db: Session = Depends(get_db), _auth=Depends(require_admin_read)):
    """Per-namespace detail — issues, incidents, shadow status for drawer view."""
    from db.models import EvaluationRecord, PendingAction
    from sqlalchemy import func
    from api.constants import WARNING_CLASSES

    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    # Issues: recent failure classes + sub_classes for this namespace
    issue_rows = db.query(
        EvaluationRecord.failure_class,
        EvaluationRecord.sub_class,
        EvaluationRecord.cluster_name,
        func.count().label("count"),
        func.max(EvaluationRecord.evaluated_at).label("last_seen"),
        func.max(EvaluationRecord.message).label("sample_message"),
    ).filter(
        EvaluationRecord.lab_code == namespace,
        EvaluationRecord.outcome == "fail",
        EvaluationRecord.failure_class.isnot(None),
        EvaluationRecord.evaluated_at > one_hour_ago,
    ).group_by(
        EvaluationRecord.failure_class, EvaluationRecord.sub_class, EvaluationRecord.cluster_name,
    ).order_by(func.count().desc()).all()

    from engine.sub_classifier import get_sub_class_info
    issues = []
    for fc, sub, cluster, count, last_seen, msg in issue_rows:
        sub_info = get_sub_class_info(sub) if sub else {}
        issues.append({
            "failure_class": fc,
            "sub_class": sub,
            "workload": sub_info.get("workload"),
            "auto_fix_confidence": sub_info.get("auto_fix_confidence"),
            "cluster": cluster,
            "count": count,
            "severity": "warning" if fc in WARNING_CLASSES else "high",
            "last_seen": last_seen.isoformat() if last_seen else None,
            "message": (msg or "")[:200],
        })

    # Incidents: Deepfield incidents for this namespace
    incidents = db.query(PendingAction).filter(
        PendingAction.target == namespace,
    ).order_by(PendingAction.id.desc()).limit(10).all()

    incident_list = []
    for inc in incidents:
        params = inc.parameters or {}
        rca = params.get("rca_output", "")
        if isinstance(rca, str) and rca.startswith("{"):
            try:
                rca = json.loads(rca.strip().strip("`").strip())
            except Exception:
                pass
        incident_list.append({
            "id": inc.id,
            "action_type": inc.action_type,
            "status": inc.status,
            "confidence": inc.confidence,
            "proposed_by": getattr(inc, "proposed_by", None) or "stargate",
            "proposed_at": inc.proposed_at.isoformat() if inc.proposed_at else None,
            "failure_class": params.get("failure_class"),
            "severity": params.get("severity"),
            "rca_summary": rca.get("root_cause", rca) if isinstance(rca, dict) else (rca[:200] if isinstance(rca, str) else None),
            "signal_count": params.get("signal_count", 0),
            "cluster": params.get("cluster"),
        })

    # Shadow status
    from engine.historical_miner import SHADOW_STATE_FILE
    shadow_entries = []
    if SHADOW_STATE_FILE.exists():
        try:
            state = json.loads(SHADOW_STATE_FILE.read_text())
            for entry in state.get("shadow_log", []) + state.get("incident_log", []):
                if entry.get("namespace") == namespace:
                    shadow_entries.append({
                        "failure_class": entry.get("failure_class"),
                        "tracked_at": entry.get("tracked_at"),
                        "resolved": entry.get("resolved"),
                        "resolution_cause": entry.get("resolution_cause", {}).get("cause") if isinstance(entry.get("resolution_cause"), dict) else None,
                    })
        except Exception:
            pass

    # Eval summary
    total_evals = db.query(func.count(EvaluationRecord.id)).filter(
        EvaluationRecord.lab_code == namespace,
        EvaluationRecord.evaluated_at > one_hour_ago,
    ).scalar()
    pass_evals = db.query(func.count(EvaluationRecord.id)).filter(
        EvaluationRecord.lab_code == namespace,
        EvaluationRecord.outcome == "pass",
        EvaluationRecord.evaluated_at > one_hour_ago,
    ).scalar()

    # Catalog commands for the top failure class
    catalog_commands = []
    top_fc = issues[0]["failure_class"] if issues else None
    if top_fc:
        import yaml as _yaml
        from pathlib import Path as _CatPath
        cat_path = _CatPath(__file__).parent.parent.parent / "remediations" / "catalog.yaml"
        if cat_path.exists():
            try:
                cat = _yaml.safe_load(cat_path.read_text()) or []
                for entry in cat:
                    for cond in entry.get("allowed_when", []):
                        if f"failure_class == {top_fc}" in cond:
                            catalog_commands = [
                                cmd.replace("{namespace}", namespace).replace("{ns}", namespace)
                                for cmd in entry.get("commands", [])
                            ]
                            break
                    if catalog_commands:
                        break
            except Exception:
                pass

    # Cluster from issues (for diagnostic command execution)
    cluster = issues[0]["cluster"] if issues else ""

    # Recent evaluation history
    eval_history = []
    recent_evals = db.query(
        EvaluationRecord.evaluated_at,
        EvaluationRecord.outcome,
        EvaluationRecord.failure_class,
        EvaluationRecord.sub_class,
        EvaluationRecord.message,
    ).filter(
        EvaluationRecord.lab_code == namespace,
        EvaluationRecord.evaluated_at > one_hour_ago,
    ).order_by(EvaluationRecord.evaluated_at.desc()).limit(15).all()

    for ev_at, outcome, fc, sub, msg in recent_evals:
        eval_history.append({
            "evaluated_at": ev_at.isoformat() if ev_at else None,
            "outcome": outcome,
            "failure_class": fc,
            "sub_class": sub,
            "message": (msg or "")[:150],
        })

    return {
        "namespace": namespace,
        "cluster": cluster,
        "total_evals": total_evals,
        "pass_evals": pass_evals,
        "health_pct": round(pass_evals / max(total_evals, 1) * 100, 1),
        "issues": issues,
        "catalog_commands": catalog_commands,
        "incidents": incident_list,
        "shadow": shadow_entries,
        "eval_history": eval_history,
    }


# ---------------------------------------------------------------------------
# Catalog Item Baselines (for needs-attention classification)
# ---------------------------------------------------------------------------

def _build_catalog_baselines(db, hours: int = 168) -> Dict:
    """Build per-catalog-item baseline failure profiles from evaluation history.

    Returns {catalog_item: {failure_class: {rate, p95_ttr_minutes, count}}}
    Used to distinguish 'expected noise' from 'needs attention'.
    """
    from db.models import EvaluationRecord
    from sqlalchemy import func
    import re as _re

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    rows = db.query(
        EvaluationRecord.lab_code,
        EvaluationRecord.outcome,
        EvaluationRecord.failure_class,
        func.count().label("cnt"),
    ).filter(
        EvaluationRecord.evaluated_at >= cutoff,
        EvaluationRecord.lab_code.isnot(None),
    ).group_by(
        EvaluationRecord.lab_code,
        EvaluationRecord.outcome,
        EvaluationRecord.failure_class,
    ).all()

    # Group by catalog item
    cat_data: Dict[str, Dict] = {}
    for lab_code, outcome, fc, cnt in rows:
        m = _re.match(r"^sandbox-[a-z0-9]{5}-(.+)$", lab_code)
        cat = m.group(1) if m else lab_code
        if cat not in cat_data:
            cat_data[cat] = {"total_evals": 0, "namespaces": set(), "failures": {}}
        cat_data[cat]["total_evals"] += cnt
        cat_data[cat]["namespaces"].add(lab_code)
        if outcome == "fail" and fc:
            cat_data[cat]["failures"].setdefault(fc, 0)
            cat_data[cat]["failures"][fc] += cnt

    # Build TTR baselines from resolution records
    ttr_by_cat: Dict[str, Dict[str, list]] = {}
    try:
        from db.models import ResolutionRecord
        res_rows = db.query(
            ResolutionRecord.lab_code,
            ResolutionRecord.failure_class,
            ResolutionRecord.ttr_seconds,
        ).filter(
            ResolutionRecord.resolved_at >= cutoff,
            ResolutionRecord.ttr_seconds.isnot(None),
            ResolutionRecord.ttr_seconds > 0,
        ).all()
        for lab_code, fc, ttr in res_rows:
            m = _re.match(r"^sandbox-[a-z0-9]{5}-(.+)$", lab_code)
            cat = m.group(1) if m else lab_code
            ttr_by_cat.setdefault(cat, {}).setdefault(fc, []).append(ttr / 60.0)
    except Exception:
        pass

    baselines: Dict[str, Dict] = {}
    for cat, d in cat_data.items():
        total = d["total_evals"]
        ns_count = len(d["namespaces"])
        fc_profiles = {}
        for fc, fail_cnt in d["failures"].items():
            rate = round(fail_cnt / max(total, 1), 3)
            ttr_list = sorted(ttr_by_cat.get(cat, {}).get(fc, []))
            p95 = ttr_list[int(len(ttr_list) * 0.95)] if len(ttr_list) > 1 else (ttr_list[0] if ttr_list else None)
            fc_profiles[fc] = {
                "rate": rate,
                "count": fail_cnt,
                "p95_ttr_minutes": round(p95, 1) if p95 else None,
            }
        baselines[cat] = {
            "namespace_count": ns_count,
            "total_evals": total,
            "failure_profiles": fc_profiles,
        }
    return baselines


def _classify_namespace(
    ns: str, catalog_item: str, failure_classes: Dict[str, int],
    first_eval_at: Optional[datetime], baselines: Dict,
) -> Dict:
    """Classify a failing namespace as: stuck, anomalous, provisioning, or expected.

    - provisioning: namespace < 20 min old, failures are common for this catalog item
    - stuck: failure duration exceeds P95 TTR for this catalog item + failure class
    - anomalous: failure class is unusual for this catalog item (< 5% baseline rate)
    - expected: normal churn — this failure class and rate are typical
    """
    now = datetime.now(timezone.utc)
    age_minutes = None
    if first_eval_at:
        first = first_eval_at.replace(tzinfo=timezone.utc) if first_eval_at.tzinfo is None else first_eval_at
        age_minutes = (now - first).total_seconds() / 60.0

    baseline = baselines.get(catalog_item, {})
    fc_profiles = baseline.get("failure_profiles", {})

    # Young namespace — likely still provisioning
    if age_minutes is not None and age_minutes < 20:
        return {"attention": "provisioning", "reason": f"namespace is {int(age_minutes)}m old"}

    top_fc = max(failure_classes, key=failure_classes.get) if failure_classes else None
    if not top_fc:
        return {"attention": "expected", "reason": "no classified failures"}

    profile = fc_profiles.get(top_fc, {})
    baseline_rate = profile.get("rate", 0)
    p95_ttr = profile.get("p95_ttr_minutes")

    # Stuck: failing longer than P95 TTR (with a floor of 30 min)
    if age_minutes is not None and p95_ttr:
        threshold = max(p95_ttr, 30)
        if age_minutes > threshold:
            return {
                "attention": "stuck",
                "reason": f"{top_fc} for {int(age_minutes)}m (P95 is {int(p95_ttr)}m)",
            }

    # Anomalous: failure class is rare for this catalog item
    if baseline_rate < 0.05 and baseline.get("total_evals", 0) > 50:
        return {
            "attention": "anomalous",
            "reason": f"{top_fc} is unusual for {catalog_item} ({baseline_rate*100:.0f}% baseline)",
        }

    # Stuck fallback: no TTR data but failing for > 60 min
    if age_minutes is not None and age_minutes > 60 and not p95_ttr:
        return {
            "attention": "stuck",
            "reason": f"{top_fc} for {int(age_minutes)}m (no baseline TTR)",
        }

    return {"attention": "expected", "reason": f"{top_fc} is normal for {catalog_item}"}


def _build_failure_class_view(
    by_namespace: list, baselines: Dict, ns_data: Dict, db,
) -> list:
    """Build a per-failure-class correlation view.

    For each failure class currently active, computes:
    - affected_namespaces: count and list of namespaces hit
    - affected_catalog_items: which lab types are affected
    - affected_clusters: which clusters are affected
    - stuck_count: how many of those namespaces are classified as stuck
    - baseline_rate: 7-day average rate across all catalog items
    - current_rate: current-hour rate (affected / total monitored)
    - attention: spiking (> 2x baseline), spreading (hitting unusual catalog items),
      concentrated (isolated to one catalog item), or normal
    """
    import re as _re

    # Aggregate current failure data by failure class
    fc_agg: Dict[str, Dict] = {}
    for entry in by_namespace:
        ns = entry["namespace"]
        cat = entry.get("catalog_item", "unknown")
        cluster = entry.get("cluster", "")
        d = ns_data.get(ns, {})
        att = entry.get("attention", "expected")

        for fc, cnt in d.get("failure_classes", {}).items():
            if fc not in fc_agg:
                fc_agg[fc] = {
                    "namespaces": [], "catalog_items": {}, "clusters": {},
                    "total_hits": 0, "stuck": 0, "anomalous": 0,
                }
            agg = fc_agg[fc]
            agg["namespaces"].append(ns)
            agg["total_hits"] += cnt
            agg["catalog_items"][cat] = agg["catalog_items"].get(cat, 0) + 1
            agg["clusters"][cluster] = agg["clusters"].get(cluster, 0) + 1
            if att == "stuck":
                agg["stuck"] += 1
            elif att == "anomalous":
                agg["anomalous"] += 1

    # Compute baseline rate across all catalog items for each failure class
    fc_baseline_rates: Dict[str, float] = {}
    total_baseline_evals = sum(b.get("total_evals", 0) for b in baselines.values())
    for cat, bl in baselines.items():
        for fc, profile in bl.get("failure_profiles", {}).items():
            fc_baseline_rates[fc] = fc_baseline_rates.get(fc, 0) + profile.get("count", 0)
    for fc in fc_baseline_rates:
        fc_baseline_rates[fc] = fc_baseline_rates[fc] / max(total_baseline_evals, 1)

    # Compute baseline catalog items per failure class (which catalog items normally see this failure)
    fc_baseline_cats: Dict[str, set] = {}
    for cat, bl in baselines.items():
        for fc, profile in bl.get("failure_profiles", {}).items():
            if profile.get("rate", 0) >= 0.05:
                fc_baseline_cats.setdefault(fc, set()).add(cat)

    # Get resolution data per failure class
    fc_resolutions: Dict[str, Dict] = {}
    try:
        from db.models import ResolutionRecord
        from sqlalchemy import func
        twenty_four_h_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        res_rows = db.query(
            ResolutionRecord.failure_class,
            ResolutionRecord.resolution_type,
            func.count().label("cnt"),
        ).filter(
            ResolutionRecord.resolved_at >= twenty_four_h_ago,
        ).group_by(
            ResolutionRecord.failure_class,
            ResolutionRecord.resolution_type,
        ).all()
        for fc, res_type, cnt in res_rows:
            fc_resolutions.setdefault(fc, {})
            fc_resolutions[fc][res_type] = cnt
    except Exception:
        pass

    total_monitored = len(ns_data)
    result = []

    for fc, agg in sorted(fc_agg.items(), key=lambda x: x[1]["stuck"] + x[1]["anomalous"], reverse=True):
        ns_count = len(agg["namespaces"])
        current_rate = ns_count / max(total_monitored, 1)
        baseline_rate = fc_baseline_rates.get(fc, 0)
        cats_affected = agg["catalog_items"]
        cats_baseline = fc_baseline_cats.get(fc, set())

        # Classify
        new_cats = set(cats_affected.keys()) - cats_baseline
        if baseline_rate > 0 and current_rate > baseline_rate * 2 and ns_count >= 3:
            attention = "spiking"
            reason = f"{current_rate*100:.0f}% of namespaces vs {baseline_rate*100:.1f}% baseline ({current_rate/baseline_rate:.1f}x)"
        elif new_cats and len(cats_baseline) > 0:
            attention = "spreading"
            reason = f"now hitting {', '.join(sorted(new_cats))} (not in baseline)"
        elif len(cats_affected) == 1 and ns_count >= 3:
            attention = "concentrated"
            cat_name = list(cats_affected.keys())[0]
            reason = f"isolated to {cat_name} ({ns_count} namespaces)"
        elif agg["stuck"] > 0:
            attention = "stuck"
            reason = f"{agg['stuck']} namespace{'s' if agg['stuck'] != 1 else ''} stuck"
        else:
            attention = "normal"
            reason = f"within baseline ({current_rate*100:.0f}% vs {baseline_rate*100:.1f}%)"

        # Resolution profile for this failure class
        resolutions = fc_resolutions.get(fc, {})
        total_resolved = sum(resolutions.values())
        self_resolve_pct = round(resolutions.get("self_resolved", 0) / max(total_resolved, 1) * 100) if total_resolved else None

        result.append({
            "failure_class": fc,
            "affected_namespaces": ns_count,
            "affected_catalog_items": sorted([
                {"catalog_item": cat, "count": cnt}
                for cat, cnt in cats_affected.items()
            ], key=lambda x: -x["count"]),
            "affected_clusters": sorted([
                {"cluster": c, "count": cnt}
                for c, cnt in agg["clusters"].items()
            ], key=lambda x: -x["count"]),
            "total_hits": agg["total_hits"],
            "stuck_count": agg["stuck"],
            "anomalous_count": agg["anomalous"],
            "current_rate": round(current_rate, 4),
            "baseline_rate": round(baseline_rate, 4),
            "attention": attention,
            "attention_reason": reason,
            "resolutions_24h": resolutions if resolutions else None,
            "self_resolve_pct": self_resolve_pct,
        })

    result.sort(key=lambda x: (
        0 if x["attention"] == "spiking" else 1 if x["attention"] == "spreading" else
        2 if x["attention"] == "stuck" else 3 if x["attention"] == "concentrated" else 4,
        -x["affected_namespaces"],
    ))

    return result


# ---------------------------------------------------------------------------
# Lifecycle Matrix
# ---------------------------------------------------------------------------

@router.get("/admin/lifecycle-matrix")
def lifecycle_matrix(db: Session = Depends(get_db), _auth=Depends(require_admin_read)):
    """Namespace lifecycle matrix built from scanner evaluation records.

    Groups namespaces by health status using actual evaluation data.
    Returns three views: by_namespace, by_lab (demo_id grouping), by_cluster.
    """
    from db.models import EvaluationRecord
    from sqlalchemy import func, or_

    STAGES = ["health", "pods", "storage", "network", "workload", "overall"]

    # Failure classes mapped to lifecycle stages
    STAGE_MAP = {
        "pods_crashlooping": "pods", "readiness_probe_failed": "pods",
        "oom_killed": "pods", "pod_pending": "pods", "backoff_limit_exceeded": "pods",
        "image_pull_backoff": "pods", "image_pull_secret_missing": "pods",
        "claim_misbound": "storage", "volume_attach_failed": "storage",
        "volume_mount_failed": "storage", "pvc_binding_failed": "storage",
        "resource_leak_pv": "storage",
        "scheduling_failed": "workload", "quota_exceeded": "workload",
        "invalid_configuration": "workload", "hpa_max_replicas": "workload",
        "resolution_failed": "workload", "sync_failed": "workload",
        "datasource_unrecognized": "workload",
        "dns_resolution_failed": "network", "route_not_admitted": "network",
        "certificate_error": "network",
        "node_pressure": "health", "operator_unhealthy": "health",
        "operator_degraded": "health", "teardown_stuck": "health",
        "health_check_failed": "health", "deprecated_api": "health",
        "vm_migration_backoff": "workload",
        "guest_agent_not_connected": "workload",
    }

    # Low-severity classes excluded from overall health calculation
    from api.constants import WARNING_CLASSES

    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    # All recent evaluations grouped by namespace + cluster (lab namespaces only)
    LAB_PREFIXES = ("sandbox-", "showroom-", "user-", "ocp4-cluster-")
    _lab_filter = or_(*[EvaluationRecord.lab_code.like(f"{p}%") for p in LAB_PREFIXES])
    rows = db.query(
        EvaluationRecord.lab_code,
        EvaluationRecord.cluster_name,
        EvaluationRecord.outcome,
        EvaluationRecord.failure_class,
        func.count().label("cnt"),
    ).filter(
        EvaluationRecord.evaluated_at > one_hour_ago,
        EvaluationRecord.lab_code.isnot(None),
        _lab_filter,
    ).group_by(
        EvaluationRecord.lab_code,
        EvaluationRecord.cluster_name,
        EvaluationRecord.outcome,
        EvaluationRecord.failure_class,
    ).all()

    # Build per-namespace data
    ns_data: Dict[str, Dict] = {}
    for lab_code, cluster, outcome, fc, cnt in rows:
        if lab_code not in ns_data:
            ns_data[lab_code] = {
                "cluster": cluster or "", "pass": 0, "fail": 0, "real_fail": 0, "total": 0,
                "failure_classes": {}, "stage_failures": {s: 0 for s in STAGES},
            }
        d = ns_data[lab_code]
        d["total"] += cnt
        if outcome == "pass":
            d["pass"] += cnt
        elif outcome == "fail":
            d["fail"] += cnt
            is_warning = fc in WARNING_CLASSES if fc else False
            if not is_warning:
                d["real_fail"] += cnt
            if fc and not is_warning:
                d["failure_classes"][fc] = d["failure_classes"].get(fc, 0) + cnt
                stage = STAGE_MAP.get(fc, "workload")
                d["stage_failures"][stage] = d["stage_failures"].get(stage, 0) + cnt

    # Build catalog item baselines and first-eval timestamps for classification
    baselines = _build_catalog_baselines(db)

    # Build catalog item slug -> display name map from Labagator
    catalog_display_names: Dict[str, str] = {}
    try:
        import urllib.request as _urlreq
        _lab_url = os.environ.get("STARGATE_LABAGATOR_URL", "")
        if _lab_url:
            with _urlreq.urlopen(f"{_lab_url}/labs?limit=300", timeout=5) as _resp:
                _labs = json.loads(_resp.read())
                for _lab in (_labs if isinstance(_labs, list) else []):
                    _ci = _lab.get("ci_name", "")
                    _title = _lab.get("title", "")
                    if _ci and _title:
                        _slug = _ci.split(".", 1)[1] if "." in _ci else _ci
                        if _slug not in catalog_display_names:
                            catalog_display_names[_slug] = _title
    except Exception:
        pass

    first_eval_map: Dict[str, datetime] = {}
    try:
        first_evals = db.query(
            EvaluationRecord.lab_code,
            func.min(EvaluationRecord.evaluated_at).label("first_at"),
        ).filter(
            EvaluationRecord.lab_code.in_(list(ns_data.keys())),
        ).group_by(EvaluationRecord.lab_code).all()
        for lab_code, first_at in first_evals:
            first_eval_map[lab_code] = first_at
    except Exception:
        pass

    # Build namespace rows — only namespaces with real failures (green ones are noise)
    by_namespace = []
    all_ns_stages = []
    for ns, d in sorted(ns_data.items(), key=lambda x: x[1]["real_fail"], reverse=True):
        effective_total = d["pass"] + d["real_fail"]
        health_pct = round(d["pass"] / max(effective_total, 1) * 100, 1)
        stages = {}
        for s in STAGES:
            if s == "overall":
                continue
            fc_count = d["stage_failures"].get(s, 0)
            if fc_count == 0:
                stages[s] = {"status": "green", "detail": "no failures"}
            else:
                fcs = [fc for fc, _ in d["failure_classes"].items() if STAGE_MAP.get(fc) == s]
                stages[s] = {"status": "red", "detail": f"{fc_count} ({', '.join(fcs[:2])})"}

        stage_statuses = [v["status"] for k, v in stages.items()]
        red_count = stage_statuses.count("red")
        if red_count == 0:
            stages["overall"] = {"status": "green", "detail": "all clear"}
        elif red_count == 1:
            stages["overall"] = {"status": "yellow", "detail": f"1 category failing"}
        else:
            stages["overall"] = {"status": "red", "detail": f"{red_count} categories failing"}

        all_ns_stages.append(stages)

        if d["real_fail"] == 0:
            continue

        top_fc = max(d["failure_classes"], key=d["failure_classes"].get) if d["failure_classes"] else None

        # Extract catalog item name from sandbox namespace
        import re as _re
        m = _re.match(r"^sandbox-[a-z0-9]{5}-(.+)$", ns)
        catalog_item = m.group(1) if m else ns

        classification = _classify_namespace(
            ns, catalog_item, d["failure_classes"],
            first_eval_map.get(ns), baselines,
        )

        by_namespace.append({
            "namespace": ns,
            "cluster": d["cluster"],
            "catalog_item": catalog_item,
            "lab_name": catalog_display_names.get(catalog_item, catalog_item),
            "pass": d["pass"],
            "fail": d["fail"],
            "total": d["total"],
            "health_pct": health_pct,
            "top_failure": top_fc,
            "attention": classification["attention"],
            "attention_reason": classification["reason"],
            "stages": stages,
        })

    # Sort by attention: stuck > anomalous > provisioning > expected
    ATTENTION_ORDER = {"stuck": 0, "anomalous": 1, "provisioning": 2, "expected": 3}
    by_namespace.sort(key=lambda r: (ATTENTION_ORDER.get(r.get("attention", "expected"), 3), -r["fail"]))

    # Build lab grouping (by demo_id prefix)
    lab_map: Dict[str, Dict] = {}
    for entry in by_namespace:
        ns = entry["namespace"]
        parts = ns.split("-")
        lab_key = "-".join(parts[:2]) if len(parts) >= 2 else ns
        if lab_key not in lab_map:
            lab_map[lab_key] = {"namespaces": 0, "pass": 0, "fail": 0, "total": 0,
                                "clusters": set(), "stage_failures": {s: 0 for s in STAGES},
                                "failure_classes": {}}
        m = lab_map[lab_key]
        m["namespaces"] += 1
        m["pass"] += entry["pass"]
        m["fail"] += entry["fail"]
        m["total"] += entry["total"]
        m["clusters"].add(entry["cluster"])
        for fc, cnt in ns_data[ns]["failure_classes"].items():
            m["failure_classes"][fc] = m["failure_classes"].get(fc, 0) + cnt
            stage = STAGE_MAP.get(fc, "workload")
            m["stage_failures"][stage] += cnt

    by_lab = []
    for lab, m in sorted(lab_map.items(), key=lambda x: x[1]["fail"], reverse=True):
        stages = {}
        for s in STAGES:
            if s == "overall":
                continue
            fc_count = m["stage_failures"].get(s, 0)
            if fc_count == 0:
                stages[s] = {"status": "green", "detail": "ok"}
            else:
                stages[s] = {"status": "red", "detail": str(fc_count)}
        red_count = sum(1 for v in stages.values() if v["status"] == "red")
        if red_count == 0:
            stages["overall"] = {"status": "green", "detail": "all clear"}
        elif red_count == 1:
            stages["overall"] = {"status": "yellow", "detail": "1 failing"}
        else:
            stages["overall"] = {"status": "red", "detail": f"{red_count} failing"}

        by_lab.append({
            "lab_code": lab,
            "namespaces": m["namespaces"],
            "clusters": sorted(m["clusters"] - {""}),
            "fail": m["fail"],
            "total": m["total"],
            "stages": stages,
        })

    # Build cluster view
    cluster_map: Dict[str, Dict] = {}
    for entry in by_namespace:
        c = entry["cluster"] or "unknown"
        if c not in cluster_map:
            cluster_map[c] = {"namespaces": 0, "pass": 0, "fail": 0, "total": 0,
                              "stage_failures": {s: 0 for s in STAGES},
                              "failure_classes": {}}
        cm = cluster_map[c]
        cm["namespaces"] += 1
        cm["pass"] += entry["pass"]
        cm["fail"] += entry["fail"]
        cm["total"] += entry["total"]
        for fc, cnt in ns_data[entry["namespace"]]["failure_classes"].items():
            cm["failure_classes"][fc] = cm["failure_classes"].get(fc, 0) + cnt
            stage = STAGE_MAP.get(fc, "workload")
            cm["stage_failures"][stage] += cnt

    by_cluster = []
    for c, cm in sorted(cluster_map.items(), key=lambda x: x[1]["fail"], reverse=True):
        stages = {}
        for s in STAGES:
            if s == "overall":
                continue
            fc_count = cm["stage_failures"].get(s, 0)
            if fc_count == 0:
                stages[s] = {"status": "green", "detail": "ok"}
            else:
                top_fcs = sorted(
                    [(fc, cnt) for fc, cnt in cm["failure_classes"].items() if STAGE_MAP.get(fc) == s],
                    key=lambda x: -x[1],
                )
                stages[s] = {"status": "red", "detail": f"{fc_count} ({top_fcs[0][0]})" if top_fcs else str(fc_count)}
        red_count = sum(1 for v in stages.values() if v["status"] == "red")
        if red_count == 0:
            stages["overall"] = {"status": "green", "detail": "all clear"}
        elif red_count == 1:
            stages["overall"] = {"status": "yellow", "detail": "1 failing"}
        else:
            stages["overall"] = {"status": "red", "detail": f"{red_count} failing"}

        by_cluster.append({
            "cluster": c,
            "namespaces": cm["namespaces"],
            "fail": cm["fail"],
            "total": cm["total"],
            "top_failure": max(cm["failure_classes"], key=cm["failure_classes"].get) if cm["failure_classes"] else None,
            "stages": stages,
        })

    # Attach last resolution info (single batch query)
    try:
        from db.models import ResolutionRecord
        failing_ns = [r["namespace"] for r in by_namespace]
        if failing_ns:
            latest_resolutions = (
                db.query(ResolutionRecord)
                .filter(ResolutionRecord.lab_code.in_(failing_ns))
                .order_by(ResolutionRecord.resolved_at.desc())
                .all()
            )
            res_by_ns: Dict[str, Dict] = {}
            for r in latest_resolutions:
                if r.lab_code not in res_by_ns:
                    res_by_ns[r.lab_code] = {
                        "resolution_type": r.resolution_type,
                        "resolved_by": r.resolved_by,
                        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                        "ttr_minutes": round(r.ttr_seconds / 60.0, 1) if r.ttr_seconds else None,
                        "failure_class": r.failure_class,
                    }
            for entry in by_namespace:
                entry["last_resolution"] = res_by_ns.get(entry["namespace"])
    except Exception:
        pass

    # Summary — counts ALL namespaces (including healthy) for accurate percentages
    total_ns_count = len(all_ns_stages)
    stage_totals: Dict[str, Dict[str, int]] = {s: {"green": 0, "yellow": 0, "red": 0} for s in STAGES}
    for stages in all_ns_stages:
        for s in STAGES:
            st = stages.get(s, {}).get("status", "green")
            stage_totals[s][st] = stage_totals[s].get(st, 0) + 1

    # Attention breakdown
    attention_counts: Dict[str, int] = {}
    for entry in by_namespace:
        a = entry.get("attention", "expected")
        attention_counts[a] = attention_counts.get(a, 0) + 1

    # Catalog item health summary
    cat_health: Dict[str, Dict] = {}
    for entry in by_namespace:
        cat = entry.get("catalog_item", "unknown")
        if cat not in cat_health:
            cat_health[cat] = {"total": 0, "stuck": 0, "anomalous": 0, "expected": 0, "provisioning": 0}
        cat_health[cat]["total"] += 1
        cat_health[cat][entry.get("attention", "expected")] += 1

    by_catalog_item = sorted([
        {"catalog_item": cat, "lab_name": catalog_display_names.get(cat, cat), **counts}
        for cat, counts in cat_health.items()
    ], key=lambda x: x["stuck"] + x["anomalous"], reverse=True)

    # --- Failure class correlation view ---
    # Per failure class: current rate vs baseline, which catalog items & clusters hit,
    # attention classification (spiking / spreading / normal / improving)
    by_failure_class = _build_failure_class_view(by_namespace, baselines, ns_data, db)

    return {
        "stages": STAGES,
        "by_namespace": by_namespace[:500],
        "by_lab": by_lab,
        "by_cluster": by_cluster,
        "by_catalog_item": by_catalog_item,
        "by_failure_class": by_failure_class,
        "summary": {
            "total_namespaces": len(by_namespace),
            "total_monitored": total_ns_count,
            "total_labs": len(by_lab),
            "total_clusters": len(by_cluster),
            "needs_attention": attention_counts.get("stuck", 0) + attention_counts.get("anomalous", 0),
            "expected_noise": attention_counts.get("expected", 0) + attention_counts.get("provisioning", 0),
            "attention_counts": attention_counts,
            "stages_health": {
                s: "red" if t["red"] > 0 else "yellow" if t["yellow"] > 0 else "green"
                for s, t in stage_totals.items()
            },
            "stage_counts": stage_totals,
        },
    }


# ---------------------------------------------------------------------------
# Deepfield / GeoLux proxy endpoints
# ---------------------------------------------------------------------------

def _proxy_get(url: str, headers: dict | None = None, timeout: int = 15) -> dict:
    """Fetch JSON from an internal service URL."""
    import urllib.request
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)[:200]}


def _proxy_parallel(calls: list[tuple[str, str, dict | None]]) -> dict:
    """Fetch multiple URLs in parallel. calls = [(key, url, headers), ...]"""
    from concurrent.futures import ThreadPoolExecutor
    results = {}

    def _fetch(key, url, headers):
        results[key] = _proxy_get(url, headers)

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        for key, url, headers in calls:
            pool.submit(_fetch, key, url, headers)

    return results


@router.get("/admin/deepfield/overview")
def deepfield_overview(_auth=Depends(require_admin_read)):
    """Proxy Deepfield metrics + incidents for the StarGate dashboard."""
    import os
    base = os.environ.get("STARGATE_DEEPFIELD_INTERNAL_URL", "http://deepfield-backend.deepfield.svc:8099")

    r = _proxy_parallel([
        ("metrics", f"{base}/api/v1/metrics?window=1h", None),
        ("incidents", f"{base}/api/v1/incidents?limit=50", None),
        ("clusters", f"{base}/api/v1/observatory/clusters", None),
    ])

    incidents = r.get("incidents", {})
    clusters = r.get("clusters", {})
    return {
        "metrics": r.get("metrics", {}),
        "incidents": incidents.get("incidents", []) if isinstance(incidents, dict) else [],
        "incident_count": incidents.get("count", 0) if isinstance(incidents, dict) else 0,
        "clusters": clusters.get("clusters", {}) if isinstance(clusters, dict) else {},
    }


@router.get("/admin/geolux/overview")
def geolux_overview(_auth=Depends(require_admin_read)):
    """Proxy GeoLux governance pipeline + stability for the StarGate dashboard."""
    import os
    base = os.environ.get("STARGATE_GEOLUX_URL", "http://geolux-geolux.geolux.svc:8091")
    api_key = os.environ.get("STARGATE_GEOLUX_API_KEY", "")
    headers = {"X-API-Key": api_key} if api_key else {}

    r = _proxy_parallel([
        ("stability", f"{base}/stability/scores?limit=20", headers),
        ("thresholds", f"{base}/stability/thresholds", headers),
        ("hyp_stats", f"{base}/hypotheses/stats", headers),
        ("mpc_stats", f"{base}/mpc/stats", headers),
        ("constraints", f"{base}/classify/constraints", headers),
        ("classifications", f"{base}/classify/recent?limit=50", headers),
        ("routing", f"{base}/deepfield/routing-history?limit=10", headers),
        ("queue", f"{base}/hypotheses/queue?limit=10", headers),
    ])

    stability = r.get("stability", {})
    thresholds = r.get("thresholds", {})
    hyp_stats = r.get("hyp_stats", {})
    mpc_stats = r.get("mpc_stats", {})
    constraints = r.get("constraints", [])
    classifications = r.get("classifications", [])
    queue = r.get("queue", {})
    routing = r.get("routing", [])

    cls_pass = sum(1 for c in classifications if isinstance(c, dict) and c.get("result") == "pass") if isinstance(classifications, list) else 0
    cls_fail = sum(1 for c in classifications if isinstance(c, dict) and c.get("result") == "fail") if isinstance(classifications, list) else 0
    cls_inc = sum(1 for c in classifications if isinstance(c, dict) and c.get("result") == "inconclusive") if isinstance(classifications, list) else 0

    pipeline = {
        "classifications": {"total": len(classifications) if isinstance(classifications, list) else 0, "pass": cls_pass, "fail": cls_fail, "inconclusive": cls_inc},
        "hypotheses": {"total": hyp_stats.get("total", 0), "pending": hyp_stats.get("pending", 0), "validated": hyp_stats.get("validated", 0), "falsified": hyp_stats.get("falsified", 0)},
        "actions": {"mpc_cycles": mpc_stats.get("total", 0), "mpc_suspended": mpc_stats.get("suspended", 0)},
        "top_failure_classes": hyp_stats.get("failure_classes", []),
        "clusters": hyp_stats.get("clusters", []) if not isinstance(mpc_stats.get("clusters"), list) else mpc_stats["clusters"],
    }

    # Learned patterns (non-blocking — may not exist yet)
    learning = _proxy_get(f"{base}/learning/patterns", headers)

    return {
        "pipeline": pipeline,
        "stability_scores": stability if isinstance(stability, list) else [],
        "stability_threshold": thresholds.get("stability_threshold", 0.7) if isinstance(thresholds, dict) else 0.7,
        "hypothesis_stats": hyp_stats,
        "mpc_stats": mpc_stats,
        "constraints_count": len(constraints) if isinstance(constraints, list) else 0,
        "recent_hypotheses": queue.get("hypotheses", [])[:10] if isinstance(queue, dict) else [],
        "recent_routing": routing if isinstance(routing, list) else [],
        "learned_patterns": learning.get("patterns", []) if isinstance(learning, dict) else [],
    }
