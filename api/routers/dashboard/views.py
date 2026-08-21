"""Dashboard views — lab detail, ZeroTouch, Sandbox-API, visual storytelling,
data health, data mapping, corpus, and audit ledger endpoints."""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.database import get_db
from db import repository
from api.routers._shared import (
    _event_bus,
    _load_latest_babylon,
    _load_latest_scan,
    _load_agnosticv_constraints,
    _fetch_labagator_labs,
    _fetch_labagator_sessions,
    _fetch_demolition_sessions,
    _get_lab_namespaces,
    require_admin,
)

logger = logging.getLogger("stargate.dashboard.views")

router = APIRouter()


# ---------------------------------------------------------------------------
# Lab detail
# ---------------------------------------------------------------------------

@router.get("/dashboard/lab/{lab_code}")
def dashboard_lab(lab_code: str, db: Session = Depends(get_db)):
    """Single lab deep dive — evaluation history, constraints, sessions."""
    import urllib.request as urllib_req
    from api.routers._shared import _make_ssl_context
    ctx = _make_ssl_context()

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
        "provisioning": _get_lab_provisioning(lab_code),
    }


def _get_lab_constraint_violations(lab_code: str, constraints: Dict) -> list:
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


def _get_lab_provisioning(lab_code: str) -> Dict:
    """Get provisioning data for a specific lab from Babylon cache."""
    babylon = _load_latest_babylon()
    instance_mapping = babylon.get("instance_mapping", babylon.get("summit_mapping", {}))
    instances = instance_mapping.get(lab_code, [])
    by_state: Dict[str, int] = {}
    for inst in instances:
        st = inst.get("state", "unknown")
        by_state[st] = by_state.get(st, 0) + 1

    pools_data = babylon.get("pools", {})
    all_pools = pools_data.get("all_pools", pools_data.get("summit_pools", []))
    lab_slug = lab_code.lower()
    linked_pools = [
        {"name": p["name"], "available": p.get("available", 0), "ready": p.get("ready", 0), "min": p.get("min", 0)}
        for p in all_pools if isinstance(p, dict) and lab_slug in p.get("name", "").lower()
    ]

    from api.routers._shared import _fetch_launchpad_sessions
    launchpad_sessions = [s for s in _fetch_launchpad_sessions() if s.get("lab_code", "").lower() == lab_slug]

    return {
        "instances": instances[:100],
        "instance_summary": {"total": len(instances), "by_state": by_state},
        "pools": linked_pools,
        "launchpad_sessions": launchpad_sessions,
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
        from api.routers.dashboard.deployments import dashboard_summit
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
        from api.routers.dashboard.deployments import dashboard_summit
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
    from api.routers.dashboard.deployments import dashboard_summit

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

        src_labagator = {"connected": True, "key": f"lab_code={code}"}

        has_instances = lab.get("instances_total", 0) > 0 or len(summit_mapping.get(code, [])) > 0
        has_smoke = lab.get("demolition_status", "none") != "none"
        has_scanned = lab.get("last_scanned") is not None
        babylon_connected = has_instances or has_smoke or has_scanned
        src_babylon = {"connected": babylon_connected, "key": f"instances={lab.get('instances_total',0)}, smoke={has_smoke}, scanned={has_scanned}"}
        if not babylon_connected:
            issues.append("babylon: not provisioned (no instances, no smoke tests, no scans)")

        cloud_pool_map = {"CNV": "openshift-cnv", "AWS": "clusterplatform", "Tenant Namespace": None}
        pool_prefix = cloud_pool_map.get(cloud)
        pool_connected = False
        pool_key = f"cloud={cloud}"
        if lab.get("provisioned", 0) > 0 or lab.get("capacity", 0) > 0:
            pool_connected = True
            pool_key = f"provisioned={lab.get('provisioned',0)}"
        elif pool_prefix:
            pool_connected = any(p.get("name", "").startswith(pool_prefix) for p in babylon.get("pools", {}).get("all_pools", []))
            pool_key = f"{cloud}→{pool_prefix}.*"
        elif cloud == "Tenant Namespace":
            pool_connected = True
            pool_key = "Tenant Namespace (no pool needed)"
        elif ci_base and ci_base != "summit-2026":
            pool_connected = any(p.get("name", "").startswith(ci_base) for p in babylon.get("pools", {}).get("all_pools", []))
            pool_key = f"ci_base={ci_base}"
        src_pools = {"connected": pool_connected, "key": pool_key}
        if not pool_connected:
            issues.append(f"pools: no pool for cloud={cloud}")

        demo_connected = lab.get("demolition_status", "none") != "none"
        src_demolition = {"connected": demo_connected, "key": f"status={lab.get('demolition_status','none')}", "total": lab.get("demolition_total", 0)}
        if not demo_connected:
            issues.append("demolition: no smoke test results")

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

        lab_ci = lab.get("ci_name", "")
        constraints = _load_agnosticv_constraints(code, ci_name=lab_ci)
        agv_connected = constraints is not None and len(constraints) > 0
        src_agnosticv = {"connected": agv_connected, "key": f"slug={ci_slug}" if ci_slug else f"prefix={code.lower()}", "fields": len(constraints) if constraints else 0}
        if not agv_connected:
            issues.append("agnosticv: no matching directory")

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
# Audit ledger — hash-chained tamper-proof trail
# ---------------------------------------------------------------------------

@router.get("/dashboard/audit-ledger")
def dashboard_audit_ledger():
    """Get the current audit ledger chain with integrity verification."""
    try:
        from integrations.kafka_publisher import _get_ledger
        ledger = _get_ledger()
        chain = ledger.export_chain()
        valid = ledger.verify_chain()
        return {
            "chain_length": len(chain),
            "chain_valid": valid,
            "latest_hash": chain[-1]["hash"] if chain else None,
            "latest_sequence": chain[-1]["sequence"] if chain else -1,
            "entries": chain[-20:],
        }
    except Exception as e:
        return {"chain_length": 0, "chain_valid": True, "error": str(e)}


@router.post("/dashboard/audit-ledger/verify")
def verify_audit_chain(chain: list, _auth=Depends(require_admin)):
    """Verify an exported audit chain for tamper detection."""
    from engine.audit_ledger import AuditLedger
    valid = AuditLedger.verify_exported_chain(chain)
    broken_at = None
    if not valid:
        for i, entry in enumerate(chain):
            if i == 0:
                continue
            if entry.get("prev_hash") != chain[i-1].get("hash"):
                broken_at = i
                break
    return {"valid": valid, "entries_checked": len(chain), "broken_at_sequence": broken_at}
