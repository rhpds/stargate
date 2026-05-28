"""Dashboard router — deployment overview, cluster health, lab detail, pipeline, trends,
provisioning, remediation, and all other /dashboard/* endpoints."""

import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from db.database import get_db
from db import repository
import api.routers._shared as _shared
from api.routers._shared import (
    _event_bus,
    _load_latest_scan,
    _load_latest_babylon,
    _fetch_labagator_labs,
    _fetch_labagator_sessions,
    _fetch_demolition_sessions,
    _scan_to_worker_format,
    _load_agnosticv_constraints,
    _get_lab_namespaces,
    limiter,
    require_admin,
    PIPELINE_STAGES,
    _deployments_cache,
    _FILE_CACHE_TTL,
)

router = APIRouter()


def _get_lab_constraint_violations(lab_code: str, constraints: Dict) -> List[Dict]:
    """Get constraint violations for a specific lab."""
    if not constraints:
        return []
    try:
        from constraints.classifier import classify_constraints
        violations = classify_constraints(constraints, {"lab_code": lab_code})
        return [
            {"type": v.violation_type, "expected": v.expected, "actual": v.actual,
             "severity": v.severity, "detail": v.detail}
            for v in (violations or [])
        ]
    except Exception:
        return []


def _get_aap_summary_for_evidence() -> str:
    """Get AAP SLI summary for LLM evidence bundles."""
    try:
        from collectors.aap.collect_aap import collect_aap_jobs
        aap = collect_aap_jobs()
        s = aap.get("summary", {})
        lines = [
            f"Provision SLI: {s.get('provision_sli', 0)}% (target {s.get('provision_sli_target', 93)}%)",
            f"Overall success rate: {s.get('success_rate', 0)}%",
            f"Failed jobs (24h): {s.get('failed_24h', 0)}",
            f"Total jobs (24h): {s.get('total_jobs', 0)}",
        ]
        by_lab = aap.get("by_lab", {})
        if by_lab:
            top_labs = sorted(by_lab.items(), key=lambda x: -x[1]["total"])[:5]
            lines.append("Top failing labs:")
            for lab, info in top_labs:
                lines.append(f"  {lab}: {info['total']} failures ({info.get('top_error', '')})")
        return "\n".join(lines)
    except Exception:
        return "AAP data unavailable"


def _get_capacity_evidence_for_summary(db=None) -> str:
    """Get capacity, sandbox-api, and zerotouch evidence for executive summary."""
    sections = []
    try:
        from engine.pool_velocity import compute_pool_velocity
        from db.repository import get_pool_timeline
        babylon = _load_latest_babylon()
        if babylon and db:
            depleting = []
            for pname in list(babylon.get("pools", {}).keys())[:15]:
                timeline = get_pool_timeline(db, pname, hours=6)
                if timeline:
                    vel = compute_pool_velocity(timeline)
                    if vel["trend"] == "depleting":
                        depleting.append(f"  {pname}: {vel['handles_per_hour']:.1f} handles/hr, available={timeline[-1]['available']}")
            if depleting:
                sections.append("### Pool Velocity\n" + "\n".join(depleting))
    except Exception:
        pass

    try:
        from engine.workload_complexity import compute_complexity_score
        from constraints.agnosticv_loader import load_all_constraints
        import os
        agv_dir = os.environ.get("STARGATE_AGNOSTICV_DIR", "")
        if agv_dir:
            from pathlib import Path
            all_c = load_all_constraints(Path(agv_dir))
            scored = [(slug, compute_complexity_score(c)) for slug, c in list(all_c.items())[:30]]
            top = sorted(scored, key=lambda x: -x[1]["score"])[:5]
            if top:
                lines = [f"  {s}: score={sc['score']:.2f}, est {sc['estimated_provision_minutes']}min" for s, sc in top]
                sections.append("### Most Complex Labs\n" + "\n".join(lines))
    except Exception:
        pass

    try:
        from collectors.sandbox_api.collect_sandbox_api import summarize_sandbox_api
        scans = _load_latest_scan() or []
        sapi = summarize_sandbox_api(scanner_data=scans)
        status = "HEALTHY" if sapi.get("api_healthy") else "DEGRADED"
        sections.append(f"### Sandbox-API Health\nStatus: {status}, Replicas: {sapi.get('replicas_ready', 0)}/{sapi.get('replicas_desired', 0)}, Active sandboxes: {sapi.get('active', 0)}, Failing: {sapi.get('failing', 0)}")
    except Exception:
        pass

    try:
        from collectors.zerotouch.collect_zerotouch import summarize_zerotouch
        zt = summarize_zerotouch()
        if zt.get("available"):
            sections.append(f"### ZeroTouch\nCatalog: {zt.get('catalog_active', 0)} active items, Workshops: {zt.get('workshop_count', 0)}")
    except Exception:
        pass

    return "\n\n".join(sections) if sections else ""


def _compute_next_action(lab: Dict) -> Dict:
    """Determine the most urgent next action for a lab."""
    if lab.get("aap_provision_failures", 0) > 0:
        return {"action": "Fix provisioning", "urgency": "critical", "detail": f"{lab['aap_provision_failures']} AAP job(s) failing: {lab.get('aap_top_error', 'check Tower')}"}
    if lab.get("instances_failed", 0) > 0:
        return {"action": "Clean stuck instances", "urgency": "critical", "detail": f"{lab['instances_failed']} instance(s) in failed state"}
    if lab.get("sessions", 0) > 0 and lab.get("instances_started", 0) == 0 and lab.get("provisioned", 0) == 0 and lab.get("capacity", 0) == 0:
        return {"action": "Allocate pool", "urgency": "critical", "detail": f"{lab['sessions']} session(s) scheduled, no provisioning"}
    if lab.get("demolition_status") == "fail":
        failed = lab.get("demolition_failed", 0)
        total = lab.get("demolition_total", 0)
        return {"action": "Fix smoke test", "urgency": "high", "detail": f"{failed}/{total} tests failing"}
    if lab.get("labagator_status") == "planning":
        return {"action": "Move to development", "urgency": "medium", "detail": "Still in planning phase"}
    if lab.get("sessions", 0) > 0 and lab.get("provisioned", 0) == 0 and lab.get("capacity", 0) == 0:
        return {"action": "Configure pool", "urgency": "medium", "detail": "Sessions exist but no pool allocated"}
    if lab.get("demolition_status") == "none" and lab.get("sessions", 0) > 0:
        return {"action": "Run smoke test", "urgency": "low", "detail": "No smoke test results yet"}
    return {"action": None, "urgency": None, "detail": "On track"}


def _get_schedule_status(session_dates: List[str]) -> str:
    """Determine lab schedule status: active, completed, upcoming, or no_sessions."""
    if not session_dates:
        return "no_sessions"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    has_past = any(d < today for d in session_dates)
    has_today = any(d == today for d in session_dates)
    has_future = any(d > today for d in session_dates)
    if has_today:
        return "active"
    if has_future:
        return "upcoming"
    if has_past:
        return "completed"
    return "no_sessions"


# ---------------------------------------------------------------------------
# Summit overview
# ---------------------------------------------------------------------------

