"""Deployments sub-router — summit overview, clusters."""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends
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
    _load_agnosticv_constraints,
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

    from api.constants import WARNING_CLASSES

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
        scan_dir = Path(__file__).parent.parent.parent.parent / "scan-history"
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
        agnosticv_dir = Path(agv_dir) if agv_dir else Path(__file__).parent.parent.parent.parent / "github review" / "agnosticv"
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
    from cli.scan import load_clusters
    clusters_to_check = list(load_clusters().keys())

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
