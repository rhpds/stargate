"""Ops sub-router — overview, security, forecast, stuck instances, readiness,
lab deltas, executive summary, AAP, and platform catalog."""

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from db.database import get_db
import api.routers._shared as _shared
from api.routers._shared import (
    _event_bus,
    _load_latest_scan,
    _load_latest_babylon,
    _fetch_labagator_labs,
    _fetch_labagator_sessions,
    _scan_to_worker_format,
    limiter,
    require_admin,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@router.get("/dashboard/overview")
def dashboard_overview(db: Session = Depends(get_db), since_minutes: int = 60, cluster: str = None):
    """Unified summary stats for all dashboard views.

    Accepts since_minutes query param to filter evaluations by time window.
    Accepts cluster query param to scope to a specific cluster.
    Default: 60 (last hour). Use 0 for all-time.
    """
    from db.models import EvaluationRecord

    from api.constants import WARNING_CLASSES

    babylon = _load_latest_babylon()
    labagator = babylon.get("labagator", {})
    labs_by_code = labagator.get("labs_by_code", {})
    JUNK_PATTERNS_O = {"stuff", "healing", "ai_driven", "published.", "satbasics"}
    from api.routers._shared import EVENT_PREFIX
    filtered_codes_o = [
        code for code in labs_by_code
        if not code.startswith("-")
        and not any(code.lower().startswith(p) or code.lower() == p for p in JUNK_PATTERNS_O)
        and not ("-" in code and code.rsplit("-", 1)[0] in labs_by_code and code.rsplit("-", 1)[1].isdigit())
        and (EVENT_PREFIX or not (labs_by_code[code].get("ci_name") or "").startswith("summit-"))
    ]
    lab_count = len(filtered_codes_o)
    with_sessions = sum(1 for code in filtered_codes_o if labs_by_code[code].get("session_count", 0) > 0)

    scans = []
    if _shared._scheduler and any(wt.tick_count > 0 for wt in _shared._scheduler.workers):
        for wt in _shared._scheduler.workers:
            if wt.tick_count == 0 or not wt.last_result:
                continue
            r = wt.last_result
            n = r.get("nodes", {})
            p = r.get("pods", {})
            compute_nodes = n.get("compute_nodes", 1) or 1
            total_vms = p.get("total_vms", 0)
            sandbox_active = p.get("sandbox_active", 0)
            sandbox_failing = p.get("sandbox_failing", 0)
            crashloops = p.get("crashloops", 0)
            vms_per_node = round(total_vms / compute_nodes, 1) if compute_nodes else 0
            health_rate = round((sandbox_active - sandbox_failing) / max(sandbox_active, 1) * 100, 1) if sandbox_active > 0 else 0

            status = n.get("status", "healthy")
            issues = []
            hot = n.get("hot_nodes", 0)
            avg_cpu = n.get("avg_cpu", 0)
            if hot > 0:
                issues.append(f"{hot} nodes >80% CPU")
            if vms_per_node > 30:
                issues.append(f"{vms_per_node} VMs/node (threshold: 30)")
            if crashloops > 0:
                issues.append(f"{crashloops} showroom CrashLoopBackOff")

            scans.append({
                "cluster": wt.worker.state.name,
                "avg_cpu_pct": avg_cpu,
                "hot_nodes": hot,
                "sandbox_active": sandbox_active,
                "sandbox_failing": sandbox_failing,
                "sandbox_crashloop": crashloops,
                "total_vms": total_vms,
                "vms_per_node": vms_per_node,
                "health_rate": health_rate,
                "status": status,
                "dns_warnings": 0,
                "issues": issues,
            })
    scan_file_data = _load_latest_scan()
    if not scans:
        scans = scan_file_data
    elif scan_file_data:
        live_clusters = {s["cluster"] for s in scans}
        for s in scan_file_data:
            if s.get("cluster") not in live_clusters:
                scans.append(s)
    cluster_count = len(scans)
    healthy_clusters = sum(1 for s in scans if s.get("status") == "healthy")
    warning_clusters = sum(1 for s in scans if s.get("status") == "warning")
    critical_clusters = sum(1 for s in scans if s.get("status") == "critical")

    pools_data = babylon.get("pools", {})
    total_pools = pools_data.get("total_pools", 0)
    exhausted = len(pools_data.get("exhausted", []))
    low = len(pools_data.get("low", []))

    prov = babylon.get("provisioning", {})
    summit_prov = prov

    eval_query = db.query(EvaluationRecord).filter(
        EvaluationRecord.outcome == "fail",
    )
    if since_minutes > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        eval_query = eval_query.filter(EvaluationRecord.evaluated_at >= cutoff)
    if cluster:
        eval_query = eval_query.filter(EvaluationRecord.cluster_name == cluster)
    all_evals = eval_query.all()
    real_failures = [e for e in all_evals if (e.failure_class or "unclassified") not in WARNING_CLASSES]
    failure_classes: Dict[str, int] = {}
    for e in real_failures:
        fc = e.failure_class or "unclassified"
        failure_classes[fc] = failure_classes.get(fc, 0) + 1
    top_class = max(failure_classes, key=failure_classes.get) if failure_classes else None

    systemic = sum(1 for e in _event_bus.history if e.systemic)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "labs": {
            "total": lab_count,
            "with_sessions": with_sessions,
            "status_counts": {
                status: sum(1 for code in filtered_codes_o if labs_by_code[code].get("status") == status)
                for status in {labs_by_code[c].get("status", "") for c in filtered_codes_o} if status
            },
        },
        "clusters": {
            "total": cluster_count,
            "healthy": healthy_clusters,
            "warning": warning_clusters,
            "critical": critical_clusters,
            "scans": [
                {
                    "cluster": s.get("cluster"),
                    "avg_cpu_pct": s.get("avg_cpu_pct"),
                    "hot_nodes": s.get("hot_nodes"),
                    "sandbox_active": s.get("sandbox_active"),
                    "sandbox_failing": s.get("sandbox_failing", 0),
                    "sandbox_crashloop": s.get("sandbox_crashloop", 0),
                    "total_vms": s.get("total_vms"),
                    "vms_per_node": s.get("vms_per_node"),
                    "health_rate": s.get("health_rate"),
                    "status": s.get("status"),
                    "dns_warnings": s.get("dns_warnings"),
                    "issues": s.get("issues", []),
                }
                for s in scans
            ],
        },
        "pools": {
            "total": total_pools,
            "exhausted": exhausted,
            "low": low,
            "all_pools": pools_data.get("all_pools", pools_data.get("summit_pools", [])),
            "summit_pools": pools_data.get("summit_pools", []),
        },
        "provisioning": {
            "total": summit_prov.get("total", prov.get("total", 0)),
            "started": summit_prov.get("started", prov.get("started", 0)),
            "failed": summit_prov.get("failed", prov.get("failed", 0)),
            "failure_rate": prov.get("failure_rate", 0),
            "by_state": prov.get("by_state", {}),
        },
        "errors": {
            "total_failures": len(real_failures),
            "top_class": top_class,
            "failure_classes": failure_classes,
            "systemic": systemic,
        },
    }


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