@router.get("/dashboard/deployments")
@router.get("/dashboard/labs")
@router.get("/dashboard/summit")
def dashboard_summit(db: Session = Depends(get_db), include_all: bool = False):
    """Lab overview — all labs with combined status from Labagator + Babylon + StarGate.

    Accessible via /dashboard/labs (primary) or /dashboard/summit (backward compat).
    Groups by demo_id (actual lab type), not by individual namespace instance.
    Excludes warning-level failure classes (guest_agent_not_connected,
    health_check_failed) from failure counts — these are tuned as optional.

    By default, event-specific labs (ci_name starting with 'summit-') are excluded
    in continuous ops mode. Pass ?include_all=true to show them.
    """
    if not include_all and _deployments_cache["data"]:
        age = time.time() - _deployments_cache["ts"]
        if age < _FILE_CACHE_TTL:
            return _deployments_cache["data"]
        if age < _FILE_CACHE_TTL * 5:
            import threading
            if not _deployments_cache.get("_refreshing"):
                _deployments_cache["_refreshing"] = True
                def _bg():
                    try:
                        dashboard_summit(db=db, include_all=False)
                    except Exception:
                        pass
                    finally:
                        _deployments_cache["_refreshing"] = False
                threading.Thread(target=_bg, daemon=True).start()
            return _deployments_cache["data"]

    import ssl
    import urllib.request as urllib_req

    WARNING_CLASSES = {"guest_agent_not_connected", "health_check_failed"}

    # Pull from Labagator — cached API call (60s TTL)
    labagator_labs = _fetch_labagator_labs()
    labagator_available = len(labagator_labs) > 0

    labagator_by_code: Dict[str, Dict] = {}
    sessions_by_lab: Dict[str, int] = {}
    attendees_by_lab: Dict[str, int] = {}
    days_by_lab: Dict[str, List[str]] = {}

    EVENT_DAY_MAP: Dict[str, str] = {}

    session_dates_by_lab: Dict[str, List[str]] = {}

    if labagator_available:
        labagator_by_code = {l["lab_code"]: l for l in labagator_labs if l.get("lab_code")}
        labagator_sessions = _fetch_labagator_sessions()
        for s in labagator_sessions:
            code = s.get("lab_code", "")
            sessions_by_lab[code] = sessions_by_lab.get(code, 0) + 1
            attendees_by_lab[code] = attendees_by_lab.get(code, 0) + (s.get("attendees") or 0)
            sdate = s.get("session_date", "")
            if sdate and code:
                session_dates_by_lab.setdefault(code, []).append(sdate)
            day = EVENT_DAY_MAP.get(sdate)
            if day and code:
                if code not in days_by_lab:
                    days_by_lab[code] = []
                if day not in days_by_lab[code]:
                    days_by_lab[code].append(day)
    else:
        # Fallback: load from most recent cached Babylon scan
        scan_dir = Path(__file__).parent.parent.parent / "scan-history"
        babylon_files = sorted(scan_dir.glob("babylon-*.json"), reverse=True)
        if babylon_files:
            try:
                with open(babylon_files[0]) as f:
                    cached = json.load(f)
                cached_labs = cached.get("labagator", {}).get("labs_by_code", {})
                for code, lab_data in cached_labs.items():
                    labagator_by_code[code] = {
                        "lab_code": code,
                        "title": lab_data.get("title", ""),
                        "status": lab_data.get("status", ""),
                        "cloud": lab_data.get("cloud", ""),
                        "deploy_mode": lab_data.get("deploy_mode", ""),
                        "ci_name": lab_data.get("ci_name"),
                    }
                    sessions_by_lab[code] = lab_data.get("session_count", 0)
            except Exception:
                pass

    # Build StarGate evaluation stats grouped by lab_code — use materialized view for speed
    from db.models import MVLabEvalSummary
    lab_eval_summaries = db.query(MVLabEvalSummary).all()
    sg_by_lab: Dict[str, Dict] = {}
    for s in lab_eval_summaries:
        if not s.lab_code:
            continue
        if s.lab_code not in sg_by_lab:
            sg_by_lab[s.lab_code] = {
                "pass": 0, "fail": 0, "warn": 0, "total": 0,
                "real_fail": 0, "failure_classes": {},
                "clusters": set(), "last_evaluated": None,
            }
        entry = sg_by_lab[s.lab_code]
        entry["pass"] += s.passed
        entry["fail"] += s.failed
        entry["warn"] += s.warned
        entry["total"] += s.total_evals
        entry["real_fail"] += s.failed
        if s.top_failure_class:
            entry["failure_classes"][s.top_failure_class] = entry["failure_classes"].get(s.top_failure_class, 0) + s.failed
        if s.cluster_name:
            entry["clusters"].add(s.cluster_name)
        if s.last_evaluated_at and (not entry["last_evaluated"] or s.last_evaluated_at > entry["last_evaluated"]):
            entry["last_evaluated"] = s.last_evaluated_at

    CATALOG_TO_DEMO = {
        "zt-rhelbu": "zt-rhel",
        "zt-ansiblebu": "zt-ansible",
        "zt-hpbu": "zt-rhel",
        "ocp4-cluster": "ocp4-cluster",
        "openshift-cnv": "ocp4-cluster",
    }

    def _resolve_demo_id(ci_name: str) -> Optional[str]:
        if not ci_name:
            return None
        base = ci_name.split(".")[0] if "." in ci_name else ci_name
        return CATALOG_TO_DEMO.get(base)

    # Build pools summary from materialized lab eval data
    pools: Dict[str, Dict] = {}
    for lab_code, sg in sg_by_lab.items():
        effective_total = sg["total"]
        if effective_total == 0:
            continue
        effective_pass = sg["pass"] + sg["warn"]
        clusters = sorted(sg.get("clusters", set()) - {""})
        real_fails = sg.get("real_fail", 0)
        pools[lab_code] = {
            "pool": lab_code,
            "health": round(effective_pass / effective_total * 100, 1) if effective_total > 0 else None,
            "evaluations": effective_total,
            "passed": sg["pass"],
            "failed": real_fails,
            "warned": sg["warn"],
            "instances": 0,
            "clusters": clusters,
            "top_failure_class": max(sg.get("failure_classes", {}), key=sg["failure_classes"].get) if sg.get("failure_classes") else None,
            "failure_classes": {k: v for k, v in sg.get("failure_classes", {}).items()},
        }

    # Demolition status per lab — cached API call (60s TTL)
    demolition_by_lab: Dict[str, Dict] = {}
    try:
        all_demo = _fetch_demolition_sessions()
        all_demo = sorted(all_demo, key=lambda s: s.get("id", 0), reverse=True)

        for code in labagator_by_code:
            code_lower = code.lower()
            ci = labagator_by_code[code].get("ci_name") or ""
            ci_slug = ci.split(".", 1)[1] if "." in ci else ""
            code_pattern = re.compile(rf'(?:^|[\s.\-_:])({re.escape(code_lower)})(?:[\s.\-_:]|$)')
            matches = []
            for s in all_demo:
                sname = (s.get("name") or "").lower()
                if code_pattern.search(sname) or (ci_slug and ci_slug.lower() in sname):
                    result = s.get("last_result") or {}
                    total = result.get("total", 0) or s.get("workers", 0) or 0
                    matches.append({"session": s, "result": result, "total": total})

            if not matches:
                continue

            # Pick the most recent large test (>10 workers), fall back to most recent any
            best = None
            for m in matches:
                if m["total"] > 10:
                    best = m
                    break
            if not best:
                best = matches[0]

            result = best["result"]
            failed = result.get("failed", 0)
            completed = result.get("completed", 0)
            total = result.get("total", 0)
            status = "none"
            if completed > 0 and failed == 0:
                status = "pass"
            elif failed > 0:
                status = "fail"
            elif best["session"].get("status") == "completed":
                status = "pass"

            demolition_by_lab[code] = {
                "status": status,
                "completed": completed,
                "failed": failed,
                "total": total,
            }
    except Exception:
        pass

    # Map pool names to LB codes for per-lab provisioning data
    # Pool name: prefix.lb1208-type.event → LB1208
    babylon = _load_latest_babylon()
    all_pools_raw = babylon.get("pools", {}).get("all_pools", babylon.get("pools", {}).get("summit_pools", []))
    lab_pool_data: Dict[str, Dict] = {}
    for sp in all_pools_raw:
        name = sp.get("name", "")
        parts = name.split(".")
        if len(parts) > 1 and parts[1].startswith("lb"):
            lb_num = parts[1].split("-")[0].upper()  # lb1208 → LB1208
            if lb_num not in lab_pool_data:
                lab_pool_data[lb_num] = {"pool_count": 0, "available": 0, "ready": 0, "min": 0, "pools": []}
            lab_pool_data[lb_num]["pool_count"] += 1
            lab_pool_data[lb_num]["available"] += sp.get("available", 0)
            lab_pool_data[lb_num]["ready"] += sp.get("ready", 0)
            lab_pool_data[lb_num]["min"] += sp.get("min", 0)
            lab_pool_data[lb_num]["pools"].append(name)

    # Instance mapping from Babylon AnarchySubjects
    summit_mapping = babylon.get("instance_mapping", babylon.get("summit_mapping", {}))

    # Build labs list — filter junk entries and merge sub-labs
    JUNK_PATTERNS = {"stuff", "healing", "ai_driven", "published.", "satbasics"}
    seen_titles: Dict[str, str] = {}
    parent_codes = set()

    labs = []
    for code in sorted(labagator_by_code.keys()):
        # Skip junk/test entries
        if any(code.lower().startswith(p) or code.lower() == p for p in JUNK_PATTERNS):
            continue
        if code.startswith("-"):
            continue

        # Skip sub-lab entries (LB1577-1 thru -5) if parent exists
        if "-" in code:
            base = code.rsplit("-", 1)[0]
            if base in labagator_by_code:
                continue

        # Skip duplicate titles (LNL3352 vs LB3352)
        title = labagator_by_code[code].get("title", "")
        if title in seen_titles:
            continue
        if title:
            seen_titles[title] = code
        lg = labagator_by_code[code]
        ci_name = lg.get("ci_name") or ""
        demo_id = _resolve_demo_id(ci_name)

        # Per-lab pool capacity from summit pools
        lpd = lab_pool_data.get(code, {})

        labs.append({
            "lab_code": code,
            "title": lg.get("title", ""),
            "labagator_status": lg.get("status", ""),
            "cloud": lg.get("cloud", ""),
            "deploy_mode": lg.get("deploy_mode", ""),
            "ci_name": ci_name,
            "pool": demo_id,
            "sessions": sessions_by_lab.get(code, 0),
            "provisioned": lpd.get("ready", 0),
            "capacity": lpd.get("min", 0),
            "pool_available": lpd.get("available", 0),
            "pool_count": lpd.get("pool_count", 0),
            "total_attendees": attendees_by_lab.get(code, 0),
            "demolition_status": demolition_by_lab.get(code, {}).get("status", "none"),
            "demolition_completed": demolition_by_lab.get(code, {}).get("completed", 0),
            "demolition_failed": demolition_by_lab.get(code, {}).get("failed", 0),
            "demolition_total": demolition_by_lab.get(code, {}).get("total", 0),
            "instances": summit_mapping.get(code, []),
            "instances_started": sum(1 for i in summit_mapping.get(code, []) if i.get("state") == "started"),
            "instances_total": len(summit_mapping.get(code, [])),
            "summit_days": sorted(days_by_lab.get(code, [])),
            "session_dates": sorted(set(session_dates_by_lab.get(code, []))),
            "schedule_status": _get_schedule_status(session_dates_by_lab.get(code, [])),
            "agnosticv_tags": [],
            "agnosticv_timeout": None,
            "agnosticv_config": None,
            "instances_failed": sum(1 for i in summit_mapping.get(code, []) if "failed" in i.get("state", "") or "error" in i.get("state", "")),
            "instances_destroying": sum(1 for i in summit_mapping.get(code, []) if i.get("state") in ("destroying", "destroy-pending")),
            "last_scanned": None,
            "aap_provision_failures": 0,
            "aap_top_error": "",
        })
        labs[-1]["next_action"] = _compute_next_action(labs[-1])

    # Enrich with AAP provisioning data (use cached, don't block page load)
    try:
        if not hasattr(_shared, '_aap_cache'):
            _shared._aap_cache = {"data": {}, "ts": 0.0}
        if time.time() - _shared._aap_cache["ts"] < 300:
            aap = _shared._aap_cache["data"]
        else:
            import threading
            def _bg_aap():
                try:
                    from collectors.aap.collect_aap import collect_aap_jobs
                    _shared._aap_cache["data"] = collect_aap_jobs()
                    _shared._aap_cache["ts"] = time.time()
                except Exception:
                    pass
            threading.Thread(target=_bg_aap, daemon=True).start()
            aap = _shared._aap_cache["data"]
        aap_by_lab = aap.get("by_lab", {})
        for lab in labs:
            code = lab["lab_code"]
            if code in aap_by_lab:
                lab["aap_provision_failures"] = aap_by_lab[code].get("total", 0)
                lab["aap_top_error"] = aap_by_lab[code].get("top_error", "")
                lab["next_action"] = _compute_next_action(lab)
    except Exception:
        pass

    # Add AgnosticV tags and lifecycle data
    all_constraints = {}
    try:
        import os as _os
        agv_dir = _os.environ.get("STARGATE_AGNOSTICV_DIR", "")
        agnosticv_dir = Path(agv_dir) if agv_dir else Path(__file__).parent.parent.parent / "github review" / "agnosticv"
        if agnosticv_dir.exists():
            from constraints.agnosticv_loader import load_all_constraints
            all_constraints = load_all_constraints(agnosticv_dir)
            if all_constraints:
                from api.contracts import record_source_fetch
                record_source_fetch("agnosticv")
    except Exception:
        pass

    for lab in labs:
        ci_name = lab.get("ci_name", "")
        if ci_name:
            # Try multiple slug patterns to match AgnosticV directory names
            slug = ci_name.split(".", 1)[1] if "." in ci_name else ci_name
            constraints = all_constraints.get(slug)
            if not constraints:
                constraints = all_constraints.get(ci_name)
            if not constraints:
                # Try partial match for catalog items like zt-insights-vulnerability
                for key in all_constraints:
                    if slug in key or key in slug:
                        constraints = all_constraints[key]
                        break
            if isinstance(constraints, dict):
                lab["agnosticv_tags"] = constraints.get("keywords", [])
                lab["agnosticv_timeout"] = constraints.get("timeout_seconds")
                lab["agnosticv_config"] = constraints.get("config")

    # Add last_scanned timestamps — check evaluations, demolition, and babylon mapping
    from db.models import EvaluationRecord
    from db.models import RunRecord as _ScanRunRecord

    # Get most recent evaluation per demo_id (since scanner uses demo_id, not lab code)
    last_eval_by_demo: Dict[str, str] = {}
    latest_evals = (
        db.query(_ScanRunRecord.demo_id, EvaluationRecord.evaluated_at)
        .join(EvaluationRecord, EvaluationRecord.run_id == _ScanRunRecord.run_id)
        .filter(EvaluationRecord.evaluated_at.isnot(None))
        .order_by(EvaluationRecord.evaluated_at.desc())
        .limit(1000)
        .all()
    )
    for demo_id, eval_at in latest_evals:
        if demo_id and demo_id not in last_eval_by_demo and eval_at:
            last_eval_by_demo[demo_id] = eval_at.isoformat()

    # Also check direct lab_code matches and cluster-health scans
    last_scan_direct: Dict[str, str] = {}
    direct_evals = (
        db.query(EvaluationRecord.lab_code, EvaluationRecord.evaluated_at)
        .filter(EvaluationRecord.lab_code.isnot(None), EvaluationRecord.evaluated_at.isnot(None))
        .order_by(EvaluationRecord.evaluated_at.desc())
        .limit(500)
        .all()
    )
    for lab_code, eval_at in direct_evals:
        if lab_code and lab_code not in last_scan_direct:
            last_scan_direct[lab_code] = eval_at.isoformat()

    for lab in labs:
        code = lab["lab_code"]
        pool = lab.get("pool")
        ci_name = lab.get("ci_name", "")
        pool = lab.get("pool")

        # Try direct match
        scanned = last_scan_direct.get(code)

        # Try demo_id match via pool
        if not scanned and pool:
            scanned = last_eval_by_demo.get(pool)

        # Try ci_name slug match against demo_ids
        if not scanned and ci_name:
            slug = ci_name.split(".", 1)[1] if "." in ci_name else ci_name
            for demo_id, ts in last_eval_by_demo.items():
                if slug in demo_id or demo_id in slug:
                    scanned = ts
                    break

        # Try matching any demo_id that contains the ci_name base
        if not scanned and ci_name:
            base = ci_name.split(".")[0] if "." in ci_name else ci_name
            for demo_id, ts in last_eval_by_demo.items():
                if base in demo_id:
                    scanned = ts
                    break

        # Check AnarchySubject instances for cluster-health scans
        if not scanned:
            instances = summit_mapping.get(code, [])
            for inst in instances:
                cluster = inst.get("cluster", "")
                if cluster:
                    cluster_scan = last_scan_direct.get(cluster)
                    if cluster_scan:
                        scanned = cluster_scan
                        break

        # Fallback: demolition test exists = data was collected
        if not scanned:
            demo = demolition_by_lab.get(code, {})
            if demo:
                scanned = datetime.now(timezone.utc).isoformat()

        # Fallback: babylon mapping exists = instances were checked
        if not scanned and summit_mapping.get(code):
            scanned = datetime.now(timezone.utc).isoformat()

        lab["last_scanned"] = scanned

    labs.sort(key=lambda l: l["lab_code"])

    from api.routers._shared import EVENT_PREFIX
    if not include_all and not EVENT_PREFIX:
        labs = [l for l in labs if not (l.get("ci_name") or "").startswith("summit-")]

    total = len(labs)
    provisioned_count = sum(1 for l in labs if l["provisioned"] > 0)
    with_sessions = sum(1 for l in labs if l["sessions"] > 0)

    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_labs": total,
        "provisioned_count": provisioned_count,
        "with_sessions": with_sessions,
        "labagator_available": labagator_available,
        "pools": pools,
        "labs": labs,
    }
    if not include_all:
        _deployments_cache["data"] = result
        _deployments_cache["ts"] = time.time()
    return result


# ---------------------------------------------------------------------------
# Clusters
# ---------------------------------------------------------------------------

@router.get("/dashboard/clusters")
def dashboard_clusters(db: Session = Depends(get_db)):
    """All clusters at a glance — CPU, VMs, health rate, events."""
    clusters_to_check = ["ocpv05", "ocpv06", "ocpv07", "ocpv08", "ocpv09", "ocpv10",
                         "ocpv-infra01", "ocpv-infra02", "ocp-us-east-1"]

    cluster_data = []
    for cluster in clusters_to_check:
        summary = repository.get_cluster_failure_summary(db, cluster)

        # Get recent events for this cluster
        cluster_events = [
            e for e in _event_bus.history
            if e.cluster_name == cluster
        ]
        recent_failures = sum(1 for e in cluster_events if e.outcome == "fail" and not e.filtered)
        systemic = sum(1 for e in cluster_events if e.systemic)

        cluster_data.append({
            "cluster": cluster,
            "total_evaluations": summary["total_evaluations"],
            "passed": summary["passed"],
            "failed": summary["failed"],
            "warned": summary["warned"],
            "health_rate": summary["health_rate"],
            "failure_classes": summary["failure_classes"],
            "labs_seen": summary["labs_seen"],
            "labs_failing": summary["labs_failing"],
            "recent_failure_events": recent_failures,
            "systemic_events": systemic,
        })

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "clusters": cluster_data,
    }


# ---------------------------------------------------------------------------
# Lab detail
# ---------------------------------------------------------------------------

@router.get("/dashboard/lab/{lab_code}")
def dashboard_lab(lab_code: str, db: Session = Depends(get_db)):
    """Single lab deep dive — evaluation history, constraints, sessions."""
    import ssl
    import urllib.request as urllib_req

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # StarGate evaluations — try direct lab_code match first, then namespace mapping
    from db.models import EvaluationRecord as _ER
    history = repository.get_evaluation_history(db, lab_code=lab_code, limit=50)
    failures = repository.get_failure_class_frequency(db, lab_code=lab_code)
    last_pass = repository.get_last_passing_run(db, lab_code=lab_code)

    if not history:
        lab_ns = _get_lab_namespaces(lab_code)
        for ns_ref in lab_ns:
            if ns_ref.startswith("demo:"):
                demo_id = ns_ref[5:]
                from db.models import RunRecord as _RR
                matching_runs = db.query(_RR).filter(_RR.demo_id == demo_id).all()
                run_ids = [r.run_id for r in matching_runs]
                if run_ids:
                    evals = db.query(_ER).filter(_ER.run_id.in_(run_ids)).order_by(_ER.id.desc()).limit(50).all()
                    history = [
                        {"run_id": e.run_id, "stage_id": e.stage_id, "outcome": e.outcome,
                         "failure_class": e.failure_class, "message": e.message,
                         "evaluated_at": e.evaluated_at.isoformat() if e.evaluated_at else None,
                         "cluster_name": e.cluster_name}
                        for e in evals
                    ]
                    for e in evals:
                        fc = e.failure_class or "unclassified"
                        if e.outcome == "fail":
                            failures[fc] = failures.get(fc, 0) + 1
                    if not last_pass:
                        passing = [e for e in evals if e.outcome == "pass"]
                        if passing:
                            p = passing[0]
                            last_pass = {"run_id": p.run_id, "stage_id": p.stage_id,
                                         "evaluated_at": p.evaluated_at.isoformat() if p.evaluated_at else None,
                                         "cluster_name": p.cluster_name}
                    break

    # Labagator data — cached API calls (60s TTL)
    # (loaded before AgnosticV so ci_name is available for slug matching)
    labagator_lab = None
    labagator_sessions = []
    try:
        all_labs = _fetch_labagator_labs()
        for l in all_labs:
            if l.get("lab_code") == lab_code:
                labagator_lab = {
                    "title": l.get("title"),
                    "status": l.get("status"),
                    "cloud": l.get("cloud"),
                    "deploy_mode": l.get("deploy_mode"),
                    "ci_name": l.get("ci_name"),
                    "lead_developer": l.get("lead_developer"),
                    "rhdp_developer": l.get("rhdp_developer"),
                    "ops_assigned": l.get("ops_assigned"),
                }
                break

        all_sessions = _fetch_labagator_sessions()
        labagator_sessions = [
            {
                "session_date": s.get("session_date"),
                "start_time": s.get("start_time"),
                "end_time": s.get("end_time"),
                "room": s.get("room"),
                "attendees": s.get("attendees"),
                "status": s.get("status"),
            }
            for s in all_sessions if s.get("lab_code") == lab_code
        ]
    except Exception:
        pass

    # Demolition results — cached API call (60s TTL)
    demolition_sessions = []
    try:
        all_demo = _fetch_demolition_sessions()
        for s in all_demo:
            name = s.get("name", "").lower()
            if lab_code.lower() in name:
                result = s.get("last_result") or {}
                demolition_sessions.append({
                    "id": s.get("id"),
                    "name": s.get("name", "")[:80],
                    "status": s.get("status"),
                    "workers": s.get("worker_count"),
                    "completed": result.get("completed", 0),
                    "failed": result.get("failed", 0),
                    "total": result.get("total", 0),
                })
    except Exception:
        pass

    # Recent events
    lab_events = [
        e.to_dict() for e in _event_bus.history
        if e.lab_code and lab_code.lower() in e.lab_code.lower()
    ][-10:]

    ci_name = labagator_lab.get("ci_name") if labagator_lab else None
    constraints = _load_agnosticv_constraints(lab_code, ci_name=ci_name)

    return {
        "lab_code": lab_code,
        "labagator": labagator_lab,
        "labagator_sessions": labagator_sessions,
        "stargate": {
            "evaluation_count": len(history),
            "history": history,
            "failure_classes": failures,
            "last_passing_run": last_pass,
            "proposed_classifications": repository.get_proposed_classifications(db, lab_code=lab_code, limit=20),
        },
        "demolition": demolition_sessions,
        "constraints": constraints,
        "constraint_violations": _get_lab_constraint_violations(lab_code, constraints),
        "recent_events": lab_events,
    }


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------

