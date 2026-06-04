"""Admin router — scheduler management, scan history, and LLM observability endpoints."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

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
    one_hour = now.replace(hour=now.hour - 1) if now.hour > 0 else now
    one_day = now.replace(day=now.day - 1) if now.day > 1 else now

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
                "confidence": e.confidence,
                "evidence_source": e.evidence_source,
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
    """Get pending actions awaiting approval."""
    from db.models import PendingAction
    pending = db.query(PendingAction).filter(PendingAction.status == "pending").all()
    return {
        "pending": [
            {
                "id": p.id,
                "action_type": p.action_type,
                "target": p.target,
                "confidence": p.confidence,
                "proposed_by": getattr(p, 'proposed_by', None) or "stargate",
                "proposed_at": p.proposed_at.isoformat() if p.proposed_at else None,
                "parameters": p.parameters,
            }
            for p in pending
        ]
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
def reject_action(action_id: int, db: Session = Depends(get_db)):
    """Reject a pending action."""
    from db.models import PendingAction
    action = db.query(PendingAction).filter(PendingAction.id == action_id).first()
    if not action:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Action not found")
    action.status = "rejected"
    action.reviewed_at = datetime.now(timezone.utc)
    action.reviewed_by = "admin"
    db.commit()
    return {"id": action.id, "status": "rejected"}


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

VALID_EXECUTION_MODES = {"recommend_only", "low_risk_auto", "full_auto"}


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
def update_remediation_config(lab_code: str, request: Request, body: dict, db: Session = Depends(get_db)):
    """Create or update remediation config for a lab."""
    from fastapi import HTTPException

    mode = body.get("execution_mode", "recommend_only")
    if mode not in VALID_EXECUTION_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid execution_mode. Must be one of: {VALID_EXECUTION_MODES}")

    max_actions = body.get("max_actions_per_hour", 5)
    if not isinstance(max_actions, int) or max_actions < 1 or max_actions > 100:
        raise HTTPException(status_code=400, detail="max_actions_per_hour must be an integer between 1 and 100")

    config = repository.upsert_lab_remediation_config(
        db,
        lab_code=lab_code,
        execution_mode=mode,
        max_actions_per_hour=max_actions,
        enabled_by=body.get("enabled_by", "admin"),
        notes=body.get("notes"),
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

    from api.routers.dashboard import _is_ecosystem_ns
    recommendations = []
    for lab_code, cluster_name, failure_class, count, last_seen, sample_message in rows:
        is_eco = _is_ecosystem_ns(lab_code)
        catalog = catalog_actions.get(failure_class, {})
        severity = "critical" if count >= 10 else "high" if count >= 5 else "medium" if count >= 2 else "low"
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
def preview_remediation(request: Request, body: dict, db: Session = Depends(get_db)):
    """Preview what remediation would do — shows every gate check and exact commands without executing."""
    import os
    import re
    from api.routers._shared import _dry_run_enabled, CONFIDENCE_THRESHOLD, TEST_NAMESPACE, EXECUTION_TARGET
    from api.action_executor import _get_lab_execution_mode, _check_rate_limit
    from api.routers.dashboard import _is_ecosystem_ns
    from engine.catalog_loader import load_catalog, ACTION_TO_FAILURE_CLASSES

    namespace = body.get("namespace", "")
    failure_class = body.get("failure_class", "")
    cluster = body.get("cluster", "")
    lab_code = body.get("lab_code", namespace)

    # Derive action_type from failure_class
    action_type = body.get("action_type", "")
    if not action_type:
        for at, fcs in ACTION_TO_FAILURE_CLASSES.items():
            if failure_class in fcs:
                action_type = at
                break
        if not action_type:
            action_type = "cleanup_stuck"

    if not namespace:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="namespace is required")

    # Template substitution helper
    _safe_name = re.compile(r"^[a-zA-Z0-9._\-]*$")
    def _sub(cmd: str) -> str:
        return cmd.replace("{namespace}", namespace).replace("{pod}", "{pod}").replace("{deployment}", "{deployment}")

    # --- Gate -1: Namespace allowlist ---
    REMEDIATION_ALLOWED_PREFIXES = os.environ.get(
        "STARGATE_REMEDIATION_NS",
        "launchpad-,stargate,deepfield,intel-rh-,user-demo-,partner-ai-",
    ).split(",")
    ns_allowed = namespace == TEST_NAMESPACE or any(
        namespace.startswith(p.strip()) for p in REMEDIATION_ALLOWED_PREFIXES if p.strip()
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
def execute_remediation(request: Request, body: dict, db: Session = Depends(get_db)):
    """Manually trigger remediation for a specific namespace + failure class.

    This is the human-in-the-loop "Remediate Now" button — not auto-execution.
    Requires explicit operator action. Logs everything to audit trail.
    """
    from api.action_executor import execute_action
    from engine.catalog_loader import ACTION_TO_FAILURE_CLASSES

    namespace = body.get("namespace", "")
    failure_class = body.get("failure_class", "")
    cluster = body.get("cluster", "")
    lab_code = body.get("lab_code", namespace)

    action_type = body.get("action_type", "")
    if not action_type:
        for at, fcs in ACTION_TO_FAILURE_CLASSES.items():
            if failure_class in fcs:
                action_type = at
                break
        if not action_type:
            action_type = "cleanup_stuck"

    if not namespace:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="namespace is required")

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