@router.get("/dashboard/security")
def dashboard_security():
    """Security posture — cluster versions, kernel versions, known CVEs (read-only display)."""
    clusters = []
    for s in _load_latest_scan():
        clusters.append({
            "cluster": s.get("cluster", ""),
            "status": s.get("status", "unknown"),
        })

    known_cves = [
        {
            "cve_id": "CVE-2026-43284",
            "name": "Dirty Frag",
            "severity": "HIGH",
            "cvss": 7.8,
            "affected": "RHEL 9 kernel, RHCOS (OCP 4)",
            "status": "Affected — no errata",
            "mitigation": "Blacklist esp4/esp6 kernel modules via DaemonSet",
            "mitigation_time": "6 minutes",
            "mitigation_risk": "Near zero — IPsec disabled on all clusters",
            "applied": False,
        },
    ]

    return {
        "clusters": clusters,
        "known_cves": known_cves,
        "ocp_versions_behind": {
            "compute": "4.20.8 → 4.20.21 available (13 versions)",
            "infra01": "4.18.16 → 4.18.40 available (24 versions)",
            "infra02": "4.18.35 → 4.18.40 available (5 versions)",
        },
        "recommendations": [
            {"priority": "IMMEDIATE", "action": "Apply CVE-2026-43284 DaemonSet mitigation", "time": "6 min"},
            {"priority": "POST-SUMMIT", "action": "Update compute clusters to OCP 4.20.21", "time": "6 hours"},
            {"priority": "POST-SUMMIT", "action": "Update infra01 to OCP 4.18.40", "time": "2 hours"},
            {"priority": "POST-SUMMIT", "action": "Add NetworkPolicies to 134 unprotected sandboxes", "time": "1 hour"},
        ],
    }


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------