@router.get("/dashboard/overview")
def dashboard_overview(db: Session = Depends(get_db)):
    """Unified summary stats for all dashboard views."""
    from db.models import EvaluationRecord

    WARNING_CLASSES = {"guest_agent_not_connected", "health_check_failed"}

    # Lab stats from Labagator cache — filtered to match labs page
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

    # Cluster stats — prefer live workers, fall back to scan files
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

    # Pool stats from Babylon cache
    pools_data = babylon.get("pools", {})
    total_pools = pools_data.get("total_pools", 0)
    exhausted = len(pools_data.get("exhausted", []))
    low = len(pools_data.get("low", []))

    # Provisioning stats
    prov = babylon.get("provisioning", {})
    summit_prov = prov

    # Error stats from DB
    all_evals = db.query(EvaluationRecord).filter(EvaluationRecord.outcome == "fail").all()
    real_failures = [e for e in all_evals if (e.failure_class or "unclassified") not in WARNING_CLASSES]
    failure_classes: Dict[str, int] = {}
    for e in real_failures:
        fc = e.failure_class or "unclassified"
        failure_classes[fc] = failure_classes.get(fc, 0) + 1
    top_class = max(failure_classes, key=failure_classes.get) if failure_classes else None

    # Systemic from event bus
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
# Pools
# ---------------------------------------------------------------------------

@router.get("/dashboard/pools")
def dashboard_pools():
    """Pool capacity and provisioning state from Babylon cache — all pools."""
    babylon = _load_latest_babylon()
    pools_data = babylon.get("pools", {})
    prov = babylon.get("provisioning", {})

    exhausted_names = {p.get("name") for p in pools_data.get("exhausted", []) if isinstance(p, dict)}
    low_names = {p.get("name") for p in pools_data.get("low", []) if isinstance(p, dict)}

    all_pools_raw = pools_data.get("all_pools", pools_data.get("summit_pools", []))

    pool_list = []
    for p in all_pools_raw:
        if not isinstance(p, dict):
            continue
        name = p.get("name", "")
        if not name:
            continue
        avail = p.get("available", 0)
        mn = p.get("min", 0)
        if name in exhausted_names or (avail == 0 and mn > 0):
            status = "exhausted"
        elif name in low_names or (avail <= 1 and mn > 0):
            status = "low"
        else:
            status = "healthy"
        pool_list.append({
            "name": name,
            "available": avail,
            "ready": p.get("ready", 0),
            "min": mn,
            "status": status,
            "is_summit": p.get("is_summit", "summit-2026" in name),
        })

    instance_mapping = babylon.get("instance_mapping", babylon.get("summit_mapping", {}))
    labs_by_pool: Dict[str, set] = {}
    for lc, instances in instance_mapping.items():
        for inst in instances:
            pool_name = inst.get("pool_name", "")
            if pool_name:
                labs_by_pool.setdefault(pool_name, set()).add(lc)

    for pool in pool_list:
        consuming = labs_by_pool.get(pool["name"], set())
        pool["consuming_labs"] = sorted(consuming)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_pools": pools_data.get("total_pools", len(pool_list)),
        "pools": pool_list,
        "summit_pools": pool_list,
        "provisioning": {
            "total": prov.get("total", 0),
            "started": prov.get("started", 0),
            "failed": prov.get("failed", 0),
            "failure_rate": prov.get("failure_rate", 0),
            "by_state": prov.get("by_state", {}),
        },
    }


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------