@router.get("/dashboard/forecast")
def dashboard_forecast(db: Session = Depends(get_db)):
    """Project resource usage for the next 6 hours based on session schedule and current state."""
    babylon = _load_latest_babylon()
    labagator = babylon.get("labagator", {})
    labs_by_code = labagator.get("labs_by_code", {})
    pools = babylon.get("pools", {})
    prov = babylon.get("provisioning", {})

    sessions = _fetch_labagator_sessions()

    now = datetime.now(timezone.utc)
    forecast_hours = []

    for h in range(7):
        hour_start = now + timedelta(hours=h)
        hour_end = hour_start + timedelta(hours=1)
        hour_label = hour_start.strftime("%H:%M")

        sessions_starting = []
        total_attendees = 0
        for s in sessions:
            sd = s.get("session_date", "")
            st = s.get("start_time", "")
            if sd and st:
                try:
                    session_time = datetime.fromisoformat(f"{sd}T{st}").replace(tzinfo=timezone.utc)
                    if hour_start <= session_time < hour_end:
                        sessions_starting.append({
                            "lab_code": s.get("lab_code", ""),
                            "attendees": s.get("attendees") or 0,
                            "room": s.get("room", ""),
                        })
                        total_attendees += s.get("attendees") or 0
                except (ValueError, TypeError):
                    continue

        estimated_new_sandboxes = total_attendees
        current_pools_available = sum(p.get("available", 0) for p in pools.get("all_pools", pools.get("summit_pools", [])))

        forecast_hours.append({
            "hour": hour_label,
            "timestamp": hour_start.isoformat(),
            "sessions_starting": len(sessions_starting),
            "labs": [s["lab_code"] for s in sessions_starting],
            "total_attendees": total_attendees,
            "estimated_new_sandboxes": estimated_new_sandboxes,
            "pools_available_now": current_pools_available,
            "risk": "high" if estimated_new_sandboxes > current_pools_available * 0.8 else "medium" if estimated_new_sandboxes > current_pools_available * 0.5 else "low",
        })

    cluster_projections = []
    for s in _load_latest_scan():
        r = _scan_to_worker_format(s)
        n = r["nodes"]
        p = r["pods"]
        avg_cpu = n["avg_cpu"]

        cluster_projections.append({
            "cluster": r["cluster"],
            "current_cpu": avg_cpu,
            "current_vms": p["total_vms"],
            "current_sandboxes": p["sandbox_active"],
            "capacity_warning": avg_cpu > 60 or p["vms_per_node"] > 80,
        })

    return {
        "generated_at": now.isoformat(),
        "forecast_hours": forecast_hours,
        "cluster_projections": cluster_projections,
        "summary": {
            "peak_hour": max(forecast_hours, key=lambda x: x["total_attendees"])["hour"] if forecast_hours else None,
            "peak_attendees": max(f["total_attendees"] for f in forecast_hours) if forecast_hours else 0,
            "high_risk_hours": sum(1 for f in forecast_hours if f["risk"] == "high"),
        },
    }


# ---------------------------------------------------------------------------
# Stuck instances
# ---------------------------------------------------------------------------

@router.get("/dashboard/stuck-instances")
def dashboard_stuck_instances():
    """Return all stuck AnarchySubject instances grouped by lab."""
    babylon = _load_latest_babylon()
    mapping = babylon.get("instance_mapping", babylon.get("summit_mapping", {}))
    prov = babylon.get("provisioning", {})
    by_state = prov.get("by_state", {})

    by_lab: Dict[str, List[Dict]] = {}
    for lb, instances in mapping.items():
        for inst in instances:
            st = inst.get("state", "")
            if "failed" in st or "error" in st:
                if lb not in by_lab:
                    by_lab[lb] = []
                by_lab[lb].append({
                    "name": inst.get("anarchy_name", ""),
                    "state": st,
                    "namespace": inst.get("namespace", ""),
                    "console_url": inst.get("console_url", ""),
                    "api_url": inst.get("api_url", ""),
                })

    return {
        "by_lab": {k: v for k, v in sorted(by_lab.items(), key=lambda x: -len(x[1]))},
        "total_stuck": sum(len(v) for v in by_lab.values()),
        "platform_stuck": {
            "destroy_failed": by_state.get("destroy-failed", 0),
            "provision_failed": by_state.get("provision-failed", 0),
            "provision_error": by_state.get("provision-error", 0),
            "start_error": by_state.get("start-error", 0),
            "stop_failed": by_state.get("stop-failed", 0),
            "stopped": by_state.get("stopped", 0),
        },
    }


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

@router.get("/dashboard/readiness")
def dashboard_readiness(db: Session = Depends(get_db)):
    """Overall operational readiness score with gate statuses."""
    from api.routers._shared import EVENT_DATE, EVENT_NAME
    if EVENT_DATE:
        try:
            event_dt = datetime.fromisoformat(EVENT_DATE).replace(tzinfo=timezone.utc)
        except ValueError:
            event_dt = datetime.now(timezone.utc)
        days_until = (event_dt - datetime.now(timezone.utc)).days
    else:
        days_until = None

    from api.routers.dashboard.deployments import dashboard_summit
    summit_data = dashboard_summit(db)
    labs = summit_data.get("labs", [])
    total_labs = len(labs)
    with_sessions = sum(1 for l in labs if l.get("sessions", 0) > 0)

    labs_provisioned = sum(1 for l in labs if
        l.get("instances_started", 0) > 0 or
        l.get("provisioned", 0) > 0 or
        l.get("demolition_status", "none") != "none" or
        l.get("cloud") == "Tenant Namespace"
    )

    scans = _load_latest_scan()
    healthy_clusters = sum(1 for s in scans if s.get("status") == "healthy")
    critical_clusters = sum(1 for s in scans if s.get("status") == "critical")
    avg_health = round(sum(s.get("health_rate", 0) for s in scans) / max(len(scans), 1), 1)
    scans_count = len(scans)

    escalated = sum(1 for e in _event_bus.history if e.metadata.get("escalate"))

    prov_pct = round(labs_provisioned / max(total_labs, 1) * 100, 1)
    session_pct = round(with_sessions / max(total_labs, 1) * 100, 1)

    def _gate(value: float, low: float, high: float) -> str:
        if value < low:
            return "red"
        if value < high:
            return "yellow"
        return "green"

    capacity_score = 100
    depleting_pools = 0
    capacity_risk = "low"
    try:
        from engine.pool_velocity import compute_pool_velocity, estimate_exhaustion
        from db.repository import get_pool_timeline
        babylon = _load_latest_babylon()
        if babylon:
            for pname, pdata in babylon.get("pools", {}).items():
                if isinstance(pdata, dict) and pdata.get("min_available", 0) > 0:
                    timeline = get_pool_timeline(db, pname, hours=6)
                    if len(timeline) >= 2:
                        vel = compute_pool_velocity(timeline)
                        if vel["trend"] == "depleting":
                            depleting_pools += 1
                            eta = estimate_exhaustion(pdata.get("available", 0), vel["handles_per_hour"])
                            if eta is not None and eta < 2:
                                capacity_score = min(capacity_score, 0)
                                capacity_risk = "critical"
                            elif eta is not None and eta < 6:
                                capacity_score = min(capacity_score, 50)
                                capacity_risk = "high" if capacity_risk != "critical" else capacity_risk
    except Exception:
        pass

    sandbox_api_score = 100
    sandbox_healthy = True
    sandbox_active = 0
    sandbox_failing = 0
    try:
        from collectors.sandbox_api.collect_sandbox_api import collect_sandbox_counts
        counts = collect_sandbox_counts(scans)
        sandbox_active = counts.get("active", 0)
        sandbox_failing = counts.get("failing", 0)
        total = sandbox_active + sandbox_failing
        failing_rate = (sandbox_failing / max(total, 1)) * 100
        if failing_rate > 5:
            sandbox_api_score = 50
            sandbox_healthy = failing_rate < 10
        if not sandbox_healthy:
            sandbox_api_score = 0
    except Exception:
        pass

    infra_score = 100 if critical_clusters == 0 else max(0, 100 - critical_clusters * 25)

    overall = round(
        0.30 * min(prov_pct, 100) +
        0.25 * min(avg_health, 100) +
        0.15 * min(session_pct, 100) +
        0.10 * infra_score +
        0.10 * capacity_score +
        0.10 * sandbox_api_score,
        1,
    )

    return {
        "event_date": EVENT_DATE or None,
        "event_name": EVENT_NAME,
        "days_until_event": max(days_until, 0) if days_until is not None else None,
        "overall_readiness_pct": overall,
        "labs_provisioned": labs_provisioned,
        "labs_target": total_labs,
        "labs_with_sessions": with_sessions,
        "gates": {
            "provisioning": {
                "status": _gate(prov_pct, 50, 80),
                "value": labs_provisioned,
                "target": total_labs,
                "pct": prov_pct,
            },
            "health": {
                "status": _gate(avg_health, 70, 90),
                "value": avg_health,
                "target": 90,
            },
            "sessions": {
                "status": _gate(session_pct, 50, 80),
                "value": with_sessions,
                "target": total_labs,
                "pct": session_pct,
            },
            "infrastructure": {
                "status": "green" if critical_clusters == 0 else "red" if critical_clusters > 1 else "yellow",
                "value": critical_clusters,
                "detail": f"{healthy_clusters} healthy, {critical_clusters} critical of {scans_count} clusters",
            },
            "capacity": {
                "status": "green" if capacity_score >= 80 else "yellow" if capacity_score >= 40 else "red",
                "value": depleting_pools,
                "detail": f"{depleting_pools} pools depleting, risk: {capacity_risk}",
            },
            "sandbox_api": {
                "status": "green" if sandbox_api_score >= 80 else "yellow" if sandbox_api_score >= 40 else "red",
                "value": sandbox_active,
                "detail": f"{'Healthy' if sandbox_healthy else 'DEGRADED'}, {sandbox_active} active, {sandbox_failing} failing",
            },
        },
        "escalated_events": escalated,
    }


# ---------------------------------------------------------------------------
# Lab deltas
# ---------------------------------------------------------------------------

@router.get("/dashboard/lab-deltas")
def dashboard_lab_deltas(db: Session = Depends(get_db)):
    """Compare current lab state against previous snapshot to show progress."""
    scan_dir = Path(__file__).parent.parent.parent.parent / "scan-history"
    babylon_files = sorted(scan_dir.glob("babylon-*.json"), reverse=True)

    if len(babylon_files) < 2:
        return {"deltas": {}, "previous_time": None, "current_time": None}

    with open(babylon_files[0]) as f:
        current = json.load(f)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    prev_file = babylon_files[-1]
    for bf in reversed(babylon_files[1:]):
        try:
            fname = bf.stem
            file_ts = datetime.strptime(fname, "babylon-%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
            if file_ts <= cutoff:
                prev_file = bf
                break
        except ValueError:
            continue

    with open(prev_file) as f:
        previous = json.load(f)

    curr_mapping = current.get("summit_mapping", {})
    prev_mapping = previous.get("summit_mapping", {})

    curr_pools = {p["name"]: p for p in current.get("pools", {}).get("all_pools", current.get("pools", {}).get("summit_pools", []))}
    prev_pools = {p["name"]: p for p in previous.get("pools", {}).get("all_pools", previous.get("pools", {}).get("summit_pools", []))}

    curr_demo = current.get("demolition_summit", [])
    prev_demo = previous.get("demolition_summit", [])

    def _demo_status(demo_list: list, lab_code: str) -> Optional[str]:
        for s in sorted(demo_list, key=lambda x: x.get("id", 0), reverse=True):
            if lab_code.lower() in s.get("name", "").lower():
                result = s.get("last_result") or {}
                if result.get("completed", 0) > 0 and result.get("failed", 0) == 0:
                    return "pass"
                if result.get("failed", 0) > 0:
                    return "fail"
                return None
        return None

    curr_labs = current.get("labagator", {}).get("labs_by_code", {})
    deltas: Dict[str, Dict] = {}

    for code in curr_labs:
        d: Dict[str, Optional[str]] = {}

        curr_instances = len(curr_mapping.get(code, []))
        prev_instances = len(prev_mapping.get(code, []))
        curr_started = sum(1 for i in curr_mapping.get(code, []) if i.get("state") == "started")
        prev_started = sum(1 for i in prev_mapping.get(code, []) if i.get("state") == "started")

        if curr_started > prev_started:
            d["instances"] = "up"
        elif curr_started < prev_started:
            d["instances"] = "down"

        for pname, pool in curr_pools.items():
            if code.lower() in pname.lower():
                prev_pool = prev_pools.get(pname, {})
                curr_ready = pool.get("ready", 0)
                prev_ready = prev_pool.get("ready", 0) if prev_pool else 0
                if curr_ready > prev_ready:
                    d["capacity"] = "up"
                elif curr_ready < prev_ready:
                    d["capacity"] = "down"
                break

        curr_smoke = _demo_status(curr_demo, code)
        prev_smoke = _demo_status(prev_demo, code)
        if curr_smoke == "pass" and prev_smoke != "pass":
            d["smoke"] = "up"
        elif curr_smoke == "fail" and prev_smoke != "fail":
            d["smoke"] = "down"
        elif curr_smoke != "pass" and prev_smoke == "pass":
            d["smoke"] = "down"

        curr_status = curr_labs.get(code, {}).get("status", "")
        prev_lab = previous.get("labagator", {}).get("labs_by_code", {}).get(code, {})
        prev_status = prev_lab.get("status", "")
        if curr_status == "in_development" and prev_status == "planning":
            d["status"] = "up"

        if d:
            deltas[code] = d

    try:
        fname = babylon_files[1].stem
        prev_time = datetime.strptime(fname, "babylon-%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        prev_time = None

    return {
        "deltas": deltas,
        "previous_time": prev_time,
        "current_time": datetime.now(timezone.utc).isoformat(),
        "labs_changed": len(deltas),
    }


# ---------------------------------------------------------------------------
# Executive summary
# ---------------------------------------------------------------------------

@router.post("/dashboard/executive-summary")
@limiter.limit("5/minute")
def dashboard_executive_summary(request: Request, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Generate an executive summary with per-lab provisioning detail via configured LLM."""
    import urllib.request as urllib_req
    from db.models import EvaluationRecord

    readiness = dashboard_readiness(db)
    from api.routers.dashboard.infra import dashboard_pipeline
    pipeline_data = dashboard_pipeline(db=db)

    from api.routers.dashboard.deployments import dashboard_summit, _get_aap_summary_for_evidence, _get_capacity_evidence_for_summary
    summit_data = dashboard_summit(db)
    labs = summit_data.get("labs", [])

    all_failures = db.query(EvaluationRecord).filter(EvaluationRecord.outcome == "fail").all()
    failure_counts: Dict[str, int] = {}
    for e in all_failures:
        fc = e.failure_class or "unclassified"
        failure_counts[fc] = failure_counts.get(fc, 0) + 1
    top_failures = sorted(failure_counts.items(), key=lambda x: -x[1])[:10]

    cluster_lines = []
    if _shared._scheduler:
        for wt in _shared._scheduler.workers:
            if wt.tick_count == 0 or not wt.last_result:
                continue
            r = wt.last_result
            n = r.get("nodes", {})
            p = r.get("pods", {})
            cluster_lines.append(
                f"{wt.worker.state.name}: CPU {n.get('avg_cpu', '?')}%, "
                f"{p.get('total_vms', 0)} VMs, {p.get('vms_per_node', 0)} VMs/node, "
                f"{p.get('sandbox_active', 0)} labs active, {p.get('sandbox_failing', 0)} failing, "
                f"{p.get('crashloops', 0)} crashlooping — {n.get('status', '?')}"
            )
    if not cluster_lines:
        scans = _load_latest_scan()
        for s in scans:
            cluster_lines.append(
                f"{s['cluster']}: CPU {s.get('avg_cpu_pct', '?')}%, "
                f"{s.get('total_vms', 0)} VMs, health {s.get('health_rate', 0)}%"
            )

    pipeline_lines = []
    for stage in pipeline_data["stages"]:
        if stage["total"] > 0:
            pipeline_lines.append(
                f"{stage['stage_id']}: {stage['pass']}/{stage['total']} pass ({stage['health_rate']}%)"
            )

    labs_ready = []
    labs_at_risk = []
    labs_blocked = []
    labs_no_sessions = []

    for lab in labs:
        code = lab["lab_code"]
        sessions = lab["sessions"]
        instances_up = lab.get("instances_started", 0)
        instances_total = lab.get("instances_total", 0)
        provisioned = lab["provisioned"]
        capacity = lab["capacity"]
        smoke = lab.get("demolition_status", "none")
        status = lab["labagator_status"]

        has_capacity = instances_up > 0 or provisioned > 0
        has_sessions_flag = sessions > 0

        detail = f"{code} ({lab['title'][:40]}): sessions={sessions}, "
        if instances_total > 0:
            detail += f"instances={instances_up}/{instances_total}, "
        elif capacity > 0:
            detail += f"pools={provisioned}/{capacity}, "
        else:
            detail += "no pools, "
        detail += f"smoke={smoke}, stage={status}"
        aap_fails = lab.get("aap_provision_failures", 0)
        if aap_fails > 0:
            detail += f", AAP: {aap_fails} failures ({lab.get('aap_top_error', '')[:40]})"

        if not has_sessions_flag:
            labs_no_sessions.append(detail)
        elif has_capacity and smoke == "pass":
            labs_ready.append(detail)
        elif has_capacity and smoke != "pass":
            labs_at_risk.append(detail)
        else:
            labs_blocked.append(detail)

    days_str = f"{readiness.get('days_until_event', '?')} days until event" if readiness.get('days_until_event') is not None else "continuous operations"
    evidence = f"""## {readiness.get('event_name', 'Platform')} Readiness Report — {days_str}
Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
Context: This is a PROVISIONING & DEPLOYMENT readiness check, not a live Summit event.

### Overall Readiness: {readiness['overall_readiness_pct']}%
Score formula: 40% provisioning + 30% cluster health + 20% session coverage + 10% infrastructure

### Gates
- Provisioning: {readiness['gates']['provisioning']['value']}/{readiness['gates']['provisioning']['target']} pools ready ({readiness['gates']['provisioning']['pct']}%) — {readiness['gates']['provisioning']['status'].upper()}
- Health: {readiness['gates']['health']['value']}% average cluster health — {readiness['gates']['health']['status'].upper()}
- Sessions: {readiness['gates']['sessions']['value']}/{readiness['gates']['sessions']['target']} labs scheduled ({readiness['gates']['sessions']['pct']}%) — {readiness['gates']['sessions']['status'].upper()}
- Infrastructure: {readiness['gates']['infrastructure']['detail']} — {readiness['gates']['infrastructure']['status'].upper()}

### AAP Provisioning Health
{_get_aap_summary_for_evidence()}

### Cluster Infrastructure (live data)
{chr(10).join(cluster_lines) if cluster_lines else 'No cluster data available'}

### Provisioning Pipeline Pass Rates
{chr(10).join(pipeline_lines) if pipeline_lines else 'No pipeline data'}

### Top Failure Classes ({sum(v for _,v in top_failures)} total failures)
{chr(10).join(f'- {fc}: {count}' for fc, count in top_failures)}

### Lab Readiness Breakdown
Total labs: {len(labs)}

READY ({len(labs_ready)} labs — sessions scheduled, provisioned, smoke test passing):
{chr(10).join(labs_ready[:15]) if labs_ready else '(none)'}

AT RISK ({len(labs_at_risk)} labs — provisioned but smoke test failing or not tested):
{chr(10).join(labs_at_risk[:15]) if labs_at_risk else '(none)'}

BLOCKED ({len(labs_blocked)} labs — sessions scheduled but NO provisioning):
{chr(10).join(labs_blocked[:20]) if labs_blocked else '(none)'}

NO SESSIONS ({len(labs_no_sessions)} labs — no sessions scheduled, may not be needed for Summit):
{chr(10).join(labs_no_sessions[:10]) if labs_no_sessions else '(none)'}
{'... and ' + str(len(labs_no_sessions) - 10) + ' more' if len(labs_no_sessions) > 10 else ''}

{_get_capacity_evidence_for_summary(db)}
"""

    prompt = f"""{evidence}

## Task
You are a platform operations lead reviewing workload readiness. Based on the evidence:

1. **Executive Summary** (3-4 sentences): What is the overall platform health? What's the biggest gap? What needs attention first?

2. **Blocked Labs — Immediate Action** ({len(labs_blocked)} labs with sessions but no provisioning): What needs to happen to unblock them? These are the highest priority.

3. **At-Risk Labs** ({len(labs_at_risk)} labs failing smoke tests): What's causing the failures and what's the remediation path?

4. **Infrastructure Assessment**: Are the clusters sized correctly? Any capacity or health concerns across the {len(cluster_lines)} clusters?

5. **Pipeline Issues**: Why are certain rubric stages showing low pass rates? What's the systemic cause?

6. **Recommended Priority Actions** (numbered, top 5): What should the ops team do RIGHT NOW, in order of impact?

Be specific — reference lab codes, cluster names, failure classes, and actual numbers from the evidence."""

    from api.llm import call_llm, load_prompt, LLM_MODEL
    _exec_prompt = load_prompt("executive-summary")
    llm_result = call_llm(
        endpoint="executive-summary",
        messages=[
            {"role": "system", "content": _exec_prompt.get("system", "You are a Red Hat OpenShift operations expert managing lab provisioning and workload readiness.")},
            {"role": "user", "content": prompt},
        ],
        max_tokens=_exec_prompt.get("max_tokens", 2000),
        temperature=_exec_prompt.get("temperature", 0.3),
        timeout=90,
        db=db,
        prompt_version=_exec_prompt.get("version"),
    )
    llm_analysis = llm_result["content"] if llm_result["success"] else f"LLM call failed: {llm_result['error']}"
    llm_model = LLM_MODEL

    sources_queried = ["labagator", "stargate_db"]
    if cluster_lines:
        sources_queried.append("scanner")
    if "AAP" in evidence:
        sources_queried.append("aap")
    if "Pool Velocity" in evidence or "Sandbox-API" in evidence:
        sources_queried.extend(["babylon", "sandbox_api"])
    if "ZeroTouch" in evidence:
        sources_queried.append("zerotouch")
    if "Complex Labs" in evidence:
        sources_queried.append("agnosticv")
    sources_queried.append("llm")

    return {
        "evidence": evidence,
        "analysis": llm_analysis,
        "model": llm_model,
        "readiness": readiness,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sources_queried": list(set(sources_queried)),
        "lab_counts": {
            "ready": len(labs_ready),
            "at_risk": len(labs_at_risk),
            "blocked": len(labs_blocked),
            "no_sessions": len(labs_no_sessions),
        },
    }


# ---------------------------------------------------------------------------
# AAP provisioning
# ---------------------------------------------------------------------------

@router.get("/dashboard/aap")
def dashboard_aap():
    """AAP provisioning job health — success rates, failures, SLI tracking."""
    try:
        from collectors.aap.collect_aap import collect_aap_jobs
        return collect_aap_jobs()
    except Exception as e:
        return {
            "summary": {
                "total_jobs": 0, "successful": 0, "failed": 0, "running": 0,
                "success_rate": 0, "provision_sli": 0, "provision_sli_target": 93.0,
                "sli_met": False, "failed_24h": 0,
            },
            "top_errors": [],
            "by_cluster": {},
            "by_lab": {},
            "recent_failures": [],
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Platform Catalog — all deployable items across Babylon + ZeroTouch + AgnosticV
# ---------------------------------------------------------------------------

_catalog_cache: Dict = {"data": None, "ts": 0.0}

@router.get("/dashboard/catalog")
def dashboard_catalog(db: Session = Depends(get_db)):
    """Unified catalog of all deployable items across the platform."""
    if _catalog_cache["data"] and time.time() - _catalog_cache["ts"] < 60:
        return _catalog_cache["data"]

    items = []
    sources_found = []

    babylon = _load_latest_babylon()
    if babylon:
        catalog_items = babylon.get("catalog_items", [])
        if catalog_items:
            sources_found.append("babylon")
            for ci in catalog_items:
                items.append({
                    "name": ci.get("name", ""),
                    "display_name": ci.get("display_name", ci.get("name", "")),
                    "source": "babylon",
                    "category": ci.get("category", ""),
                    "description": ci.get("description", ""),
                    "disabled": ci.get("disabled", False),
                    "provider": ci.get("provider", ""),
                    "created": ci.get("created", ""),
                    "lab_code": None,
                })

    try:
        labagator_labs = _fetch_labagator_labs()
        if labagator_labs:
            sources_found.append("labagator")
            lab_by_ci = {}
            for lab in labagator_labs:
                ci = lab.get("ci_name") or ""
                if ci:
                    slug = ci.split(".", 1)[1] if "." in ci else ci
                    lab_by_ci[slug.lower()] = lab

            for item in items:
                parts = item["name"].split(".")
                item_slug = parts[1].lower() if len(parts) >= 2 else item["name"].lower()
                if item_slug in lab_by_ci:
                    lab = lab_by_ci[item_slug]
                    item["lab_code"] = lab.get("lab_code")
                    item["sessions"] = lab.get("session_count", 0)
                    item["labagator_status"] = lab.get("status", "")
                elif item["name"].lower() in lab_by_ci:
                    lab = lab_by_ci[item["name"].lower()]
                    item["lab_code"] = lab.get("lab_code")
                    item["sessions"] = lab.get("session_count", 0)
                    item["labagator_status"] = lab.get("status", "")
    except Exception:
        pass

    try:
        from collectors.zerotouch.collect_zerotouch import collect_catalog_items as zt_catalog
        zt_items = zt_catalog()
        if zt_items:
            sources_found.append("zerotouch")
            existing_names = {i["name"].lower() for i in items}
            for zi in zt_items:
                if zi["name"].lower() not in existing_names:
                    items.append({
                        "name": zi["name"],
                        "display_name": zi.get("display_name", zi["name"]),
                        "source": "zerotouch",
                        "category": zi.get("category", ""),
                        "description": "",
                        "disabled": zi.get("disabled", False),
                        "provider": zi.get("provider", ""),
                        "created": "",
                        "lab_code": None,
                    })
    except Exception:
        pass

    try:
        from engine.workload_complexity import compute_complexity_score
        import os
        agv_dir = os.environ.get("STARGATE_AGNOSTICV_DIR", "")
        if agv_dir:
            from pathlib import Path
            from constraints.agnosticv_loader import load_all_constraints
            all_constraints = load_all_constraints(Path(agv_dir))
            if all_constraints:
                sources_found.append("agnosticv")
                for item in items:
                    name = item["name"].lower().replace("-", "").replace("_", "")
                    for slug, constraints in all_constraints.items():
                        if slug.lower().replace("-", "").replace("_", "") == name:
                            item["complexity"] = compute_complexity_score(constraints)
                            break
    except Exception:
        pass

    active = [i for i in items if not i.get("disabled")]
    by_category = {}
    for i in items:
        cat = i.get("category") or "uncategorized"
        by_category[cat] = by_category.get(cat, 0) + 1

    result = {
        "total": len(items),
        "active": len(active),
        "disabled": len(items) - len(active),
        "by_category": by_category,
        "sources": sources_found,
        "items": items,
    }
    _catalog_cache["data"] = result
    _catalog_cache["ts"] = time.time()
    return result