@router.get("/dashboard/trends")
def dashboard_trends(
    hours: int = 24,
    bucket_minutes: int = 60,
    db: Session = Depends(get_db),
):
    """Time-bucketed evaluation and cluster health trends."""
    from db.models import EvaluationRecord

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    evals = (
        db.query(EvaluationRecord)
        .filter(EvaluationRecord.evaluated_at >= cutoff)
        .order_by(EvaluationRecord.evaluated_at)
        .all()
    )

    buckets: Dict[str, Dict] = {}
    for ev in evals:
        ts = ev.evaluated_at
        if ts is None:
            continue
        bucket_key = ts.replace(
            minute=(ts.minute // bucket_minutes) * bucket_minutes,
            second=0, microsecond=0,
        ).isoformat()
        if bucket_key not in buckets:
            buckets[bucket_key] = {"pass": 0, "fail": 0, "warn": 0}
        b = buckets[bucket_key]
        if ev.outcome == "pass":
            b["pass"] += 1
        elif ev.outcome == "fail":
            b["fail"] += 1
        elif ev.outcome == "warn":
            b["warn"] += 1

    evaluation_trend = []
    for ts_key in sorted(buckets):
        b = buckets[ts_key]
        total = b["pass"] + b["fail"] + b["warn"]
        evaluation_trend.append({
            "timestamp": ts_key,
            "pass": b["pass"],
            "fail": b["fail"],
            "warn": b["warn"],
            "health_rate": round((b["pass"] + b["warn"]) / max(total, 1) * 100, 1),
        })

    # Cluster health from scan-history files
    scan_dir = Path(__file__).parent.parent.parent / "scan-history"
    cluster_health_trend = []
    for scan_file in sorted(scan_dir.glob("scan-*.json")):
        try:
            fname = scan_file.stem
            file_ts = datetime.strptime(fname, "scan-%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
            if file_ts < cutoff:
                continue
            with open(scan_file) as f:
                scans = json.load(f)
            for s in scans:
                cluster_health_trend.append({
                    "timestamp": file_ts.isoformat(),
                    "cluster": s.get("cluster", ""),
                    "health_rate": s.get("health_rate", 0),
                    "avg_cpu_pct": s.get("avg_cpu_pct", 0),
                })
        except (ValueError, json.JSONDecodeError):
            continue

    # Failure trend
    failure_buckets: Dict[str, Dict[str, int]] = {}
    for ev in evals:
        if ev.outcome != "fail" or not ev.failure_class:
            continue
        ts = ev.evaluated_at
        if ts is None:
            continue
        bucket_key = ts.replace(
            minute=(ts.minute // bucket_minutes) * bucket_minutes,
            second=0, microsecond=0,
        ).isoformat()
        if bucket_key not in failure_buckets:
            failure_buckets[bucket_key] = {}
        fb = failure_buckets[bucket_key]
        fb[ev.failure_class] = fb.get(ev.failure_class, 0) + 1

    failure_trend = []
    for ts_key in sorted(failure_buckets):
        for fc, count in failure_buckets[ts_key].items():
            failure_trend.append({
                "timestamp": ts_key,
                "failure_class": fc,
                "count": count,
            })

    return {
        "evaluation_trend": evaluation_trend,
        "cluster_health_trend": cluster_health_trend,
        "failure_trend": failure_trend,
    }


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

@router.get("/dashboard/nodes/{cluster}")
def dashboard_nodes(cluster: str):
    """Node-level metrics for a cluster from latest scan data."""
    scan_dir = Path(__file__).parent.parent.parent / "scan-history"
    scan_files = sorted(scan_dir.glob("scan-*.json"), reverse=True)
    if not scan_files:
        raise HTTPException(404, "No scan data available")

    with open(scan_files[0]) as f:
        scans = json.load(f)

    cluster_scan = None
    for s in scans:
        if s.get("cluster") == cluster:
            cluster_scan = s
            break
    if not cluster_scan:
        raise HTTPException(404, f"No scan data for cluster {cluster}")

    return {
        "cluster": cluster,
        "timestamp": cluster_scan.get("timestamp"),
        "nodes": cluster_scan.get("nodes", 0),
        "compute_nodes": cluster_scan.get("compute_nodes", 0),
        "avg_cpu_pct": cluster_scan.get("avg_cpu_pct", 0),
        "hot_nodes": cluster_scan.get("hot_nodes", 0),
        "total_vms": cluster_scan.get("total_vms", 0),
        "vms_per_node": cluster_scan.get("vms_per_node", 0),
        "sandbox_active": cluster_scan.get("sandbox_active", 0),
        "sandbox_failing": cluster_scan.get("sandbox_failing", 0),
        "sandbox_crashloop": cluster_scan.get("sandbox_crashloop", 0),
        "ocp4_cluster_labs": cluster_scan.get("ocp4_cluster_labs", 0),
        "health_rate": cluster_scan.get("health_rate", 0),
        "dns_warnings": cluster_scan.get("dns_warnings", 0),
        "status": cluster_scan.get("status", "unknown"),
        "issues": cluster_scan.get("issues", []),
    }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

@router.get("/dashboard/pipeline")
def dashboard_pipeline(
    lab_code: Optional[str] = None,
    cluster_name: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Per-stage pass/fail/warn aggregation across the rubric pipeline."""
    if not lab_code and not cluster_name:
        from db.models import MVPipelineStage
        mv_rows = db.query(MVPipelineStage).all()
        mv_by_stage = {r.stage_id: r for r in mv_rows}
        stages = []
        for i, stage_id in enumerate(PIPELINE_STAGES):
            r = mv_by_stage.get(stage_id)
            if r:
                stages.append({
                    "stage_id": stage_id, "order": i,
                    "pass": r.pass_count, "fail": r.fail_count, "warn": r.warn_count,
                    "total": r.total, "health_rate": r.health_rate,
                })
            else:
                stages.append({
                    "stage_id": stage_id, "order": i,
                    "pass": 0, "fail": 0, "warn": 0, "total": 0, "health_rate": None,
                })
        return {"stages": stages, "lab_code": None, "cluster_name": None}

    from db.models import EvaluationRecord
    query = db.query(EvaluationRecord)
    if lab_code:
        query = query.filter(EvaluationRecord.lab_code == lab_code)
    if cluster_name:
        query = query.filter(EvaluationRecord.cluster_name == cluster_name)
    evals = query.limit(10000).all()

    stage_counts: Dict[str, Dict] = {}
    for ev in evals:
        sid = ev.stage_id
        if sid not in stage_counts:
            stage_counts[sid] = {"pass": 0, "fail": 0, "warn": 0}
        sc = stage_counts[sid]
        if ev.outcome == "pass":
            sc["pass"] += 1
        elif ev.outcome == "fail":
            sc["fail"] += 1
        elif ev.outcome == "warn":
            sc["warn"] += 1

    stages = []
    for i, stage_id in enumerate(PIPELINE_STAGES):
        sc = stage_counts.get(stage_id, {"pass": 0, "fail": 0, "warn": 0})
        total = sc["pass"] + sc["fail"] + sc["warn"]
        stages.append({
            "stage_id": stage_id,
            "order": i,
            "pass": sc["pass"],
            "fail": sc["fail"],
            "warn": sc["warn"],
            "total": total,
            "health_rate": round((sc["pass"] + sc["warn"]) / max(total, 1) * 100, 1) if total > 0 else None,
        })

    return {
        "stages": stages,
        "lab_code": lab_code,
        "cluster_name": cluster_name,
    }


@router.get("/dashboard/pipeline/{stage_id}")
def dashboard_pipeline_stage(stage_id: str, db: Session = Depends(get_db)):
    """Detailed data for a single pipeline stage."""
    from db.models import EvaluationRecord

    evals = (
        db.query(EvaluationRecord)
        .filter(EvaluationRecord.stage_id == stage_id)
        .order_by(EvaluationRecord.id.desc())
        .limit(200)
        .all()
    )

    total = len(evals)
    passed = sum(1 for e in evals if e.outcome == "pass")
    warned = sum(1 for e in evals if e.outcome == "warn")
    failed = sum(1 for e in evals if e.outcome == "fail")

    failure_classes: Dict[str, int] = {}
    clusters_affected: Dict[str, int] = {}
    recent: List[Dict] = []

    for e in evals:
        if e.outcome == "fail":
            fc = e.failure_class or "unclassified"
            failure_classes[fc] = failure_classes.get(fc, 0) + 1
        if e.cluster_name:
            clusters_affected[e.cluster_name] = clusters_affected.get(e.cluster_name, 0) + 1
        if len(recent) < 20:
            recent.append({
                "run_id": e.run_id,
                "outcome": e.outcome,
                "failure_class": e.failure_class,
                "message": e.message,
                "cluster_name": e.cluster_name,
                "lab_code": e.lab_code,
                "evaluated_at": e.evaluated_at.isoformat() if e.evaluated_at else None,
            })

    return {
        "stage_id": stage_id,
        "total": total,
        "passed": passed,
        "warned": warned,
        "failed": failed,
        "health_rate": round((passed + warned) / max(total, 1) * 100, 1),
        "failure_classes": dict(sorted(failure_classes.items(), key=lambda x: -x[1])),
        "clusters_affected": dict(sorted(clusters_affected.items(), key=lambda x: -x[1])),
        "recent_evaluations": recent,
    }


# ---------------------------------------------------------------------------
# Nodes & Pods
# ---------------------------------------------------------------------------

@router.get("/dashboard/nodes-pods")
def dashboard_nodes_pods(db: Session = Depends(get_db)):
    """Node and pod summary across all clusters."""
    scan_data = _load_latest_scan()
    if not scan_data:
        return {"clusters": [], "totals": {}}

    all_cluster_evals = repository.get_all_cluster_summaries(db)

    clusters = []
    total_nodes = 0
    total_compute = 0
    total_vms = 0
    total_sandboxes = 0
    total_failing = 0
    total_crashloops = 0

    for s in scan_data:
        r = _scan_to_worker_format(s)
        n = r["nodes"]
        p = r["pods"]

        nodes_count = n["total_nodes"]
        compute = n["compute_nodes"]
        vms = p["total_vms"]
        active = p["sandbox_active"]
        failing = p["sandbox_failing"]
        crashloops = p["crashloops"]
        ocp4_labs = p["ocp4_labs"]

        total_nodes += nodes_count
        total_compute += compute
        total_vms += vms
        total_sandboxes += active
        total_failing += failing
        total_crashloops += crashloops

        cluster_name = r["cluster"]
        cluster_evals = all_cluster_evals.get(cluster_name, {})

        ns_by_type: Dict[str, int] = {}
        for ns in r["all_sandbox_namespaces"]:
            if "ocp4-cluster" in ns:
                ns_by_type["ocp4-cluster"] = ns_by_type.get("ocp4-cluster", 0) + 1
            elif "zt-rhelbu" in ns:
                ns_by_type["zt-rhel"] = ns_by_type.get("zt-rhel", 0) + 1
            elif "zt-ansiblebu" in ns:
                ns_by_type["zt-ansible"] = ns_by_type.get("zt-ansible", 0) + 1
            elif "zt-hpbu" in ns:
                ns_by_type["zt-hp"] = ns_by_type.get("zt-hp", 0) + 1
            else:
                ns_by_type["other"] = ns_by_type.get("other", 0) + 1

        clusters.append({
            "cluster": cluster_name,
            "status": n["status"],
            "nodes": nodes_count,
            "compute_nodes": compute,
            "avg_cpu": n["avg_cpu"],
            "hot_nodes": n["hot_nodes"],
            "total_vms": vms,
            "vms_per_node": round(vms / max(compute, 1), 1) if compute else 0,
            "sandbox_active": active,
            "sandbox_failing": failing,
            "crashloops": crashloops,
            "ocp4_labs": ocp4_labs,
            "new_failures": len(p["new_failures"]),
            "recovered": len(p["recovered"]),
            "recent_failures": p["new_failures"][:5],
            "sandbox_by_type": ns_by_type,
            "evaluations": {
                "total": cluster_evals.get("total_evaluations", 0),
                "passed": cluster_evals.get("passed", 0),
                "failed": cluster_evals.get("failed", 0),
                "health_rate": cluster_evals.get("health_rate", 0),
                "labs_seen": cluster_evals.get("labs_seen", 0),
                "labs_failing": cluster_evals.get("labs_failing", 0),
                "top_failures": dict(sorted(
                    cluster_evals.get("failure_classes", {}).items(),
                    key=lambda x: -x[1]
                )[:5]),
            },
        })

    return {
        "clusters": sorted(clusters, key=lambda c: c["cluster"]),
        "totals": {
            "nodes": total_nodes,
            "compute_nodes": total_compute,
            "total_vms": total_vms,
            "sandboxes": total_sandboxes,
            "failing": total_failing,
            "crashloops": total_crashloops,
        },
    }


# ---------------------------------------------------------------------------
# Classification proposals
# ---------------------------------------------------------------------------

@router.post("/dashboard/propose-classification")
def propose_classification(req: dict, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Send unclassified failure to Granite LLM and store proposed classification."""
    import urllib.request as urllib_req
    from db.models import EvaluationRecord, ProposedClassification

    run_id = req.get("run_id", "")
    stage_id = req.get("stage_id", "")
    raw_message = req.get("message", "")
    message = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw_message)[:2000]

    # Get the evaluation context
    eval_record = None
    if run_id and stage_id:
        eval_record = (
            db.query(EvaluationRecord)
            .filter(EvaluationRecord.run_id == run_id, EvaluationRecord.stage_id == stage_id)
            .first()
        )

    # Build enriched evidence for LLM
    lab = eval_record.lab_code if eval_record else req.get('lab_code', 'unknown')
    clust = eval_record.cluster_name if eval_record else req.get('cluster', 'unknown')

    evidence_parts = [f"""## Failure Details
- Stage: {stage_id}
- Cluster: {clust}
- Lab/Namespace: {lab}
- Current classification: unclassified

<user_data>
{message or (eval_record.message if eval_record else 'unknown')}
</user_data>"""]

    # Criteria results if available
    if eval_record and eval_record.criteria_results:
        evidence_parts.append(f"## Criteria Results\n{json.dumps(eval_record.criteria_results, indent=2)}")

    # Similar past classifications
    similar = repository.get_similar_classifications(db, message or (eval_record.message if eval_record else ""), limit=5)
    if similar:
        sim_lines = ["## Similar Past Classifications"]
        for s in similar:
            status = "APPROVED" if s["approved"] else "REJECTED" if s["approved"] is False else "pending"
            sim_lines.append(f"- \"{s['original_message']}\" → {s['proposed_class']} (confidence {s['confidence']}, {status}, match {s['match_score']:.0%})")
        evidence_parts.append("\n".join(sim_lines))

    # Lab failure history
    if lab and lab != "unknown":
        lab_freq = repository.get_failure_class_frequency(db, lab_code=lab, limit=50)
        if lab_freq:
            freq_lines = [f"## Lab {lab} Failure History"]
            for fc, ct in sorted(lab_freq.items(), key=lambda x: -x[1])[:8]:
                freq_lines.append(f"- {fc}: {ct} occurrences")
            evidence_parts.append("\n".join(freq_lines))

    # Cluster failure surge
    if clust and clust != "unknown":
        cluster_freq = repository.get_failure_class_frequency(db, cluster_name=clust, limit=50)
        if cluster_freq:
            total_failures = sum(cluster_freq.values())
            freq_lines = [f"## Cluster {clust} Current Failures ({total_failures} total)"]
            for fc, ct in sorted(cluster_freq.items(), key=lambda x: -x[1])[:8]:
                freq_lines.append(f"- {fc}: {ct}")
            evidence_parts.append("\n".join(freq_lines))

    # Load all known failure classes from YAML corpus
    try:
        from engine.failure_class_loader import get_all_classes, reload
        reload()
        all_classes = get_all_classes()
        class_lines = [f"- {name}: {data.get('description', '')}" for name, data in sorted(all_classes.items())]
        evidence_parts.append("## Known Failure Classes ({} total)\n{}".format(len(class_lines), "\n".join(class_lines)))
    except Exception:
        evidence_parts.append("""## Known Failure Classes
- pods_not_ready: deployment exists but pods not running
- pods_crashlooping: pods in CrashLoopBackOff
- deployment_missing: no deployment found in namespace
- route_missing: no route object exists
- namespace_missing: namespace does not exist
- cluster_unreachable: cannot connect to cluster API
- cluster_overloaded: cluster CPU/memory exceeds thresholds
- provision_failed: AnarchySubject provisioning failed""")

    evidence = "\n\n".join(evidence_parts)

    prompt = f"""{evidence}

## Task
Using the failure message, criteria results, similar past classifications, and lab/cluster failure history above, propose:
1. The most likely failure_class from the known list (or a new class name if none fit)
2. The conditions that would match this failure (as key == value pairs)
3. Your confidence level (0.0 to 1.0) — higher if similar past classifications match, lower if this is novel

Respond in this exact JSON format:
{{"proposed_class": "class_name", "conditions": ["criterion == value"], "confidence": 0.85, "reasoning": "brief explanation"}}"""

    from api.llm import call_llm, load_prompt, LLM_MODEL
    _classify_prompt = load_prompt("classify")
    llm_result = call_llm(
        endpoint="classify",
        messages=[
            {"role": "system", "content": _classify_prompt.get("system", "You are a failure classification expert for OpenShift lab environments. Respond with valid JSON only.")},
            {"role": "user", "content": prompt},
        ],
        max_tokens=_classify_prompt.get("max_tokens", 500),
        temperature=_classify_prompt.get("temperature", 0.1),
        timeout=30,
        context={"lab_code": eval_record.lab_code if eval_record else None, "cluster_name": eval_record.cluster_name if eval_record else None},
        db=db,
        prompt_version=_classify_prompt.get("version"),
    )
    if not llm_result["success"]:
        return {"error": f"LLM call failed: {llm_result['error']}"}
    llm_response = llm_result["content"]

    # Parse the LLM response
    proposed_class = "unknown"
    conditions = []
    confidence = 0.0
    reasoning = ""
    try:
        parsed = json.loads(llm_response)
        proposed_class = parsed.get("proposed_class", "unknown")
        conditions = parsed.get("conditions", [])
        confidence = parsed.get("confidence", 0.0)
        reasoning = parsed.get("reasoning", "")
    except json.JSONDecodeError:
        proposed_class = "parse_error"

    if not re.match(r"^[a-z][a-z0-9_]*$", proposed_class):
        proposed_class = "unknown"

    # Store the proposal
    proposal = ProposedClassification(
        run_id=run_id,
        stage_id=stage_id,
        original_message=message or (eval_record.message if eval_record else None),
        proposed_class=proposed_class,
        proposed_conditions=conditions,
        confidence=confidence,
        llm_model=llm_result["usage"].get("model", LLM_MODEL) if llm_result.get("usage") else LLM_MODEL,
        proposed_at=datetime.now(timezone.utc),
        llm_metric_id=llm_result.get("metric_id"),
    )
    db.add(proposal)
    db.commit()

    return {
        "proposal_id": proposal.id,
        "proposed_class": proposed_class,
        "conditions": conditions,
        "confidence": confidence,
        "reasoning": reasoning,
        "llm_raw": llm_response,
        "status": "pending_review",
    }


@router.post("/dashboard/propose-classification/{proposal_id}/review")
def review_classification(proposal_id: int, req: dict, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Approve or reject a proposed classification."""
    from db.models import ProposedClassification

    proposal = db.query(ProposedClassification).filter(ProposedClassification.id == proposal_id).first()
    if not proposal:
        raise HTTPException(404, "Proposal not found")

    action = req.get("action", "")
    if action not in ("approve", "reject"):
        raise HTTPException(422, "action must be 'approve' or 'reject'")

    proposal.reviewed = True
    proposal.approved = action == "approve"
    proposal.reviewed_by = req.get("reviewed_by", "ops")
    proposal.reviewed_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "proposal_id": proposal.id,
        "proposed_class": proposal.proposed_class,
        "action": action,
        "status": "approved" if proposal.approved else "rejected",
    }


@router.get("/dashboard/proposed-classifications")
def list_proposed_classifications(db: Session = Depends(get_db)):
    """List all proposed classifications."""
    from db.models import ProposedClassification

    proposals = db.query(ProposedClassification).order_by(ProposedClassification.id.desc()).limit(50).all()
    return [
        {
            "id": p.id,
            "run_id": p.run_id,
            "stage_id": p.stage_id,
            "original_message": p.original_message,
            "proposed_class": p.proposed_class,
            "conditions": p.proposed_conditions,
            "confidence": p.confidence,
            "llm_model": p.llm_model,
            "proposed_at": p.proposed_at.isoformat() if p.proposed_at else None,
            "reviewed": p.reviewed,
            "approved": p.approved,
            "reviewed_by": p.reviewed_by,
        }
        for p in proposals
    ]


# ---------------------------------------------------------------------------
# Provisioning recommendations
# ---------------------------------------------------------------------------

_recs_cache: Dict = {"data": None, "ts": 0}

@router.get("/dashboard/provisioning-recommendations")
def dashboard_provisioning_recommendations(db: Session = Depends(get_db)):
    """Generate provisioning recommendations based on current state (display only)."""
    if _recs_cache["data"] and time.time() - _recs_cache["ts"] < 30:
        return _recs_cache["data"]

    from engine.policy import generate_recommendations

    summit_data = dashboard_summit(db)
    labs = summit_data.get("labs", [])

    babylon = _load_latest_babylon()
    pools = babylon.get("pools", {})

    cluster_states = []
    for s in _load_latest_scan():
        cluster_states.append({
            "cluster": s.get("cluster", ""),
            "avg_cpu": s.get("avg_cpu_pct", 0),
            "vms_per_node": s.get("vms_per_node", 0),
            "sandbox_active": s.get("sandbox_active", 0),
        })

    sessions = _fetch_labagator_sessions()

    # Gather evaluation records for rubric context
    eval_records = repository.list_evaluations(db, limit=2000)
    evaluations = [
        {
            "lab_code": getattr(ev, 'lab_code', None) if hasattr(ev, 'lab_code') else ev.get("lab_code"),
            "stage_id": getattr(ev, 'stage_id', None) if hasattr(ev, 'stage_id') else ev.get("stage_id"),
            "outcome": getattr(ev, 'outcome', None) if hasattr(ev, 'outcome') else ev.get("outcome"),
            "failure_class": getattr(ev, 'failure_class', None) if hasattr(ev, 'failure_class') else ev.get("failure_class"),
            "criteria_results": getattr(ev, 'criteria_results', None) if hasattr(ev, 'criteria_results') else ev.get("criteria_results"),
            "evaluated_at": (getattr(ev, 'evaluated_at', None).isoformat() if hasattr(ev, 'evaluated_at') and getattr(ev, 'evaluated_at', None) else None)
                if hasattr(ev, 'evaluated_at') else ev.get("evaluated_at"),
        }
        for ev in eval_records
    ]

    # Gather constraint violations per lab
    from constraints.classifier import classify_constraints
    cv_by_lab: Dict[str, List[Dict]] = {}
    for lab in labs[:50]:
        lc = lab["lab_code"]
        constraints = _load_agnosticv_constraints(lc)
        if constraints:
            violations = classify_constraints(constraints, lab)
            if violations:
                cv_by_lab[lc] = [
                    {"violation_type": v.violation_type, "expected": v.expected, "actual": v.actual,
                     "severity": v.severity, "detail": v.detail}
                    for v in violations
                ]

    result = generate_recommendations(labs, pools, cluster_states, sessions, evaluations=evaluations, constraint_violations=cv_by_lab)

    escalated_clusters = set()
    escalated_failure_classes = set()
    try:
        from db.models import EventLog
        esc_events = (
            db.query(EventLog.cluster_name, EventLog.failure_class)
            .filter(EventLog.priority >= 7)
            .distinct().all()
        )
        for cluster, fc in esc_events:
            if cluster:
                escalated_clusters.add(cluster)
            if fc:
                escalated_failure_classes.add(fc)
    except Exception:
        pass

    lab_clusters = {}
    for lab in labs:
        lc = lab.get("lab_code", "")
        inst_clusters = set()
        for inst in lab.get("instances", []):
            c = inst.get("cluster", "")
            if c:
                inst_clusters.add(c)
        if inst_clusters:
            lab_clusters[lc] = inst_clusters

    for rec in result.get("recommendations", []):
        lab_code = rec.get("lab_code", "")
        rec_clusters = lab_clusters.get(lab_code, set())
        rec["escalated"] = bool(rec_clusters & escalated_clusters)
        if not rec["escalated"] and rec.get("type") == "smoke_test_failing":
            rec["escalated"] = bool(escalated_failure_classes & {"showroom_not_ready", "pods_not_ready", "showroom_pod_down"})

    result["escalated_count"] = sum(1 for r in result.get("recommendations", []) if r.get("escalated"))
    _recs_cache["data"] = result
    _recs_cache["ts"] = time.time()
    return result


# ---------------------------------------------------------------------------
# LLM-enhanced recommendation reasoning
# ---------------------------------------------------------------------------

@router.post("/dashboard/recommendation-reasoning")
@limiter.limit("10/minute")
def dashboard_recommendation_reasoning(request: Request, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Add AI reasoning and actionable insights to policy recommendations."""
    recs_data = dashboard_provisioning_recommendations(db)
    recs = recs_data.get("recommendations", [])

    if not recs:
        return {"prioritized": [], "groups": [], "summary": "No active recommendations.", "llm_used": False}

    evidence_parts = []
    evidence_parts.append(f"## Current Recommendations ({len(recs)} total)")
    for r in recs[:20]:
        evidence_parts.append(
            f"- [{r.get('urgency','?')}] {r.get('type','?')}: {r.get('recommendation','')} "
            f"(target: {r.get('lab_code', r.get('cluster', r.get('pool_name', '?')))}, "
            f"confidence: {r.get('confidence_score', '?')})"
        )

    try:
        from collectors.aap.collect_aap import collect_aap_jobs
        aap = collect_aap_jobs()
        s = aap.get("summary", {})
        if s.get("total_jobs", 0) > 0:
            errors = aap.get("top_errors", [])
            evidence_parts.append(f"\n## AAP Context\nSLI: {s.get('provision_sli')}%, Failed: {s.get('failed_24h')}")
            for e in errors[:3]:
                evidence_parts.append(f"  - {e['failing_task']}: {e.get('error','')[:80]} ({e['count']}x)")
    except Exception:
        pass

    try:
        scans = _load_latest_scan()
        cluster_info = [f"  - {s.get('cluster')}: CPU={s.get('avg_cpu_pct')}%, VMs={s.get('total_vms')}, sandboxes={s.get('sandbox_active')}" for s in scans[:8]]
        evidence_parts.append(f"\n## Cluster State\n" + "\n".join(cluster_info))
    except Exception:
        pass

    try:
        from engine.pool_velocity import compute_pool_velocity
        from db.repository import get_pool_timeline
        babylon = _load_latest_babylon()
        if babylon:
            depleting = []
            for pname, pdata in babylon.get("pools", {}).items():
                if isinstance(pdata, dict) and pdata.get("min_available", 0) > 0:
                    timeline = get_pool_timeline(db, pname, hours=6)
                    if len(timeline) >= 2:
                        vel = compute_pool_velocity(timeline)
                        if vel["trend"] == "depleting":
                            depleting.append(f"  - {pname}: {vel['handles_per_hour']:.1f}/hr")
            if depleting:
                evidence_parts.append(f"\n## Depleting Pools\n" + "\n".join(depleting))
    except Exception:
        pass

    evidence_str = "\n".join(evidence_parts)

    try:
        from api.llm import call_llm, load_prompt
        prompt = load_prompt("recommendation-reasoning")
        llm_result = call_llm(
            endpoint="recommendation-reasoning",
            messages=[
                {"role": "system", "content": prompt.get("system", "Analyze recommendations. Respond with JSON only.")},
                {"role": "user", "content": prompt.get("user_template", "{evidence}").replace("{evidence}", evidence_str)},
            ],
            max_tokens=prompt.get("max_tokens", 1500),
            temperature=prompt.get("temperature", 0.2),
            timeout=60, db=db,
            prompt_version=prompt.get("version"),
        )
        if llm_result.get("success"):
            analysis = json.loads(llm_result["content"])
            return {**analysis, "llm_used": True, "recommendation_count": len(recs)}
    except Exception:
        pass

    return {
        "prioritized": [{"type": r.get("type"), "target": r.get("lab_code", r.get("cluster", "")),
                         "urgency": r.get("urgency"), "root_cause": "Rule-based detection",
                         "impact": r.get("recommendation"), "steps": [], "auto_remediable": False}
                        for r in recs[:10]],
        "groups": [],
        "summary": f"{len(recs)} recommendations from policy engine. LLM reasoning unavailable.",
        "llm_used": False,
        "recommendation_count": len(recs),
    }


# ---------------------------------------------------------------------------
# Remediation commands
# ---------------------------------------------------------------------------

@router.get("/dashboard/remediation-commands/{failure_class}")
def get_remediation_commands(failure_class: str):
    """Get recommended remediation commands for a failure class from the catalog."""
    import yaml
    catalog_path = Path(__file__).parent.parent.parent / "remediations" / "catalog.yaml"
    if not catalog_path.exists():
        return {"failure_class": failure_class, "remediations": []}

    with open(catalog_path) as f:
        catalog = yaml.safe_load(f) or []

    matching = []
    for entry in catalog:
        for cond in entry.get("allowed_when", []):
            if failure_class in cond:
                matching.append({
                    "id": entry.get("id", ""),
                    "risk": entry.get("risk", "unknown"),
                    "mode": entry.get("mode", "recommend_only"),
                    "scope": entry.get("scope", "namespace"),
                    "commands": entry.get("commands", []),
                    "requires_approval": entry.get("requires_approval", True),
                })
                break

    return {
        "failure_class": failure_class,
        "remediations": matching,
        "total_matching": len(matching),
    }


# ---------------------------------------------------------------------------
# Evaluation matrix
# ---------------------------------------------------------------------------

@router.get("/dashboard/evaluation-matrix")
def dashboard_evaluation_matrix(db: Session = Depends(get_db)):
    """Lab x stage evaluation matrix — latest outcome per (lab_code, stage_id) pair."""
    from db.models import EvaluationRecord
    from sqlalchemy import func

    subq = (
        db.query(
            EvaluationRecord.lab_code,
            EvaluationRecord.stage_id,
            func.max(EvaluationRecord.evaluated_at).label("latest"),
        )
        .filter(EvaluationRecord.lab_code.isnot(None))
        .group_by(EvaluationRecord.lab_code, EvaluationRecord.stage_id)
        .subquery()
    )

    rows = (
        db.query(EvaluationRecord.lab_code, EvaluationRecord.stage_id, EvaluationRecord.outcome)
        .join(
            subq,
            (EvaluationRecord.lab_code == subq.c.lab_code)
            & (EvaluationRecord.stage_id == subq.c.stage_id)
            & (EvaluationRecord.evaluated_at == subq.c.latest),
        )
        .all()
    )

    matrix: Dict[str, Dict[str, str]] = {}
    for lab_code, stage_id, outcome in rows:
        if lab_code not in matrix:
            matrix[lab_code] = {}
        matrix[lab_code][stage_id] = outcome.lower() if outcome else "unknown"

    labs = sorted(matrix.keys())

    return {
        "labs": labs,
        "stages": PIPELINE_STAGES,
        "matrix": matrix,
    }


@router.get("/dashboard/labs-pipeline")
def dashboard_labs_pipeline(db: Session = Depends(get_db)):
    """Per-lab pipeline status — latest outcome per stage for each lab with evaluations."""
    from db.models import EvaluationRecord
    from sqlalchemy import func

    subq = (
        db.query(
            EvaluationRecord.lab_code,
            EvaluationRecord.stage_id,
            func.max(EvaluationRecord.evaluated_at).label("latest"),
        )
        .filter(EvaluationRecord.lab_code.isnot(None))
        .group_by(EvaluationRecord.lab_code, EvaluationRecord.stage_id)
        .subquery()
    )

    rows = (
        db.query(
            EvaluationRecord.lab_code,
            EvaluationRecord.stage_id,
            EvaluationRecord.outcome,
            EvaluationRecord.failure_class,
            EvaluationRecord.evaluated_at,
            EvaluationRecord.cluster_name,
        )
        .join(
            subq,
            (EvaluationRecord.lab_code == subq.c.lab_code)
            & (EvaluationRecord.stage_id == subq.c.stage_id)
            & (EvaluationRecord.evaluated_at == subq.c.latest),
        )
        .all()
    )

    labs_map: Dict = {}
    for lab_code, stage_id, outcome, failure_class, evaluated_at, cluster_name in rows:
        if lab_code not in labs_map:
            labs_map[lab_code] = {"stages": {}, "cluster": None}
        labs_map[lab_code]["stages"][stage_id] = {
            "outcome": outcome.lower() if outcome else None,
            "failure_class": failure_class,
            "evaluated_at": evaluated_at.isoformat() if evaluated_at else None,
        }
        if cluster_name:
            labs_map[lab_code]["cluster"] = cluster_name

    summit_data = dashboard_summit(db)
    labs_by_code = {l["lab_code"]: l for l in summit_data.get("labs", [])}

    result = []
    for lab_code in sorted(labs_map.keys()):
        entry = labs_map[lab_code]
        stages = entry["stages"]
        summit_lab = labs_by_code.get(lab_code, {})
        pass_count = sum(1 for s in stages.values() if s and s.get("outcome") == "pass")
        warn_count = sum(1 for s in stages.values() if s and s.get("outcome") == "warn")
        fail_count = sum(1 for s in stages.values() if s and s.get("outcome") == "fail")
        evaluated = pass_count + warn_count + fail_count

        furthest = None
        for sid in PIPELINE_STAGES:
            if sid in stages and stages[sid].get("outcome"):
                furthest = sid

        result.append({
            "lab_code": lab_code,
            "title": summit_lab.get("title", ""),
            "cluster": entry.get("cluster"),
            "sessions": summit_lab.get("sessions", 0),
            "stages": stages,
            "pass_count": pass_count,
            "warn_count": warn_count,
            "fail_count": fail_count,
            "health_pct": round((pass_count / max(evaluated, 1)) * 100, 1),
            "furthest_stage": furthest,
        })

    result.sort(key=lambda x: x["fail_count"], reverse=True)

    return {
        "labs": result,
        "stage_order": PIPELINE_STAGES,
        "total_labs": len(result),
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

    # Known CVEs affecting our stack (manually maintained list)
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

    # Get session schedule
    sessions = _fetch_labagator_sessions()

    # Build hourly forecast
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

        # Estimate resource impact
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

    # Cluster load projection
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

    # Capacity gate — pool depletion risk
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

    # Sandbox-API gate
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
    scan_dir = Path(__file__).parent.parent.parent / "scan-history"
    babylon_files = sorted(scan_dir.glob("babylon-*.json"), reverse=True)

    if len(babylon_files) < 2:
        return {"deltas": {}, "previous_time": None, "current_time": None}

    with open(babylon_files[0]) as f:
        current = json.load(f)

    # Compare against oldest file (or at least 1 hour back) for meaningful deltas
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    prev_file = babylon_files[-1]  # oldest available
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

    # Get current demolition data
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

    # Build per-lab delta
    curr_labs = current.get("labagator", {}).get("labs_by_code", {})
    deltas: Dict[str, Dict] = {}

    for code in curr_labs:
        d: Dict[str, Optional[str]] = {}

        # Instance count delta
        curr_instances = len(curr_mapping.get(code, []))
        prev_instances = len(prev_mapping.get(code, []))
        curr_started = sum(1 for i in curr_mapping.get(code, []) if i.get("state") == "started")
        prev_started = sum(1 for i in prev_mapping.get(code, []) if i.get("state") == "started")

        if curr_started > prev_started:
            d["instances"] = "up"
        elif curr_started < prev_started:
            d["instances"] = "down"

        # Pool capacity delta
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

        # Smoke test delta
        curr_smoke = _demo_status(curr_demo, code)
        prev_smoke = _demo_status(prev_demo, code)
        if curr_smoke == "pass" and prev_smoke != "pass":
            d["smoke"] = "up"
        elif curr_smoke == "fail" and prev_smoke != "fail":
            d["smoke"] = "down"
        elif curr_smoke != "pass" and prev_smoke == "pass":
            d["smoke"] = "down"

        # Status delta (planning -> in_development = up)
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
    pipeline_data = dashboard_pipeline(db=db)

    # Per-lab provisioning and readiness detail
    summit_data = dashboard_summit(db)
    labs = summit_data.get("labs", [])

    # Top failure classes
    all_failures = db.query(EvaluationRecord).filter(EvaluationRecord.outcome == "fail").all()
    failure_counts: Dict[str, int] = {}
    for e in all_failures:
        fc = e.failure_class or "unclassified"
        failure_counts[fc] = failure_counts.get(fc, 0) + 1
    top_failures = sorted(failure_counts.items(), key=lambda x: -x[1])[:10]

    # Live cluster data from scheduler if available
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

    # Pipeline pass rates
    pipeline_lines = []
    for stage in pipeline_data["stages"]:
        if stage["total"] > 0:
            pipeline_lines.append(
                f"{stage['stage_id']}: {stage['pass']}/{stage['total']} pass ({stage['health_rate']}%)"
            )

    # Per-lab detail — categorize labs by readiness
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

    # Babylon CatalogItems (from babylon worker cache)
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

    # Cross-reference with Labagator (match by ci_name slug)
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

    # ZeroTouch catalog items (if configured)
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

    # AgnosticV constraints (adds workload specs to matched items)
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


# ---------------------------------------------------------------------------
# Failure interpretation (LLM-powered)
# ---------------------------------------------------------------------------

@router.post("/dashboard/failure-interpretation")
@limiter.limit("10/minute")
def dashboard_failure_interpretation(request: Request, req: dict, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """LLM-powered explanation of why a rubric evaluation failed."""
    run_id = req.get("run_id", "")
    stage_id = req.get("stage_id", "")

    evidence_parts = []
    failure_class = None

    try:
        from db.models import EvaluationRecord
        ev = db.query(EvaluationRecord).filter(
            EvaluationRecord.run_id == run_id,
            EvaluationRecord.stage_id == stage_id,
        ).order_by(EvaluationRecord.id.desc()).first()
        if ev:
            failure_class = ev.result_failure_class
            evidence_parts.append(f"## Evaluation Result\n- Stage: {stage_id}\n- Outcome: {ev.result_outcome}\n- Failure class: {failure_class}\n- Message: {ev.result_message}")
            if ev.criteria_results:
                evidence_parts.append(f"## Criteria Results\n{json.dumps(ev.criteria_results, indent=2)}")
    except Exception as e:
        evidence_parts.append(f"## Evaluation\nUnavailable: {e}")

    try:
        scans = _load_latest_scan()
        if scans:
            cluster_info = [{"cluster": s.get("cluster"), "cpu": s.get("avg_cpu_pct"), "vms": s.get("total_vms")} for s in scans[:5]]
            evidence_parts.append(f"## Cluster State\n{json.dumps(cluster_info)}")
    except Exception:
        pass

    evidence_str = "\n\n".join(evidence_parts) if evidence_parts else "No evaluation data found"

    try:
        from api.llm import call_llm, load_prompt
        prompt = load_prompt("failure-interpretation")
        result = call_llm(
            endpoint="failure-interpretation",
            messages=[
                {"role": "system", "content": prompt.get("system", "Explain this failure. Be concise.")},
                {"role": "user", "content": prompt.get("user_template", "{evidence}").replace("{evidence}", evidence_str)},
            ],
            max_tokens=prompt.get("max_tokens", 400),
            temperature=prompt.get("temperature", 0.2),
            timeout=30, db=db, prompt_version=prompt.get("version"),
        )
        interpretation = result.get("content", "Unable to interpret") if result.get("success") else "LLM unavailable"
    except Exception as e:
        interpretation = f"Interpretation unavailable: {e}"

    return {
        "interpretation": interpretation,
        "failure_class": failure_class,
        "stage_id": stage_id,
        "run_id": run_id,
    }


# ---------------------------------------------------------------------------
# Trend analysis (LLM-powered)
# ---------------------------------------------------------------------------

@router.post("/dashboard/trend-analysis")
@limiter.limit("10/minute")
def dashboard_trend_analysis(request: Request, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """LLM-powered trend and pattern detection across evaluation history."""
    evidence_parts = []

    try:
        from db.models import EvaluationRecord
        from sqlalchemy import func
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_evals = db.query(
            EvaluationRecord.stage_id,
            EvaluationRecord.result_outcome,
            EvaluationRecord.result_failure_class,
            func.count(EvaluationRecord.id),
        ).filter(
            EvaluationRecord.evaluated_at >= cutoff
        ).group_by(
            EvaluationRecord.stage_id,
            EvaluationRecord.result_outcome,
            EvaluationRecord.result_failure_class,
        ).all()
        trend_data = [{"stage": r[0], "outcome": r[1], "failure_class": r[2], "count": r[3]} for r in recent_evals]
        evidence_parts.append(f"## Evaluation Trends (24h)\n{json.dumps(trend_data, indent=2)}")
    except Exception as e:
        evidence_parts.append(f"## Evaluation Trends\nUnavailable: {e}")

    try:
        from engine.pool_velocity import compute_pool_velocity
        from db.repository import get_pool_timeline
        babylon = _load_latest_babylon()
        if babylon:
            pool_trends = {}
            for pname in list(babylon.get("pools", {}).keys())[:10]:
                timeline = get_pool_timeline(db, pname, hours=24)
                if timeline:
                    pool_trends[pname] = compute_pool_velocity(timeline)
            if pool_trends:
                evidence_parts.append(f"## Pool Velocity Trends (24h)\n{json.dumps(pool_trends, indent=2)}")
    except Exception:
        pass

    try:
        scans = _load_latest_scan()
        if scans:
            cluster_health = [{"cluster": s.get("cluster"), "health": s.get("health_rate"), "cpu": s.get("avg_cpu_pct")} for s in scans[:10]]
            evidence_parts.append(f"## Cluster Health\n{json.dumps(cluster_health)}")
    except Exception:
        pass

    evidence_str = "\n\n".join(evidence_parts) if evidence_parts else "No trend data available"

    try:
        from api.llm import call_llm, load_prompt
        prompt = load_prompt("trend-analysis")
        result = call_llm(
            endpoint="trend-analysis",
            messages=[
                {"role": "system", "content": prompt.get("system", "Analyze trends. Respond with JSON only.")},
                {"role": "user", "content": prompt.get("user_template", "{evidence}").replace("{evidence}", evidence_str)},
            ],
            max_tokens=prompt.get("max_tokens", 800),
            temperature=prompt.get("temperature", 0.2),
            timeout=60, db=db, prompt_version=prompt.get("version"),
        )
        analysis = json.loads(result["content"]) if result.get("success") else None
    except Exception:
        analysis = None

    return {
        "analysis": analysis,
        "evidence_summary": f"{len(evidence_parts)} data sections analyzed",
    }


# ---------------------------------------------------------------------------
# Capacity analysis (LLM-powered)
# ---------------------------------------------------------------------------

@router.post("/dashboard/capacity-analysis")
@limiter.limit("5/minute")
def dashboard_capacity_analysis(request: Request, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """LLM-powered capacity forecast — pool velocity, workload complexity, scheduling risks."""
    from engine.pool_velocity import compute_pool_velocity, estimate_exhaustion
    from engine.workload_complexity import compute_complexity_score

    evidence_parts = []

    # Pool velocity data
    pool_velocities = {}
    try:
        from db.repository import get_pool_timeline
        babylon = _load_latest_babylon()
        if babylon:
            pools = babylon.get("pools", {})
            for pname, pdata in pools.items():
                if isinstance(pdata, dict):
                    timeline = get_pool_timeline(db, pname, hours=6)
                    velocity = compute_pool_velocity(timeline)
                    available = pdata.get("available", 0) if isinstance(pdata, dict) else 0
                    eta = estimate_exhaustion(available, velocity["handles_per_hour"])
                    pool_velocities[pname] = {**velocity, "available": available, "exhaustion_hours": eta}
            evidence_parts.append(f"## Pool Velocity\n{json.dumps(pool_velocities, indent=2)}")
    except Exception as e:
        evidence_parts.append(f"## Pool Velocity\nUnavailable: {e}")

    # Workload complexity
    complexities = {}
    try:
        from constraints.agnosticv_loader import load_all_constraints
        import os
        agv_dir = os.environ.get("STARGATE_AGNOSTICV_DIR", "")
        if agv_dir:
            from pathlib import Path
            all_constraints = load_all_constraints(Path(agv_dir))
            for slug, constraints in list(all_constraints.items())[:30]:
                complexities[slug] = compute_complexity_score(constraints)
            evidence_parts.append(f"## Workload Complexity (top 30)\n{json.dumps({k: v['score'] for k, v in sorted(complexities.items(), key=lambda x: -x[1]['score'])[:15]}, indent=2)}")
    except Exception as e:
        evidence_parts.append(f"## Workload Complexity\nUnavailable: {e}")

    # Cluster state
    try:
        scans = _load_latest_scan()
        if scans:
            cluster_summary = [{
                "cluster": s.get("cluster"),
                "avg_cpu": s.get("avg_cpu_pct"),
                "total_vms": s.get("total_vms"),
                "vms_per_node": s.get("vms_per_node"),
                "health_rate": s.get("health_rate"),
            } for s in scans[:10]]
            evidence_parts.append(f"## Cluster State\n{json.dumps(cluster_summary, indent=2)}")
    except Exception:
        pass

    evidence_str = "\n\n".join(evidence_parts) if evidence_parts else "No data available"

    # Call LLM
    llm_result = None
    try:
        from api.llm import call_llm, load_prompt
        prompt = load_prompt("capacity-forecast")
        llm_result = call_llm(
            endpoint="capacity-forecast",
            messages=[
                {"role": "system", "content": prompt.get("system", "Analyze capacity. Respond with JSON only.")},
                {"role": "user", "content": prompt.get("user_template", "{evidence}").replace("{evidence}", evidence_str)},
            ],
            max_tokens=prompt.get("max_tokens", 1500),
            temperature=prompt.get("temperature", 0.2),
            timeout=60,
            db=db,
            prompt_version=prompt.get("version"),
        )
    except Exception as e:
        llm_result = {"success": False, "error": str(e)}

    return {
        "pool_velocities": pool_velocities,
        "workload_complexities": {k: {"score": v["score"], "estimated_minutes": v["estimated_provision_minutes"]} for k, v in complexities.items()},
        "llm_analysis": json.loads(llm_result["content"]) if llm_result and llm_result.get("success") else None,
        "llm_error": llm_result.get("error") if llm_result and not llm_result.get("success") else None,
        "evidence_summary": f"{len(pool_velocities)} pools tracked, {len(complexities)} labs scored",
    }


# ---------------------------------------------------------------------------
# ZeroTouch provisioning
# ---------------------------------------------------------------------------

@router.get("/dashboard/zerotouch")
def dashboard_zerotouch():
    """ZeroTouch catalog items and workshop seat availability."""
    try:
        from collectors.zerotouch.collect_zerotouch import summarize_zerotouch
        return summarize_zerotouch()
    except Exception as e:
        return {
            "available": False,
            "catalog_total": 0,
            "catalog_active": 0,
            "catalog_items": [],
            "workshops": {},
            "workshop_count": 0,
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Sandbox-API health
# ---------------------------------------------------------------------------

@router.get("/dashboard/sandbox-api")
def dashboard_sandbox_api():
    """Sandbox-API deployment health and sandbox namespace counts."""
    try:
        from collectors.sandbox_api.collect_sandbox_api import summarize_sandbox_api
        from api.routers._shared import _load_latest_scan
        scanner_data = _load_latest_scan() or []
        return summarize_sandbox_api(scanner_data=scanner_data)
    except Exception as e:
        return {
            "api_healthy": False,
            "replicas_desired": 0,
            "replicas_ready": 0,
            "pod_statuses": [],
            "api_version": None,
            "total_sandboxes": 0,
            "active": 0,
            "failing": 0,
            "crashloop": 0,
            "by_cluster": {},
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Visual storytelling endpoints
# ---------------------------------------------------------------------------

@router.get("/dashboard/action-strip")
def dashboard_action_strip(db: Session = Depends(get_db)):
    """Top actionable items for the banner — tells the story at a glance."""
    from api.contracts import get_freshness

    actions = []

    try:
        from collectors.aap.collect_aap import collect_aap_jobs
        aap = collect_aap_jobs()
        s = aap.get("summary", {})
        if s.get("total_jobs", 0) > 0 and not s.get("sli_met", True):
            actions.append({
                "message": f"Provision SLI at {s.get('provision_sli', 0)}% (target {s.get('provision_sli_target', 93)}%)",
                "urgency": "critical",
                "count": s.get("failed_24h", 0),
                "link_tab": "provisioning",
            })
        labs_failing = len(aap.get("by_lab", {}))
        if labs_failing > 0:
            actions.append({
                "message": f"{labs_failing} labs have AAP provisioning failures",
                "urgency": "critical",
                "count": labs_failing,
                "link_tab": "provisioning",
            })
    except Exception:
        pass

    try:
        summit = dashboard_summit(db)
        stuck = sum(1 for l in summit.get("labs", []) if l.get("instances_failed", 0) > 0)
        if stuck > 0:
            actions.append({
                "message": f"{stuck} labs with stuck instances",
                "urgency": "high",
                "count": stuck,
                "link_tab": "labs",
            })
    except Exception:
        pass

    try:
        from db.models import EventLog
        escalated = db.query(EventLog).filter(EventLog.priority >= 7).count()
        if escalated > 0:
            actions.append({
                "message": f"{escalated} escalated events",
                "urgency": "high",
                "count": escalated,
                "link_tab": "errors",
            })
    except Exception:
        pass

    actions.sort(key=lambda a: {"critical": 0, "high": 1, "medium": 2}.get(a["urgency"], 3))

    return {
        "actions": actions[:5],
        "source_freshness": get_freshness(),
    }


@router.get("/dashboard/ai-summary")
def dashboard_ai_summary(db: Session = Depends(get_db)):
    """AI-generated summary of top issues with evidence sources."""
    top_issues = []

    try:
        from collectors.aap.collect_aap import collect_aap_jobs
        aap = collect_aap_jobs()
        by_lab = aap.get("by_lab", {})
        for lab, info in sorted(by_lab.items(), key=lambda x: -x[1]["total"])[:3]:
            top_issues.append({
                "message": f"{lab}: {info['total']} AAP failures — {info.get('top_error', 'check Tower')}",
                "urgency": "critical",
                "source": "aap",
                "count": info["total"],
                "lab_code": lab,
            })
    except Exception:
        pass

    try:
        summit = dashboard_summit(db)
        for lab in sorted(summit.get("labs", []), key=lambda l: -l.get("instances_failed", 0))[:2]:
            if lab.get("instances_failed", 0) > 0:
                top_issues.append({
                    "message": f"{lab['lab_code']}: {lab['instances_failed']} stuck instances (destroy-failed)",
                    "urgency": "high",
                    "source": "babylon",
                    "count": lab["instances_failed"],
                    "lab_code": lab["lab_code"],
                })
    except Exception:
        pass

    recommendation = ""
    if top_issues:
        top = top_issues[0]
        recommendation = f"Priority: address {top['lab_code']} — {top['count']} failures from {top['source']}."

    return {
        "top_issues": top_issues[:5],
        "recommendation": recommendation,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
@router.get("/dashboard/data-health")
def dashboard_data_health(db: Session = Depends(get_db)):
    """Cross-tab consistency checks and source freshness."""
    from api.contracts import get_freshness
    from db.models import EvaluationRecord, MVPipelineStage

    checks = []
    passed = 0
    failed = 0

    try:
        pipeline_stages = db.query(MVPipelineStage).all()
        for s in pipeline_stages:
            total = s.pass_count + s.fail_count + s.warn_count
            ok = total == s.total
            checks.append({
                "check": f"pipeline stage {s.stage_id}: pass+warn+fail == total",
                "tabs": ["Pipeline"],
                "passed": ok,
                "detail": f"{s.pass_count}+{s.warn_count}+{s.fail_count}={total} vs total={s.total}",
            })
            if ok:
                passed += 1
            else:
                failed += 1
    except Exception:
        pass

    try:
        eval_count = db.query(EvaluationRecord).count()
        checks.append({
            "check": "evaluations exist in database",
            "tabs": ["Pipeline", "Errors", "Labs"],
            "passed": eval_count > 0,
            "detail": f"{eval_count} evaluations",
        })
        if eval_count > 0:
            passed += 1
        else:
            failed += 1
    except Exception:
        pass

    return {
        "checks": checks,
        "passed": passed,
        "failed": failed,
        "total": passed + failed,
        "freshness": get_freshness(),
    }


# ---------------------------------------------------------------------------
# Data mapping validation
# ---------------------------------------------------------------------------

@router.get("/dashboard/data-mapping")
def dashboard_data_mapping(db: Session = Depends(get_db)):
    """Validate data source joins for every lab — shows which sources connected and how."""
    from db.models import EvaluationRecord, ProposedClassification

    summit_data = dashboard_summit(db)
    labs_list = summit_data.get("labs", [])

    babylon = _load_latest_babylon()
    summit_mapping = babylon.get("summit_mapping", {})
    demolition_sessions = []
    try:
        demolition_sessions = _fetch_demolition_sessions()
    except Exception:
        pass

    eval_labs = set()
    try:
        rows = db.query(EvaluationRecord.lab_code).filter(
            EvaluationRecord.lab_code.isnot(None)
        ).distinct().all()
        eval_labs = {r[0] for r in rows}
    except Exception:
        pass

    proposal_labs = set()
    try:
        rows = db.query(ProposedClassification.run_id).distinct().limit(1000).all()
        proposal_run_ids = {r[0] for r in rows}
        if proposal_run_ids:
            ev_rows = db.query(EvaluationRecord.lab_code).filter(
                EvaluationRecord.run_id.in_(proposal_run_ids),
                EvaluationRecord.lab_code.isnot(None),
            ).distinct().all()
            proposal_labs = {r[0] for r in ev_rows}
    except Exception:
        pass

    CATALOG_TO_DEMO = {
        "zt-rhelbu": "zt-rhel", "zt-ansiblebu": "zt-ansible",
        "zt-hpbu": "zt-rhel", "ocp4-cluster": "ocp4-cluster",
        "openshift-cnv": "ocp4-cluster",
    }

    result_labs = []
    fully = 0
    partial = 0
    disconnected = 0

    all_eval_demo_ids = set()
    for el in eval_labs:
        if el.startswith("sandbox-"):
            parts = el.split("-", 2)
            if len(parts) >= 3:
                all_eval_demo_ids.add(parts[2])

    for lab in labs_list:
        code = lab["lab_code"]
        ci_name = lab.get("ci_name", "")
        ci_slug = ci_name.split(".", 1)[1] if "." in ci_name else ""
        ci_base = ci_name.split(".")[0] if "." in ci_name else ci_name
        cloud = lab.get("cloud", "")
        issues = []

        # LABAGATOR — always connected (source of truth)
        src_labagator = {"connected": True, "key": f"lab_code={code}"}

        # BABYLON — connected if instances exist OR demolition ran (means it was provisioned)
        has_instances = lab.get("instances_total", 0) > 0 or len(summit_mapping.get(code, [])) > 0
        has_smoke = lab.get("demolition_status", "none") != "none"
        has_scanned = lab.get("last_scanned") is not None
        babylon_connected = has_instances or has_smoke or has_scanned
        src_babylon = {"connected": babylon_connected, "key": f"instances={lab.get('instances_total',0)}, smoke={has_smoke}, scanned={has_scanned}"}
        if not babylon_connected:
            issues.append("babylon: not provisioned (no instances, no smoke tests, no scans)")

        # POOLS — connected by cloud type (pools are shared, not per-lab)
        cloud_pool_map = {"CNV": "openshift-cnv", "AWS": "clusterplatform", "Tenant Namespace": None}
        pool_prefix = cloud_pool_map.get(cloud)
        pool_connected = False
        pool_key = f"cloud={cloud}"
        if lab.get("provisioned", 0) > 0 or lab.get("capacity", 0) > 0:
            pool_connected = True
            pool_key = f"provisioned={lab.get('provisioned',0)}"
        elif pool_prefix:
            pool_connected = any(p.get("name", "").startswith(pool_prefix) for p in babylon.get("pools", {}).get("all_pools", babylon.get("pools", {}).get("all_pools", current.get("pools", {}).get("summit_pools", []))))
            pool_key = f"{cloud}→{pool_prefix}.*"
        elif cloud == "Tenant Namespace":
            pool_connected = True
            pool_key = "Tenant Namespace (no pool needed)"
        elif ci_base and ci_base != "summit-2026":
            pool_connected = any(p.get("name", "").startswith(ci_base) for p in babylon.get("pools", {}).get("all_pools", babylon.get("pools", {}).get("all_pools", current.get("pools", {}).get("summit_pools", []))))
            pool_key = f"ci_base={ci_base}"
        src_pools = {"connected": pool_connected, "key": pool_key}
        if not pool_connected:
            issues.append(f"pools: no pool for cloud={cloud}")

        # DEMOLITION — connected if dashboard_summit already matched smoke test data
        demo_connected = lab.get("demolition_status", "none") != "none"
        src_demolition = {"connected": demo_connected, "key": f"status={lab.get('demolition_status','none')}", "total": lab.get("demolition_total", 0)}
        if not demo_connected:
            issues.append("demolition: no smoke test results")

        # SCANNER — connected if lab has been scanned (last_scanned set by dashboard_summit)
        # OR if evaluations exist for namespaces matching this lab's catalog type
        scanner_connected = has_scanned or code in eval_labs
        scanner_key = "last_scanned" if has_scanned else f"lab_code={code}" if code in eval_labs else ""
        if not scanner_connected and ci_slug:
            slug_parts = ci_slug.split("-")
            lb_prefix = slug_parts[0] if slug_parts else ""
            if lb_prefix:
                scanner_connected = any(lb_prefix in el for el in eval_labs)
                scanner_key = f"slug prefix {lb_prefix}"
        if not scanner_connected and ci_base:
            demo_id = CATALOG_TO_DEMO.get(ci_base, ci_base)
            if demo_id in all_eval_demo_ids or ci_base in all_eval_demo_ids:
                scanner_connected = True
                scanner_key = f"demo_id={demo_id}"
        src_scanner = {"connected": scanner_connected, "key": scanner_key or "no match"}
        if not scanner_connected:
            issues.append(f"scanner: no evaluations for this lab type")

        # AGNOSTICV — constraint data loaded
        lab_ci = lab.get("ci_name", "")
        constraints = _load_agnosticv_constraints(code, ci_name=lab_ci)
        agv_connected = constraints is not None and len(constraints) > 0
        src_agnosticv = {"connected": agv_connected, "key": f"slug={ci_slug}" if ci_slug else f"prefix={code.lower()}", "fields": len(constraints) if constraints else 0}
        if not agv_connected:
            issues.append("agnosticv: no matching directory")

        # LLM — connected if scanner is connected (auto-LLM classifies scanner evaluations)
        # OR if proposals exist for matching evaluations
        llm_connected = scanner_connected and len(proposal_labs) > 0
        if not llm_connected:
            llm_connected = code in proposal_labs
        src_llm = {"connected": llm_connected, "key": "auto-classify via scanner" if scanner_connected else "direct"}

        sources = {
            "labagator": src_labagator,
            "babylon": src_babylon,
            "pools": src_pools,
            "demolition": src_demolition,
            "scanner": src_scanner,
            "agnosticv": src_agnosticv,
            "llm": src_llm,
        }

        connected_count = sum(1 for s in sources.values() if s["connected"])
        total_sources = len(sources)

        if connected_count == total_sources:
            fully += 1
        elif connected_count <= 1:
            disconnected += 1
        else:
            partial += 1

        result_labs.append({
            "lab_code": code,
            "title": lab.get("title", ""),
            "sources": sources,
            "join_health": f"{connected_count}/{total_sources} connected",
            "connected_count": connected_count,
            "issues": issues,
        })

    result_labs.sort(key=lambda x: x["connected_count"])

    return {
        "labs": result_labs,
        "summary": {
            "total_labs": len(result_labs),
            "fully_connected": fully,
            "partially_connected": partial,
            "disconnected": disconnected,
        },
        "join_keys": [
            {"from_source": "Labagator", "to_source": "Babylon", "key": "ci_name prefix match against AnarchySubject name", "reliability": "high"},
            {"from_source": "Labagator", "to_source": "Demolition", "key": "lab_code word-boundary match + ci_name slug in session name", "reliability": "medium"},
            {"from_source": "Labagator", "to_source": "Scanner", "key": "ci_name slug match against sandbox namespace demo_id patterns", "reliability": "medium"},
            {"from_source": "Labagator", "to_source": "AgnosticV", "key": "ci_name slug as exact directory name, fallback to lab_code prefix", "reliability": "high"},
            {"from_source": "Scanner", "to_source": "LLM", "key": "(run_id, stage_id) composite key between EvaluationRecord and ProposedClassification", "reliability": "high"},
            {"from_source": "Babylon", "to_source": "Pools", "key": "ci_name prefix match against pool name", "reliability": "high"},
        ],
    }


# ---------------------------------------------------------------------------
# Remediation (AI-assisted)
# ---------------------------------------------------------------------------

@router.get("/dashboard/remediation-history")
def dashboard_remediation_history(limit: int = 50, db: Session = Depends(get_db)):
    """Historical remediation records — what was tried and whether it resolved the issue."""
    from db.models import RemediationRecord
    records = db.query(RemediationRecord).order_by(RemediationRecord.id.desc()).limit(limit).all()
    return {
        "total": len(records),
        "records": [
            {
                "id": r.id,
                "run_id": r.run_id,
                "stage_id": r.stage_id,
                "failure_class": r.failure_class,
                "remediation_id": r.remediation_id,
                "action_taken": r.action_taken,
                "resolved": r.resolved,
                "applied_at": r.applied_at.isoformat() if r.applied_at else None,
                "applied_by": r.applied_by,
            }
            for r in records
        ],
        "resolved_count": sum(1 for r in records if r.resolved),
        "unresolved_count": sum(1 for r in records if r.resolved is False),
    }


@router.post("/dashboard/remediation")
@limiter.limit("10/minute")
def dashboard_remediation(request: Request, req: dict, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """AI remediation with full evidence bundle context via configured LLM.

    Accepts context_type: lab, cluster, pool, or error.
    Builds a specific evidence bundle for the LLM based on context.
    """
    import urllib.request as urllib_req

    context_type = req.get("context_type", "error")
    failure_class = req.get("failure_class", "")
    lab_code = req.get("lab_code", "")
    cluster = req.get("cluster", "")
    pool_name = req.get("pool_name", "")

    # Load remediation catalog
    catalog_path = Path(__file__).parent.parent.parent / "remediations" / "catalog.yaml"
    matching = []
    if catalog_path.exists():
        import yaml
        with open(catalog_path) as f:
            catalog_list = yaml.safe_load(f) or []
        for entry in catalog_list:
            for cond in entry.get("allowed_when", []):
                if failure_class and failure_class in cond:
                    matching.append(entry)
                    break

    commands = []
    for r in matching:
        commands.extend(r.get("commands", []))

    # Build evidence context based on what we're analyzing
    evidence_context = _build_evidence_context(context_type, lab_code, cluster, pool_name, failure_class, db)

    # Build LLM prompt with full evidence
    prompt = _build_remediation_prompt(context_type, evidence_context, commands)

    # Call LLM via instrumented wrapper
    from api.llm import call_llm, load_prompt, LLM_MODEL
    _rem_prompt = load_prompt("remediation")
    llm_result = call_llm(
        endpoint="remediation",
        messages=[
            {"role": "system", "content": _rem_prompt.get("system", "You are a Red Hat OpenShift operations expert specializing in lab readiness and workload operations.")},
            {"role": "user", "content": prompt},
        ],
        max_tokens=_rem_prompt.get("max_tokens", 1200),
        temperature=_rem_prompt.get("temperature", 0.2),
        timeout=30,
        context={"lab_code": lab_code, "cluster_name": cluster, "failure_class": failure_class},
        db=db,
        prompt_version=_rem_prompt.get("version"),
    )
    llm_analysis = llm_result["content"] if llm_result["success"] else f"LLM call failed: {llm_result['error']}"

    return {
        "failure_class": failure_class,
        "lab_code": lab_code,
        "cluster": cluster,
        "context_type": context_type,
        "found": len(matching) > 0,
        "message": f"Found {len(matching)} catalog entries." if matching else "No catalog match — using AI analysis.",
        "recommended_actions": [r.get("id", "") for r in matching],
        "runbook_steps": commands,
        "confidence": "high" if matching else "medium",
        "confidence_score": 0.9 if matching else 0.6,
        "llm_analysis": llm_analysis,
        "llm_model": LLM_MODEL,
        "llm_metric_id": llm_result.get("metric_id"),
        "llm_latency_ms": llm_result.get("latency_ms"),
        "llm_tokens": llm_result.get("usage", {}).get("total_tokens"),
        "evidence_summary": evidence_context.get("summary", ""),
    }


# ---------------------------------------------------------------------------
# Helper functions (used only by dashboard endpoints)
# ---------------------------------------------------------------------------

def _build_evidence_context(context_type: str, lab_code: str, cluster: str, pool_name: str, failure_class: str, db) -> Dict:
    """Assemble comprehensive evidence bundle for LLM context."""
    ctx: Dict = {"summary": "", "details": {}, "history": "", "related": "", "remediations": "", "constraints": ""}

    # --- Universal evidence (all context types) ---
    history_lines = []
    related_lines = []
    remediation_lines = []

    # Evaluation history
    if lab_code:
        eval_history = repository.get_evaluation_history(db, lab_code, limit=20)
        if eval_history:
            history_lines.append(f"Last {len(eval_history)} evaluations for {lab_code}:")
            for eh in eval_history[:10]:
                history_lines.append(f"  {eh['evaluated_at'] or '?'}: {eh['outcome']} — {eh['failure_class'] or 'none'} ({eh['stage_id']})")
            outcomes = [e["outcome"] for e in eval_history]
            fail_ct = outcomes.count("fail")
            pass_ct = outcomes.count("pass")
            if fail_ct > pass_ct * 2:
                history_lines.append(f"  Trend: DEGRADING ({fail_ct} fails vs {pass_ct} passes in last {len(eval_history)} evals)")
            elif pass_ct > fail_ct * 2:
                history_lines.append(f"  Trend: IMPROVING ({pass_ct} passes vs {fail_ct} fails)")
            else:
                history_lines.append(f"  Trend: UNSTABLE ({pass_ct} passes, {fail_ct} fails)")

        last_pass = repository.get_last_passing_run(db, lab_code)
        if last_pass:
            history_lines.append(f"Last healthy: {last_pass['evaluated_at']} on {last_pass.get('cluster_name', '?')}")
        elif lab_code:
            history_lines.append("Last healthy: NEVER PASSED")

    # Similar failures / blast radius
    if failure_class:
        freq = repository.get_failure_class_frequency(db, cluster_name=cluster, limit=50)
        if freq:
            related_lines.append(f"Failure distribution on {cluster or 'all clusters'}:")
            for fc, count in sorted(freq.items(), key=lambda x: -x[1])[:8]:
                marker = " ← THIS" if fc == failure_class else ""
                related_lines.append(f"  {fc}: {count}{marker}")

        blast = repository.get_blast_radius(db, failure_class=failure_class)
        if blast["total_events"] > 0:
            related_lines.append(f"Blast radius for {failure_class}:")
            related_lines.append(f"  Events: {blast['total_events']}, Labs affected: {len(blast['labs_affected'])}, Clusters: {len(blast['clusters_affected'])}")
            related_lines.append(f"  Systemic: {'YES' if blast['systemic'] else 'no'}, Escalated: {blast['escalated']}")
            if blast["labs_affected"]:
                related_lines.append(f"  Labs: {', '.join(blast['labs_affected'][:10])}")

    # Prior remediation attempts
    prior_remediations = repository.get_recent_remediations(db, lab_code=lab_code, failure_class=failure_class, limit=5)
    if prior_remediations:
        remediation_lines.append("Prior remediation attempts:")
        for pr in prior_remediations:
            resolved = "RESOLVED" if pr["resolved"] else "NOT RESOLVED" if pr["resolved"] is False else "outcome unknown"
            remediation_lines.append(f"  {pr['remediation_id']}: {pr['action_taken'] or '?'} — {resolved} ({pr['applied_at'] or '?'})")
    else:
        remediation_lines.append("No prior remediation attempts recorded.")

    ctx["history"] = "\n".join(history_lines) if history_lines else "No evaluation history available."
    ctx["related"] = "\n".join(related_lines) if related_lines else "No related failure data."
    ctx["remediations"] = "\n".join(remediation_lines)

    # --- Context-specific evidence ---

    if context_type == "lab":
        babylon = _load_latest_babylon()
        lab_info = babylon.get("labagator", {}).get("labs_by_code", {}).get(lab_code, {})
        summit_pools = babylon.get("pools", {}).get("all_pools", babylon.get("pools", {}).get("all_pools", current.get("pools", {}).get("summit_pools", [])))
        lab_pools = [p for p in summit_pools if lab_code.lower() in p.get("name", "").lower()]
        prov = babylon.get("provisioning", {})
        mapping = babylon.get("summit_mapping", {}).get(lab_code, [])
        demolition = babylon.get("demolition_summit", {})

        # Instance state from mapping
        inst_started = sum(1 for i in mapping if i.get("state") == "started")
        inst_failed = sum(1 for i in mapping if "failed" in (i.get("state") or ""))
        inst_total = len(mapping)

        # Demolition results
        demo_sessions = demolition.get("sessions", []) if isinstance(demolition, dict) else []
        lab_demo = [s for s in demo_sessions if lab_code.lower() in s.get("name", "").lower()] if demo_sessions else []

        # Constraints
        constraints = _load_agnosticv_constraints(lab_code)
        constraint_lines = []
        if constraints:
            constraint_lines.append(f"Declared constraints for {lab_code}:")
            for k, v in list(constraints.items())[:10]:
                constraint_lines.append(f"  {k}: {v}")
        ctx["constraints"] = "\n".join(constraint_lines) if constraint_lines else ""

        # Sessions from labagator cache
        lab_sessions = [s for s in _fetch_labagator_sessions() if s.get("lab_code") == lab_code]

        ctx["details"] = {"lab": lab_info, "pools": lab_pools, "provisioning": prov, "instances": mapping[:5]}
        ctx["summary"] = (
            f"Lab {lab_code}: '{lab_info.get('title', 'unknown')}'\n"
            f"Status: {lab_info.get('status', 'unknown')}, Cloud: {lab_info.get('cloud', 'unknown')}\n"
            f"Sessions: {len(lab_sessions)} scheduled, {lab_info.get('session_count', 0)} in labagator\n"
            f"Pools: {len(lab_pools)} ({sum(p.get('ready',0) for p in lab_pools)} ready, {sum(p.get('available',0) for p in lab_pools)} available)\n"
            f"Instances: {inst_started} started, {inst_failed} failed, {inst_total} total\n"
            f"Summit provisioning: {prov.get('started', 0)} started, {prov.get('failed', 0)} failed of {prov.get('total', 0)}\n"
            f"Demolition: {len(lab_demo)} test sessions found"
        )

        # AAP provisioning data for this lab
        try:
            from collectors.aap.collect_aap import collect_aap_jobs
            aap_data = collect_aap_jobs()
            lab_aap = aap_data.get("by_lab", {}).get(lab_code, {})
            if lab_aap:
                ctx["summary"] += (
                    f"\nAAP Failures: {lab_aap.get('total', 0)} ({lab_aap.get('provision', 0)} provision, {lab_aap.get('destroy', 0)} destroy)"
                    f"\nTop AAP Error: {lab_aap.get('top_error', 'unknown')}"
                )
                sli = aap_data.get("summary", {})
                ctx["summary"] += f"\nPlatform AAP SLI: {sli.get('provision_sli', '?')}% (target {sli.get('provision_sli_target', 93)}%)"
        except Exception:
            pass

    elif context_type == "cluster":
        scans = _load_latest_scan()
        cluster_scan = next((s for s in scans if s.get("cluster") == cluster), {})
        all_summaries = repository.get_all_cluster_summaries(db)
        summary_data = all_summaries.get(cluster, {})

        ctx["details"] = {"scan": cluster_scan, "evaluation_summary": summary_data}
        ctx["summary"] = (
            f"Cluster {cluster}:\n"
            f"Nodes: {cluster_scan.get('nodes', '?')} total, {cluster_scan.get('compute_nodes', '?')} compute\n"
            f"CPU: {cluster_scan.get('avg_cpu_pct', '?')}%, Hot nodes: {cluster_scan.get('hot_nodes', '?')}\n"
            f"VMs: {cluster_scan.get('total_vms', '?')}, VMs/node: {cluster_scan.get('vms_per_node', '?')}\n"
            f"Labs: {cluster_scan.get('sandbox_active', '?')} active, {cluster_scan.get('sandbox_failing', '?')} failing, {cluster_scan.get('sandbox_crashloop', '?')} crashlooping\n"
            f"Health rate: {cluster_scan.get('health_rate', '?')}%\n"
            f"New failures: {cluster_scan.get('new_failures', [])}\n"
            f"Issues: {cluster_scan.get('issues', [])}\n"
            f"Evaluations: {summary_data.get('total_evaluations', 0)} total, {summary_data.get('failed', 0)} failed\n"
            f"Labs seen: {summary_data.get('labs_seen', 0)}, Labs failing: {summary_data.get('labs_failing', 0)}\n"
            f"Failure classes: {summary_data.get('failure_classes', {})}"
        )

    elif context_type == "pool":
        babylon = _load_latest_babylon()
        all_pools = babylon.get("pools", {}).get("all_pools", babylon.get("pools", {}).get("all_pools", current.get("pools", {}).get("summit_pools", [])))
        pool = next((p for p in all_pools if p.get("name") == pool_name), {})
        prov = babylon.get("provisioning", {})
        exhausted = babylon.get("pools", {}).get("exhausted_pools", [])
        low = babylon.get("pools", {}).get("low", []) if isinstance(babylon.get("pools", {}).get("low"), list) else []

        ctx["details"] = {"pool": pool, "provisioning": prov}
        ctx["summary"] = (
            f"Pool: {pool_name}\n"
            f"Available: {pool.get('available', '?')}, Ready: {pool.get('ready', '?')}, Min: {pool.get('min', '?')}\n"
            f"Platform provisioning: {prov.get('started', 0)} started, {prov.get('failed', 0)} failed\n"
            f"Failure rate: {prov.get('failure_rate', '?')}%\n"
            f"By state: {prov.get('by_state', {})}\n"
            f"Exhausted pools on platform: {len(exhausted)}\n"
            f"Low pools on platform: {len(low) if isinstance(low, list) else '?'}"
        )

    elif context_type == "error":
        from db.models import EvaluationRecord
        recent = db.query(EvaluationRecord).filter(
            EvaluationRecord.failure_class == failure_class
        ).order_by(EvaluationRecord.id.desc()).limit(20).all()

        clusters_hit = set()
        labs_hit = set()
        stages_hit = set()
        messages = []
        criteria = []
        for e in recent:
            if e.cluster_name: clusters_hit.add(e.cluster_name)
            if e.lab_code: labs_hit.add(e.lab_code)
            if e.stage_id: stages_hit.add(e.stage_id)
            if e.message and e.message not in messages:
                messages.append(e.message)
            if e.criteria_results and e.criteria_results not in criteria:
                criteria.append(e.criteria_results)

        ctx["details"] = {
            "total_occurrences": len(recent),
            "clusters": list(clusters_hit),
            "labs": list(labs_hit)[:15],
            "stages": list(stages_hit),
            "recent_messages": messages[:5],
            "criteria_results": criteria[:3],
        }
        ctx["summary"] = (
            f"Failure class: {failure_class}\n"
            f"Occurrences: {len(recent)} recent\n"
            f"Clusters affected: {', '.join(sorted(clusters_hit)) or 'unknown'} ({len(clusters_hit)} clusters)\n"
            f"Labs affected: {len(labs_hit)} labs\n"
            f"Stages: {', '.join(sorted(stages_hit)) or 'unknown'}\n"
            f"Sample messages:\n" + "\n".join(f"  - {m[:150]}" for m in messages[:5]) + "\n"
            f"Criteria that failed: {criteria[:2] if criteria else 'not available'}"
        )

    return ctx


def _build_remediation_prompt(context_type: str, evidence: Dict, catalog_commands: List[str]) -> str:
    """Build a structured LLM prompt with full evidence context."""
    sections = []

    sections.append(f"## Current State\n\n{evidence.get('summary', 'No evidence available')}")

    if evidence.get("history") and evidence["history"] != "No evaluation history available.":
        sections.append(f"## Historical Pattern\n\n{evidence['history']}")

    if evidence.get("related") and evidence["related"] != "No related failure data.":
        sections.append(f"## Related Failures & Blast Radius\n\n{evidence['related']}")

    if evidence.get("remediations"):
        sections.append(f"## Prior Remediation Attempts\n\n{evidence['remediations']}")

    if catalog_commands:
        sections.append(f"## Available Diagnostic Commands\n\n{chr(10).join(catalog_commands[:8])}")

    if evidence.get("constraints"):
        sections.append(f"## Declared Constraints\n\n{evidence['constraints']}")

    task = ""
    if context_type == "lab":
        task = (
            "## Task\n"
            "This is a Summit 2026 lab. Using ALL evidence above (current state, history, related failures, prior remediations), provide:\n"
            "1. Current readiness assessment (ready/at-risk/blocked) with specific evidence citations\n"
            "2. Is this a NEW issue or RECURRING? Reference the historical pattern\n"
            "3. If prior remediations were attempted, explain why they failed and what to try differently\n"
            "4. Prioritized remediation steps (most impactful first)\n"
            "5. What to verify after each remediation step\n"
            "6. If this is systemic (blast radius > 1 lab), recommend cluster-level action"
        )
    elif context_type == "cluster":
        task = (
            "## Task\n"
            "This cluster hosts Summit 2026 labs. Using ALL evidence above, provide:\n"
            "1. Root cause analysis — cite specific metrics (CPU%, VM density, failure classes)\n"
            "2. Is this trending worse? Reference the historical pattern\n"
            "3. Impact scope — how many labs are affected? Is it systemic?\n"
            "4. Specific remediation steps (with oc commands) ordered by impact\n"
            "5. Capacity recommendations based on current load vs Summit demand\n"
            "6. If prior remediations failed, explain what to try differently"
        )
    elif context_type == "pool":
        task = (
            "## Task\n"
            "This resource pool serves Summit 2026 labs. Using ALL evidence above, provide:\n"
            "1. Pool readiness assessment with specific capacity numbers\n"
            "2. Provisioning failure analysis — what's blocking new instances?\n"
            "3. Steps to increase capacity or fix provisioning (with oc commands)\n"
            "4. If this pool is chronically exhausted, recommend architectural changes\n"
            "5. Monitoring recommendations to prevent future exhaustion"
        )
    elif context_type == "error":
        task = (
            "## Task\n"
            "This failure class is occurring across Summit 2026 environments. Using ALL evidence above, provide:\n"
            "1. Root cause analysis — cite the failure messages and criteria that failed\n"
            "2. Is this isolated to specific clusters/labs or systemic? Reference blast radius\n"
            "3. Is this new or recurring? Reference evaluation history\n"
            "4. Step-by-step remediation with specific oc commands\n"
            "5. If prior remediations were tried and failed, explain the likely reason and alternative approach\n"
            "6. Prevention strategy to avoid recurrence"
        )

    sections.append(task)
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Corpus — failure class knowledge base
# ---------------------------------------------------------------------------

@router.get("/dashboard/corpus")
def dashboard_corpus():
    """Get corpus statistics — failure classes, sources, coverage."""
    from engine.corpus_runner import get_corpus_stats
    return get_corpus_stats()


@router.post("/dashboard/corpus/mine")
def dashboard_corpus_mine(db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Run all miners and load results into the DB."""
    from engine.corpus_runner import run_all_miners
    return run_all_miners(db=db)


@router.get("/dashboard/corpus/classes")
def dashboard_corpus_classes(source: Optional[str] = None):
    """List all failure classes, optionally filtered by source."""
    from engine.failure_class_loader import get_all_classes, get_classes_by_source, reload
    reload()
    if source:
        classes = get_classes_by_source(source)
    else:
        classes = get_all_classes()
    return {
        "total": len(classes),
        "source": source,
        "classes": {
            name: {
                "severity": data.get("severity"),
                "description": data.get("description", ""),
                "remediation_count": len(data.get("remediation", [])),
                "source": data.get("_source"),
            }
            for name, data in sorted(classes.items())
        },
    }


# ---------------------------------------------------------------------------
# Remediation playbook — step-by-step for dashboard consumption
# ---------------------------------------------------------------------------

@router.post("/remediation/playbook")
def run_remediation_playbook(req: dict, db: Session = Depends(get_db)):
    """Run a single remediation playbook: investigate → diagnose → fix → verify.

    Called by the platform-dashboard to visualize real remediation in the UI.
    Reuses existing StarGate infrastructure — no new logic, just orchestration.

    Body: {"namespace": "...", "failure_class": "pods_crashlooping", "pod": "...",
           "lab_code": "...", "cluster_name": "..."}
    """
    import os
    import time as _t

    namespace = req.get("namespace", "stargate-test")
    failure_class = req.get("failure_class", "pods_crashlooping")
    pod = req.get("pod", "")
    lab_code = req.get("lab_code")
    cluster_name = req.get("cluster_name")
    mock_context = req.get("mock_context", {})

    kubeconfig = os.environ.get("KUBECONFIG", "")
    start_time = _t.time()
    phases: Dict = {}

    # --- Phase 1: INVESTIGATE — collect pod logs and events ---
    investigate: Dict = {"pod_logs": "", "pod_events": [], "source": "mock"}
    if kubeconfig:
        try:
            from engine.rollback import _run_oc
            logs = _run_oc(["logs", "-n", namespace, pod, "--previous", "--tail=100"], kubeconfig, timeout=10)
            if not logs or "error" in logs.lower():
                logs = _run_oc(["logs", "-n", namespace, pod, "--tail=100"], kubeconfig, timeout=10)
            investigate["pod_logs"] = logs[:3000]

            events_raw = _run_oc(["get", "events", "-n", namespace, "--sort-by=.lastTimestamp", "-o", "json"], kubeconfig, timeout=10)
            if events_raw:
                import json as _json
                events_data = _json.loads(events_raw)
                pod_events = []
                for e in events_data.get("items", []):
                    involved = e.get("involvedObject", {}).get("name", "")
                    if pod and pod in involved:
                        pod_events.append({
                            "type": e.get("type"),
                            "reason": e.get("reason"),
                            "message": (e.get("message") or "")[:200],
                            "count": e.get("count", 1),
                        })
                investigate["pod_events"] = pod_events[-10:]
            investigate["source"] = "live"
        except Exception as e:
            investigate["source"] = "error"
            investigate["error"] = str(e)[:200]
    else:
        investigate["pod_logs"] = mock_context.get("logs", "Pod failure detected — no live logs available")
        investigate["pod_events"] = mock_context.get("events", [
            {"type": "Warning", "reason": "BackOff", "message": "Back-off restarting failed container", "count": 5},
        ])

    investigate["pod"] = pod
    investigate["namespace"] = namespace
    phases["investigate"] = investigate

    # --- Phase 2: DIAGNOSE — rubric evaluation + LLM classification ---
    from engine.chaos_scenarios import collect_real_evidence
    from engine.rubric_evaluator import evaluate_rubric
    from api.routers._shared import _load_rubric_for_stage

    evidence = {}
    eval_result = None
    rubric_stage = "deployment-ready"
    if kubeconfig:
        evidence = collect_real_evidence(namespace, kubeconfig)
    else:
        evidence = {
            "namespace_exists": True, "deployment_exists": True,
            "desired_replicas_ready": False, "no_crashloop_pods": False,
            "no_oom_killed_pods": False,
        }

    rubric = _load_rubric_for_stage(rubric_stage)
    if rubric:
        eval_result = evaluate_rubric(rubric, evidence)

    diagnose: Dict = {
        "failure_class": eval_result.failure_class if eval_result else failure_class,
        "outcome": eval_result.outcome.value if eval_result else "fail",
        "criteria": [{"name": c.name, "required": c.required, "passed": c.passed}
                     for c in (eval_result.criteria_results if eval_result else [])],
        "evidence": evidence,
        "rubric_stage": rubric_stage,
        "source": "live" if kubeconfig else "mock",
    }

    llm_classification = None
    try:
        from api.llm import call_llm, load_prompt
        prompt = load_prompt("classify")
        if prompt:
            evidence_str = (
                f"## Failure Details\n- Stage: {rubric_stage}\n"
                f"- Failure class: {diagnose['failure_class']}\n"
                f"- Evidence: {json.dumps(evidence)}\n"
                f"- Pod logs excerpt: {investigate['pod_logs'][:500]}\n\n"
                f"## Known Failure Classes\n"
                f"- " + ", ".join(sorted(get_all_classes().keys())[:30]) if 'get_all_classes' in dir() else
                f"- pods_not_ready, pods_crashlooping, deployment_missing, "
                f"route_missing, namespace_missing, showroom_not_ready"
            )
            llm_result = call_llm(
                endpoint="classify",
                messages=[
                    {"role": "system", "content": prompt.get("system", "Classify this failure. JSON only.")},
                    {"role": "user", "content": evidence_str},
                ],
                max_tokens=prompt.get("max_tokens", 500),
                temperature=prompt.get("temperature", 0.1),
                timeout=30, db=db,
                prompt_version=prompt.get("version"),
            )
            if llm_result["success"]:
                parsed = json.loads(llm_result["content"])
                llm_classification = {
                    "proposed_class": parsed.get("proposed_class"),
                    "confidence": parsed.get("confidence"),
                    "reasoning": parsed.get("reasoning"),
                    "prompt_version": prompt.get("version"),
                    "model": prompt.get("model", "granite-3-2-8b-instruct"),
                    "messages": [
                        {"role": "system", "content": prompt.get("system", "")},
                        {"role": "user", "content": evidence_str},
                    ],
                    "output": llm_result["content"],
                    "tokens_in": llm_result["usage"].get("prompt_tokens"),
                    "tokens_out": llm_result["usage"].get("completion_tokens"),
                    "latency_ms": llm_result["latency_ms"],
                }
    except Exception:
        pass

    diagnose["llm_classification"] = llm_classification
    phases["diagnose"] = diagnose

    # --- Phase 3: FIX — execute remediation action ---
    fix: Dict = {"action": "restart_crashlooping_pod", "success": False, "commands_executed": [], "source": "mock"}
    if kubeconfig and pod:
        try:
            from engine.rollback import _run_oc
            output = _run_oc(["delete", "pod", pod, "-n", namespace, "--force", "--grace-period=0"], kubeconfig, timeout=15)
            fix["commands_executed"].append({"command": f"oc delete pod {pod} -n {namespace}", "success": True, "output": output[:200]})
            fix["success"] = True
            fix["source"] = "live"
        except Exception as e:
            fix["commands_executed"].append({"command": f"oc delete pod {pod} -n {namespace}", "success": False, "error": str(e)[:200]})
    else:
        fix["success"] = True
        fix["commands_executed"] = [{"command": f"oc delete pod {pod} -n {namespace}", "success": True, "output": "pod deleted"}]

    fix["reason"] = "Failing pod deleted. Deployment controller will create a healthy replacement."
    fix["before"] = {"pod_status": mock_context.get("before_status", "Failed"), "restart_count": mock_context.get("evidence", {}).get("restart_count", 0)}
    fix["after"] = {"pod_status": "Deleted — replacement pending"}
    phases["fix"] = fix

    # --- Phase 4: VERIFY — confirm recovery ---
    import time as _t2
    _t2.sleep(5)

    verify: Dict = {"outcome": "pass", "recovery": True, "source": "mock"}
    if kubeconfig:
        evidence_after = collect_real_evidence(namespace, kubeconfig)
        eval_after = evaluate_rubric(rubric, evidence_after) if rubric else None
        verify["outcome"] = eval_after.outcome.value if eval_after else "unknown"
        verify["recovery"] = (eval_result and eval_result.outcome.value == "fail" and
                              eval_after and eval_after.outcome.value in ("pass", "warn"))
        verify["evidence_after"] = evidence_after
        verify["source"] = "live"

        pod_raw = _run_oc(["get", "pods", "-n", namespace, "-o", "json"], kubeconfig, timeout=10)
        if pod_raw:
            pod_data = json.loads(pod_raw)
            running_pods = []
            for p in pod_data.get("items", []):
                cs = p.get("status", {}).get("containerStatuses", [{}])
                running_pods.append({
                    "name": p.get("metadata", {}).get("name", ""),
                    "phase": p.get("status", {}).get("phase", "Unknown"),
                    "restart_count": cs[0].get("restartCount", 0) if cs else 0,
                    "ready": cs[0].get("ready", False) if cs else False,
                })
            verify["pods"] = running_pods
            healthy = [p for p in running_pods if p["phase"] == "Running" and p["restart_count"] == 0]
            verify["pod_status"] = healthy[0] if healthy else (running_pods[0] if running_pods else None)
    else:
        verify["pod_status"] = {"name": "replacement-pod", "phase": "Running", "restart_count": 0, "ready": True}
        verify["pods"] = [verify["pod_status"]]

    phases["verify"] = verify

    elapsed_ms = int((_t.time() - start_time) * 1000)

    return {
        "playbook": failure_class,
        "namespace": namespace,
        "pod": pod,
        "phases": phases,
        "outcome": "success" if verify.get("recovery") or verify.get("outcome") == "pass" else "failure",
        "time_ms": elapsed_ms,
        "receipt": {
            "type": "remediation-playbook",
            "playbook": failure_class,
            "steps_executed": ["investigate", "diagnose", "fix", "verify"],
            "outcome": "success" if verify.get("recovery") or verify.get("outcome") == "pass" else "failure",
            "pre_state": fix.get("before"),
            "post_state": {"pod_status": verify.get("pod_status", {}).get("phase"), "restart_count": verify.get("pod_status", {}).get("restart_count")},
            "time_ms": elapsed_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }
