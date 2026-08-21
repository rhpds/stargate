"""Remediation sub-router — failure detail, remediation commands, evaluation matrix,
AI-assisted remediation, investigations, diagnostics, evidence helpers, corpus, audit, playbook."""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from db.database import get_db
from db import repository
from api.constants import is_ecosystem_ns as _is_ecosystem_ns
from api.routers._shared import (
    _load_latest_scan,
    _load_latest_babylon,
    _load_agnosticv_constraints,
    _fetch_labagator_sessions,
    limiter,
    require_admin,
    PIPELINE_STAGES,
    EXECUTOR_KUBECONFIG,
)

logger = logging.getLogger("stargate.dashboard.remediation")

router = APIRouter()


# ---------------------------------------------------------------------------
# Remediation commands
# ---------------------------------------------------------------------------

@router.get("/dashboard/failure-detail/{failure_class}")
def get_failure_detail(failure_class: str, cluster: str = None, since_minutes: int = 60, db: Session = Depends(get_db)):
    """Namespace-level breakdown for a failure class."""
    from db.models import EvaluationRecord

    query = db.query(EvaluationRecord).filter(
        EvaluationRecord.outcome == "fail",
        EvaluationRecord.failure_class == failure_class,
    )
    if cluster:
        query = query.filter(EvaluationRecord.cluster_name == cluster)
    if since_minutes > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
        query = query.filter(EvaluationRecord.evaluated_at >= cutoff)

    rows = query.order_by(EvaluationRecord.evaluated_at.desc()).limit(500).all()

    by_namespace: Dict[str, Dict] = {}
    for r in rows:
        ns = r.lab_code or "unknown"
        if ns not in by_namespace:
            by_namespace[ns] = {
                "namespace": ns,
                "cluster": r.cluster_name or "unknown",
                "count": 0,
                "last_seen": None,
                "messages": [],
                "is_ecosystem": _is_ecosystem_ns(ns),
            }
        by_namespace[ns]["count"] += 1
        if r.evaluated_at and (not by_namespace[ns]["last_seen"] or r.evaluated_at.isoformat() > by_namespace[ns]["last_seen"]):
            by_namespace[ns]["last_seen"] = r.evaluated_at.isoformat()
        if r.message and r.message not in by_namespace[ns]["messages"] and len(by_namespace[ns]["messages"]) < 3:
            by_namespace[ns]["messages"].append(r.message[:200])

    namespaces = sorted(by_namespace.values(), key=lambda x: (-x["count"]))

    return {
        "failure_class": failure_class,
        "total_occurrences": len(rows),
        "namespaces": namespaces,
        "cluster_filter": cluster,
    }


@router.get("/dashboard/remediation-commands/{failure_class}")
def get_remediation_commands(failure_class: str):
    """Get recommended remediation commands for a failure class from the catalog."""
    import yaml
    catalog_path = Path(__file__).parent.parent.parent.parent / "remediations" / "catalog.yaml"
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
def dashboard_evaluation_matrix(db: Session = Depends(get_db), cluster: str = None):
    """Lab x stage evaluation matrix — latest outcome per (lab_code, stage_id) pair."""
    from db.models import EvaluationRecord
    from sqlalchemy import func

    base_filter = [EvaluationRecord.lab_code.isnot(None)]
    if cluster:
        base_filter.append(EvaluationRecord.cluster_name == cluster)

    subq = (
        db.query(
            EvaluationRecord.lab_code,
            EvaluationRecord.stage_id,
            func.max(EvaluationRecord.evaluated_at).label("latest"),
        )
        .filter(*base_filter)
        .group_by(EvaluationRecord.lab_code, EvaluationRecord.stage_id)
        .subquery()
    )

    rows = (
        db.query(EvaluationRecord.lab_code, EvaluationRecord.stage_id, EvaluationRecord.outcome, EvaluationRecord.cluster_name)
        .join(
            subq,
            (EvaluationRecord.lab_code == subq.c.lab_code)
            & (EvaluationRecord.stage_id == subq.c.stage_id)
            & (EvaluationRecord.evaluated_at == subq.c.latest),
        )
        .all()
    )

    matrix: Dict[str, Dict[str, str]] = {}
    lab_clusters: Dict[str, str] = {}
    for lab_code, stage_id, outcome, cluster_name in rows:
        if lab_code not in matrix:
            matrix[lab_code] = {}
        matrix[lab_code][stage_id] = outcome.lower() if outcome else "unknown"
        if cluster_name:
            lab_clusters[lab_code] = cluster_name

    ecosystem = sorted(k for k in matrix if _is_ecosystem_ns(k))
    infrastructure = sorted(k for k in matrix if not _is_ecosystem_ns(k))
    labs = ecosystem + infrastructure

    all_clusters = sorted(set(lab_clusters.values()))

    return {
        "labs": labs,
        "stages": PIPELINE_STAGES,
        "matrix": matrix,
        "lab_clusters": lab_clusters,
        "ecosystem_labs": ecosystem,
        "infrastructure_labs": infrastructure,
        "clusters": all_clusters,
    }


@router.get("/dashboard/labs-pipeline")
def dashboard_labs_pipeline(db: Session = Depends(get_db), ecosystem_only: bool = False):
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

    # Late import to avoid circular dependency
    from api.routers.dashboard.deployments import dashboard_summit
    summit_data = dashboard_summit(db)
    labs_by_code = {l["lab_code"]: l for l in summit_data.get("labs", [])}

    result = []
    for lab_code in sorted(labs_map.keys()):
        is_eco = _is_ecosystem_ns(lab_code)
        if ecosystem_only and not is_eco:
            continue

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
            "is_ecosystem": is_eco,
        })

    result.sort(key=lambda x: (not x["is_ecosystem"], -x["fail_count"]))

    return {
        "labs": result,
        "stage_order": PIPELINE_STAGES,
        "total_labs": len(result),
        "ecosystem_count": sum(1 for r in result if r["is_ecosystem"]),
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
    """AI remediation with full evidence bundle context via configured LLM."""
    import urllib.request as urllib_req

    context_type = req.get("context_type", "error")
    if context_type == "failure_class":
        context_type = "error"
    failure_class = req.get("failure_class", "")
    lab_code = req.get("lab_code", "")
    cluster = req.get("cluster", "")
    pool_name = req.get("pool_name", "")

    catalog_path = Path(__file__).parent.parent.parent.parent / "remediations" / "catalog.yaml"
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

    evidence_context = _build_evidence_context(context_type, lab_code, cluster, pool_name, failure_class, db)

    live_diagnostics = _run_diagnostic_commands(commands, lab_code, cluster)
    if live_diagnostics:
        evidence_context["live_diagnostics"] = live_diagnostics

    prompt = _build_remediation_prompt(context_type, evidence_context, commands)

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

    quality_outcome = None
    if llm_result["success"]:
        try:
            from engine.llm_quality_gate import check_response_quality
            _, quality_result = check_response_quality(
                prompt_type="remediation",
                response=llm_result["content"],
                evidence={"raw": prompt, "failure_class": failure_class, "lab_code": lab_code},
                metadata={"cluster": cluster, "context_type": context_type},
            )
            quality_outcome = quality_result.overall_outcome.value if quality_result else None
        except Exception:
            pass

    if llm_analysis and lab_code:
        _pod_names = re.findall(r'(?:pod[/ ])([a-z0-9][a-z0-9.-]+?)(?:_|\(| |$|\n)', evidence_context.get("live_diagnostics", ""), re.IGNORECASE)
        _pod = _pod_names[0] if _pod_names else ""
        if _pod:
            llm_analysis = llm_analysis.replace("<pod_name>", _pod).replace("<pod-name>", _pod)
        llm_analysis = re.sub(r'<(deployment|service|pvc|node|pv)_name>', r'{\1}', llm_analysis)
        llm_analysis = re.sub(r'```[^\n]*\noc get resourceclaim[^\n]*\n```', '', llm_analysis)
        llm_analysis = re.sub(r'oc get resourceclaim[^\n]*', '# resourceclaim CRD is on Babylon control plane, not this cluster', llm_analysis)
        llm_analysis = _redact_sensitive(llm_analysis)

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
        "quality_outcome": quality_outcome,
    }


_INVESTIGATION_DIR = Path(__file__).parent.parent.parent.parent / "scan-history" / "investigations"


def _save_investigation(job_id: str, data: Dict):
    _INVESTIGATION_DIR.mkdir(parents=True, exist_ok=True)
    (_INVESTIGATION_DIR / f"{job_id}.json").write_text(json.dumps(data))


def _load_investigation(job_id: str) -> Optional[Dict]:
    f = _INVESTIGATION_DIR / f"{job_id}.json"
    if f.exists():
        return json.loads(f.read_text())
    return None


@router.post("/dashboard/investigate")
@limiter.limit("5/minute")
def dashboard_investigate_start(request: Request, req: dict, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Start an AI investigation — returns immediately with a job ID."""
    import threading
    import uuid
    from db.repository import create_investigation, start_investigation, complete_investigation, fail_investigation

    failure_class = req.get("failure_class", "")
    lab_code = req.get("lab_code", "")
    cluster = req.get("cluster", "")

    if not lab_code:
        return {"error": "lab_code required"}

    job_id = f"inv-{uuid.uuid4().hex[:8]}"
    create_investigation(db, job_id=job_id, lab_code=lab_code, cluster=cluster, failure_class=failure_class, trigger_type="manual")
    _save_investigation(job_id, {"status": "running", "tool_calls": [], "analysis": None, "error": None})

    def _run():
        from db.database import get_session_factory
        factory = get_session_factory()
        _db = factory()
        try:
            start_investigation(_db, job_id)

            evidence_lines = [f"Failure class: {failure_class}", f"Namespace: {lab_code}", f"Cluster: {cluster}"]

            from db.models import EvaluationRecord
            recent = _db.query(EvaluationRecord).filter(
                EvaluationRecord.lab_code == lab_code,
            ).order_by(EvaluationRecord.id.desc()).limit(5).all()
            if recent:
                evidence_lines.append("\nRecent evaluations:")
                for e in recent:
                    evidence_lines.append(f"  {e.evaluated_at}: {e.outcome} — {e.failure_class or 'none'} | {(e.message or '')[:150]}")

            from engine.investigation_agent import run_investigation
            kubeconfig_dir = os.path.dirname(EXECUTOR_KUBECONFIG) if EXECUTOR_KUBECONFIG else ""

            result = run_investigation(
                namespace=lab_code,
                cluster=cluster,
                failure_class=failure_class,
                initial_evidence="\n".join(evidence_lines),
                kubeconfig_dir=kubeconfig_dir,
                job_id=job_id,
                db=_db,
            )

            from tasks.maintenance import _extract_structured_fields
            fields = _extract_structured_fields(result.get("analysis", ""))

            complete_investigation(
                _db, job_id,
                analysis=result.get("analysis", ""),
                tool_calls=result.get("tool_calls", []),
                iterations=result.get("iterations", 0),
                model_used=os.environ.get("STARGATE_AGENT_MODEL", ""),
                root_cause=fields.get("root_cause"),
                remediation_suggestion=fields.get("remediation_suggestion"),
                fallback=result.get("fallback", False),
                error=result.get("error"),
            )
            _save_investigation(job_id, {
                "status": "complete",
                "analysis": result.get("analysis", ""),
                "tool_calls": result.get("tool_calls", []),
                "iterations": result.get("iterations", 0),
                "error": result.get("error"),
                "fallback": result.get("fallback", False),
            })
        except Exception as e:
            fail_investigation(_db, job_id, str(e))
            _save_investigation(job_id, {"status": "error", "error": str(e)[:500], "tool_calls": [], "analysis": None})
        finally:
            _db.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return {"job_id": job_id, "status": "running"}


@router.get("/dashboard/investigate/{job_id}")
def dashboard_investigate_poll(job_id: str, db: Session = Depends(get_db)):
    """Poll for investigation progress and results."""
    from db.repository import get_investigation
    record = get_investigation(db, job_id)
    if record and record.status in ("complete", "error"):
        return {
            "status": record.status,
            "analysis": record.analysis,
            "tool_calls": record.tool_calls or [],
            "iterations": record.iterations,
            "error": record.error,
            "fallback": record.fallback,
            "trigger_type": record.trigger_type,
        }
    file_result = _load_investigation(job_id)
    if file_result:
        return file_result
    if record:
        return {"status": record.status, "tool_calls": [], "analysis": None, "error": None}
    raise HTTPException(status_code=404, detail="Investigation not found")


@router.get("/dashboard/investigations")
def dashboard_investigations_list(
    lab_code: Optional[str] = None,
    cluster: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List recent investigations with optional filters."""
    from db.repository import list_investigations
    from db.models import LabMapping, ResolutionRecord, EvaluationRecord
    from engine.attention_classifier import extract_catalog_item, classify_namespace, get_cached_baselines
    from sqlalchemy import func

    records = list_investigations(db, lab_code=lab_code, cluster=cluster, status=status, limit=limit)

    lab_codes = [r.lab_code for r in records if r.lab_code]
    lab_map = {}
    if lab_codes:
        mappings = db.query(LabMapping).filter(LabMapping.lab_code.in_(lab_codes)).all()
        lab_map = {m.lab_code: m for m in mappings}

    baselines = get_cached_baselines(db)

    result = []
    for r in records:
        lm = lab_map.get(r.lab_code)
        lab_name = lm.ci_name if lm else None
        catalog_item = extract_catalog_item(r.lab_code) if r.lab_code else None
        if not lab_name and catalog_item:
            lab_name = catalog_item.replace("-", " ").title()

        current_status = None
        if r.lab_code and r.failure_class:
            latest_eval = (
                db.query(EvaluationRecord)
                .filter(
                    EvaluationRecord.lab_code == r.lab_code,
                    EvaluationRecord.failure_class == r.failure_class,
                )
                .order_by(EvaluationRecord.id.desc())
                .first()
            )
            if latest_eval:
                if latest_eval.outcome == "pass":
                    current_status = "resolved"
                else:
                    age = (datetime.now(timezone.utc) - (latest_eval.evaluated_at.replace(tzinfo=timezone.utc) if latest_eval.evaluated_at.tzinfo is None else latest_eval.evaluated_at)).total_seconds()
                    if age > 3600:
                        current_status = "stale"
                    else:
                        current_status = "active"
            else:
                current_status = "unknown"

        attention = None
        attention_reason = None
        if r.lab_code and r.failure_class and current_status == "active":
            try:
                first_eval_at = db.query(
                    func.min(EvaluationRecord.evaluated_at)
                ).filter(EvaluationRecord.lab_code == r.lab_code).scalar()
                cl = classify_namespace(
                    r.lab_code, catalog_item or "",
                    {r.failure_class: 1}, first_eval_at, baselines,
                )
                attention = cl.get("attention")
                attention_reason = cl.get("reason")
            except Exception:
                pass

        resolved = None
        if r.resolved_by_id:
            res = db.query(ResolutionRecord).filter(ResolutionRecord.id == r.resolved_by_id).first()
            if res:
                resolved = {
                    "resolution_type": res.resolution_type,
                    "ttr_minutes": round(res.ttr_seconds / 60, 1) if res.ttr_seconds else None,
                }

        result.append({
            "job_id": r.job_id,
            "lab_code": r.lab_code,
            "cluster": r.cluster,
            "failure_class": r.failure_class,
            "trigger_type": r.trigger_type,
            "status": r.status,
            "iterations": r.iterations,
            "root_cause": r.root_cause,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "has_analysis": bool(r.analysis),
            "lab_name": lab_name,
            "catalog_item": catalog_item,
            "owner": lm.owner if lm else None,
            "cloud": lm.cloud if lm else None,
            "current_status": current_status,
            "verdict": (r.trust_dimensions or {}).get("verdict"),
            "attention": attention,
            "attention_reason": attention_reason,
            "resolution": resolved,
        })
    return result


@router.get("/dashboard/investigations/stats")
def dashboard_investigations_stats(db: Session = Depends(get_db)):
    """Investigation stats for the dashboard — no admin auth required."""
    from db.models import InvestigationRecord
    from db.repository import count_investigations_today
    from sqlalchemy import func

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    today_count = count_investigations_today(db)
    queue_depth = db.query(InvestigationRecord).filter(InvestigationRecord.status.in_(("queued", "dispatched"))).count()

    stuck_today = db.query(InvestigationRecord).filter(
        InvestigationRecord.created_at >= today_start,
        InvestigationRecord.trigger_type == "auto_stuck",
    ).count()
    anomalous_today = db.query(InvestigationRecord).filter(
        InvestigationRecord.created_at >= today_start,
        InvestigationRecord.trigger_type == "auto_anomalous",
    ).count()

    by_trigger = db.query(
        InvestigationRecord.trigger_type, func.count(),
    ).filter(InvestigationRecord.created_at >= today_start).group_by(
        InvestigationRecord.trigger_type,
    ).all()

    avg_cost = db.query(func.avg(InvestigationRecord.cost_estimate)).filter(
        InvestigationRecord.created_at >= today_start,
        InvestigationRecord.cost_estimate.isnot(None),
    ).scalar()

    enabled = os.environ.get("STARGATE_AUTO_INVESTIGATE", "false").lower() == "true"
    max_stuck = int(os.environ.get("STARGATE_INVESTIGATE_MAX_STUCK_PER_DAY", "100"))
    max_anomalous = int(os.environ.get("STARGATE_INVESTIGATE_MAX_ANOMALOUS_PER_DAY", "50"))

    return {
        "today": today_count,
        "queue_depth": queue_depth,
        "stuck_today": stuck_today,
        "stuck_max": max_stuck,
        "anomalous_today": anomalous_today,
        "anomalous_max": max_anomalous,
        "by_trigger_type": {t: c for t, c in by_trigger},
        "avg_cost_today": round(avg_cost, 4) if avg_cost else None,
        "enabled": enabled,
        "max_per_catalog_hour": int(os.environ.get("STARGATE_INVESTIGATE_MAX_PER_CATALOG_HOUR", "3")),
    }


# ---------------------------------------------------------------------------
# Read-only diagnostic command runner
# ---------------------------------------------------------------------------

_SAFE_OC_VERBS = frozenset({"get", "describe", "logs", "status", "whoami", "version", "api-resources", "adm", "explain", "api-versions"})
_BLOCKED_FLAGS = frozenset({"--force", "--grace-period=0", "-f", "--filename", "--dry-run=none"})
_SAFE_ADM_SUBCOMMANDS = frozenset({"top", "node-logs", "inspect", "must-gather"})

_SAFE_PIPE_COMMANDS = {"grep", "head", "tail", "wc", "sort", "uniq", "cut", "awk", "sed", "tr", "column"}


def _is_safe_command(cmd: str) -> bool:
    """Only allow read-only oc commands, optionally piped to safe filters."""
    segments = [s.strip() for s in cmd.split("|")]

    parts = segments[0].split()
    if not parts or parts[0] != "oc":
        return False
    verb = parts[1] if len(parts) > 1 else ""
    if verb not in _SAFE_OC_VERBS:
        return False
    if verb == "adm":
        adm_sub = parts[2] if len(parts) > 2 else ""
        if adm_sub not in _SAFE_ADM_SUBCOMMANDS:
            return False
    for flag in _BLOCKED_FLAGS:
        if flag in parts:
            return False

    for seg in segments[1:]:
        seg_parts = seg.split()
        if not seg_parts:
            return False
        if seg_parts[0] not in _SAFE_PIPE_COMMANDS:
            return False

    return True


_BASELINE_DIAGNOSTICS = [
    "oc get pods -n {namespace} -o wide",
    "oc get events -n {namespace} --sort-by=.lastTimestamp",
    "oc get svc -n {namespace}",
    "oc get pvc -n {namespace}",
]


_SENSITIVE_PATTERNS = re.compile(
    r'('
    r'(?:password|passwd|secret|token|key|auth|credential|api.key|ssh.pass|vault.password|activationkey)'
    r'(?:\s*[:=]\s*|\s*\n\s*value:\s*))'
    r'(\S+)',
    re.IGNORECASE,
)
_YAML_SECRET_VALUE = re.compile(
    r'((?:PASSWORD|PASSWD|SECRET|TOKEN|KEY|AUTH|CREDENTIAL|VAULT_PASSWORD|ACTIVATIONKEY|ssh.pass)["\s]*\n\s*value:\s*)(\S+)',
    re.IGNORECASE,
)
_CERT_BLOCK = re.compile(r'-----BEGIN [A-Z ]+-----[\s\S]*?-----END [A-Z ]+-----')
_BEARER_TOKEN = re.compile(r'(Bearer\s+|token["\s:=]+)([A-Za-z0-9._-]{20,})')
_LONG_BASE64 = re.compile(r'[A-Za-z0-9+/=]{60,}')


def _redact_sensitive(text: str) -> str:
    """Redact passwords, tokens, certificates, and long base64 from command output."""
    if not text:
        return text or ""
    text = _CERT_BLOCK.sub('[CERTIFICATE REDACTED]', text)
    text = _YAML_SECRET_VALUE.sub(r'\1[REDACTED]', text)
    text = _SENSITIVE_PATTERNS.sub(r'\1[REDACTED]', text)
    text = _BEARER_TOKEN.sub(r'\1[REDACTED]', text)
    text = _LONG_BASE64.sub('[REDACTED]', text)
    return text


def _run_diagnostic_commands(
    catalog_commands: List[str],
    namespace: str,
    cluster: str,
    max_commands: int = 6,
    timeout_per_cmd: int = 8,
) -> str:
    """Run read-only diagnostic commands against the real cluster."""
    import subprocess

    if not EXECUTOR_KUBECONFIG or not os.path.exists(EXECUTOR_KUBECONFIG):
        return ""
    if not namespace:
        return ""

    kubeconfig = EXECUTOR_KUBECONFIG
    if cluster:
        secrets_dir = os.path.dirname(EXECUTOR_KUBECONFIG)
        cluster_kc = os.path.join(secrets_dir, f"kubeconfig-{cluster}")
        if os.path.exists(cluster_kc):
            kubeconfig = cluster_kc

    all_cmds = list(_BASELINE_DIAGNOSTICS)
    for c in catalog_commands:
        if c not in all_cmds:
            all_cmds.append(c)

    results = []
    executed = 0

    for raw_cmd in all_cmds:
        if executed >= max_commands:
            break

        cmd = raw_cmd.replace("{namespace}", namespace).replace("{cluster}", cluster or "")
        if "{" in cmd:
            continue
        if not _is_safe_command(cmd):
            continue

        try:
            use_shell = "|" in cmd
            r = subprocess.run(
                cmd if use_shell else cmd.split(),
                capture_output=True,
                text=True,
                timeout=timeout_per_cmd,
                shell=use_shell,
                env={**os.environ, "KUBECONFIG": kubeconfig},
            )
            output = r.stdout.strip() if r.returncode == 0 else f"ERROR: {r.stderr.strip()}"
            output = _redact_sensitive(output)
            if len(output) > 2000:
                output = output[:2000] + "\n... (truncated)"
            results.append(f"$ {cmd}\n{output}")
            executed += 1
        except subprocess.TimeoutExpired:
            results.append(f"$ {cmd}\nERROR: command timed out after {timeout_per_cmd}s")
            executed += 1
        except Exception as e:
            logger.warning(f"Diagnostic command failed: {cmd} — {e}")

    return "\n\n".join(results)


# ---------------------------------------------------------------------------
# Helper functions (used only by remediation endpoints)
# ---------------------------------------------------------------------------

def _build_evidence_context(context_type: str, lab_code: str, cluster: str, pool_name: str, failure_class: str, db) -> Dict:
    """Assemble comprehensive evidence bundle for LLM context."""
    ctx: Dict = {"summary": "", "details": {}, "history": "", "related": "", "remediations": "", "constraints": ""}

    history_lines = []
    related_lines = []
    remediation_lines = []

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

    from engine.namespace import strip_sandbox_prefix, is_sandbox
    agnosticv_lookup = strip_sandbox_prefix(lab_code) if lab_code else lab_code
    constraints = _load_agnosticv_constraints(agnosticv_lookup) if agnosticv_lookup else None
    if not constraints and lab_code != agnosticv_lookup:
        constraints = _load_agnosticv_constraints(lab_code)
    if constraints:
        constraint_lines = [f"AgnosticV spec for {agnosticv_lookup}:"]
        for k, v in list(constraints.items())[:15]:
            constraint_lines.append(f"  {k}: {v}")
        ctx["constraints"] = "\n".join(constraint_lines)

    if lab_code and is_sandbox(lab_code):
        from engine.namespace import extract_guid
        _guid = extract_guid(lab_code)
        rhdp_lines = []

        try:
            from db.models import LabMapping
            _lm = db.query(LabMapping).filter(LabMapping.lab_code == f"guid:{_guid}").first()
            if _lm:
                if _lm.ci_name:
                    rhdp_lines.append(f"Lab name: {_lm.ci_name}")
                if _lm.ci_slug:
                    rhdp_lines.append(f"AgnosticD governor: {_lm.ci_slug}")
                if _lm.agnosticv_path:
                    rhdp_lines.append(f"AgnosticV config: {_lm.agnosticv_path}")
                    rhdp_lines.append(f"Config URL: https://github.com/rhpds/agnosticv/tree/main/{_lm.agnosticv_path}")
                if _lm.owner:
                    rhdp_lines.append(f"Owner: {_lm.owner}")
        except Exception:
            pass

        try:
            babylon = _load_latest_babylon()
            if babylon:
                all_pools = babylon.get("pools", {}).get("all_pools", [])
                slug = strip_sandbox_prefix(lab_code)
                matching_pools = [p for p in all_pools if slug in p.get("name", "").lower()]
                for p in matching_pools[:2]:
                    rhdp_lines.append(f"Pool {p.get('name','?')}: {p.get('available',0)} available, {p.get('min_available',0)} min, {p.get('ready',0)} ready")
                if not matching_pools:
                    prov = babylon.get("provisioning", {})
                    rhdp_lines.append(f"Platform provisioning: {prov.get('total',0)} subjects, {prov.get('started',0)} started, {prov.get('failed',0)} failed ({prov.get('failure_rate',0)}%)")
        except Exception:
            pass

        try:
            from db.models import ResolutionRecord
            _resolutions = db.query(ResolutionRecord).filter(
                ResolutionRecord.lab_code == lab_code,
            ).order_by(ResolutionRecord.resolved_at.desc()).limit(5).all()
            if _resolutions:
                rhdp_lines.append(f"Resolution history ({len(_resolutions)} recent):")
                for _r in _resolutions:
                    rhdp_lines.append(f"  {_r.failure_class}: {_r.resolution_type} — {_r.resolution_action or '?'} (TTR: {round(_r.ttr_seconds/60,1) if _r.ttr_seconds else '?'}m)")
        except Exception:
            pass

        if rhdp_lines:
            ctx["rhdp_stack"] = "\n".join(rhdp_lines)

    if context_type == "lab":
        babylon = _load_latest_babylon()
        lab_info = babylon.get("labagator", {}).get("labs_by_code", {}).get(lab_code, {})
        all_pools = babylon.get("pools", {}).get("all_pools", [])
        lab_pools = [p for p in all_pools if lab_code.lower() in p.get("name", "").lower()]
        prov = babylon.get("provisioning", {})
        mapping = babylon.get("lab_mapping", babylon.get("summit_mapping", {})).get(lab_code, [])
        demolition = babylon.get("demolition", babylon.get("demolition_summit", {}))

        inst_started = sum(1 for i in mapping if i.get("state") == "started")
        inst_failed = sum(1 for i in mapping if "failed" in (i.get("state") or ""))
        inst_total = len(mapping)

        demo_sessions = demolition.get("sessions", []) if isinstance(demolition, dict) else []
        lab_demo = [s for s in demo_sessions if lab_code.lower() in s.get("name", "").lower()] if demo_sessions else []

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
        all_pools = babylon.get("pools", {}).get("all_pools", [])
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

    if evidence.get("live_diagnostics"):
        sections.append(f"## Live Cluster Diagnostics (read-only)\n\nThe following commands were executed against the real cluster. Analyze this output to diagnose the issue.\n\n{evidence['live_diagnostics']}")
    elif catalog_commands:
        sections.append(f"## Available Diagnostic Commands (not yet executed)\n\n{chr(10).join(catalog_commands[:8])}")

    if evidence.get("constraints"):
        sections.append(f"## Declared Constraints\n\n{evidence['constraints']}")

    if evidence.get("rhdp_stack"):
        sections.append(
            f"## RHDP Stack Context\n\n"
            f"This sandbox is part of the Red Hat Demo Platform (RHDP). The following data comes from "
            f"the Babylon control plane (AnarchySubject, ResourceClaim), AgnosticV catalog, and "
            f"Poolboy resource pools. Use this to determine whether the issue is in the lab config "
            f"(AgnosticV/AgnosticD), the provisioning pipeline (Babylon/Poolboy), or the cluster.\n\n"
            f"{evidence['rhdp_stack']}"
        )
        if evidence.get("agnosticv_url"):
            sections.append(f"AgnosticV config: {evidence['agnosticv_url']}")

    task = ""
    if context_type == "lab":
        task = (
            "## Task\n"
            "Diagnose this lab and produce an executable remediation plan.\n\n"
            "1. **Diagnosis**: What is broken and why? Quote the specific failure messages, counts, and trend from the evidence. No generic statements.\n"
            "2. **Root cause**: Is this a lab-level config issue, a cluster-level resource issue, or a platform-level systemic issue? Cite the blast radius data.\n"
            "3. **Fix** (ordered by impact):\n"
            "   - For each step: the exact `oc` command using the real namespace/cluster from the evidence\n"
            "   - What the output should look like if the fix worked\n"
            "   - What to do if it didn't work\n"
            "4. **If evidence is insufficient**: State exactly what additional commands to run and what to look for in the output."
        )
    elif context_type == "cluster":
        task = (
            "## Task\n"
            "Diagnose this cluster and produce an executable remediation plan.\n\n"
            "1. **Diagnosis**: What is failing and at what rate? Quote CPU%, VM counts, failure class counts from the evidence.\n"
            "2. **Scope**: How many labs are affected? Is this isolated or systemic? Cite the numbers.\n"
            "3. **Fix** (ordered by impact):\n"
            "   - For each step: the exact `oc` command with the real cluster/namespace\n"
            "   - Expected output if the fix worked\n"
            "4. **Capacity**: Based on the current load numbers, is the cluster over-committed? What's the headroom?"
        )
    elif context_type == "pool":
        task = (
            "## Task\n"
            "Diagnose this resource pool and produce an executable remediation plan.\n\n"
            "1. **Diagnosis**: What is the current capacity vs demand? Quote the available/ready/min numbers.\n"
            "2. **Root cause**: Why are provisions failing? Cite the failure rate and error patterns.\n"
            "3. **Fix**: Exact `oc` commands to increase capacity or unblock provisioning.\n"
            "4. **Prevention**: What monitoring threshold would catch this before it impacts labs?"
        )
    elif context_type == "error":
        task = (
            "## Task\n"
            "Diagnose this failure class and produce an executable remediation plan.\n\n"
            "1. **Diagnosis**: What is the actual error? Quote the sample messages from the evidence verbatim. Explain what they mean operationally.\n"
            "2. **Scope**: {how many} occurrences across {which clusters} and {how many labs}. Is this isolated or systemic? Cite the blast radius.\n"
            "3. **Root cause**: Based on the error messages and criteria failures, what is the most likely underlying cause? Be specific — name the component, resource, or config that is failing.\n"
            "4. **Fix** (ordered by blast radius):\n"
            "   - For each step: the exact `oc` command using the real namespaces and clusters from the evidence\n"
            "   - What to look for in the output to confirm the diagnosis\n"
            "   - The fix command and how to verify it worked\n"
            "5. **If prior remediations failed**: Why did they fail? What specifically to try differently?"
        )

    sections.append(task)
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Diagnostics + Remediation playbook
# ---------------------------------------------------------------------------

@router.post("/admin/diagnostics/run")
@limiter.limit("30/minute")
def run_diagnostic_command(request: Request, req: dict, _auth=Depends(require_admin)):
    """Execute a single read-only diagnostic command against a cluster."""
    import subprocess

    cmd = req.get("command", "").strip()
    namespace = req.get("namespace", "")
    cluster = req.get("cluster", "")

    if not cmd:
        raise HTTPException(status_code=400, detail="command is required")
    if not namespace:
        raise HTTPException(status_code=400, detail="namespace is required")

    resolved = cmd.replace("{namespace}", namespace).replace("{cluster}", cluster or "")
    if "{" in resolved:
        raise HTTPException(status_code=400, detail="Command has unresolved placeholders")
    if not _is_safe_command(resolved):
        raise HTTPException(status_code=403, detail="Command rejected — only read-only oc commands allowed")

    kubeconfig = EXECUTOR_KUBECONFIG
    if cluster:
        secrets_dir = os.path.dirname(EXECUTOR_KUBECONFIG)
        cluster_kc = os.path.join(secrets_dir, f"kubeconfig-{cluster}")
        if os.path.exists(cluster_kc):
            kubeconfig = cluster_kc

    if not kubeconfig or not os.path.exists(kubeconfig):
        raise HTTPException(status_code=503, detail="No kubeconfig available for this cluster")

    try:
        use_shell = "|" in resolved
        r = subprocess.run(
            resolved if use_shell else resolved.split(),
            capture_output=True,
            text=True,
            timeout=15,
            shell=use_shell,
            env={**os.environ, "KUBECONFIG": kubeconfig},
        )
        return {
            "command": resolved,
            "output": _redact_sensitive(r.stdout.strip() if r.returncode == 0 else r.stderr.strip()),
            "exit_code": r.returncode,
            "cluster": cluster,
            "namespace": namespace,
        }
    except subprocess.TimeoutExpired:
        return {"command": resolved, "output": "Command timed out after 15s", "exit_code": -1, "cluster": cluster, "namespace": namespace}


@router.post("/remediation/playbook")
def run_remediation_playbook(req: "PlaybookRunRequest", db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Run a single remediation playbook: investigate → diagnose → fix → verify."""
    import os
    import re
    import time as _t
    from api.schemas import PlaybookRunRequest  # noqa: F811

    _K8S_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,252}$")

    namespace = req.namespace
    failure_class = req.failure_class
    pod = req.pod
    lab_code = req.lab_code
    cluster_name = req.cluster_name
    mock_context = req.mock_context

    if namespace and not _K8S_NAME.match(namespace):
        raise HTTPException(status_code=422, detail="Invalid namespace name")
    if pod and not _K8S_NAME.match(pod):
        raise HTTPException(status_code=422, detail="Invalid pod name")

    kubeconfig = os.environ.get("KUBECONFIG", "")
    start_time = _t.time()
    phases: Dict = {}

    # --- Phase 1: INVESTIGATE ---
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

    # --- Phase 2: DIAGNOSE ---
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
        from api.llm import call_llm, load_prompt, LLM_MODEL
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
                    "model": prompt.get("model", LLM_MODEL),
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

    # --- Phase 3: FIX ---
    fix: Dict = {"action": "restart_crashlooping_pod", "success": False, "commands_executed": [], "source": "mock"}
    if kubeconfig and pod:
        try:
            from api.action_executor import execute_action
            result = execute_action(
                action_type="cleanup_stuck",
                target=namespace,
                parameters={"pods": [pod], "failure_class": failure_class, "cluster": cluster_name, "triggered_by": "playbook"},
                confidence=1.0,
                db=db,
                lab_code=lab_code,
            )
            fix["success"] = result.get("executed", False)
            fix["source"] = "live" if result.get("executed") else "blocked"
            fix["commands_executed"] = result.get("commands_executed", [])
            if not fix["success"]:
                fix["blocked_reason"] = result.get("reason", "execution gate blocked")
        except Exception as e:
            fix["commands_executed"].append({"command": f"oc delete pod {pod} -n {namespace}", "success": False, "error": str(e)[:200]})
    else:
        fix["success"] = True
        fix["commands_executed"] = [{"command": f"oc delete pod {pod} -n {namespace}", "success": True, "output": "pod deleted"}]

    fix["reason"] = "Failing pod deleted. Deployment controller will create a healthy replacement."
    fix["before"] = {"pod_status": mock_context.get("before_status", "Failed"), "restart_count": mock_context.get("evidence", {}).get("restart_count", 0)}
    fix["after"] = {"pod_status": "Deleted — replacement pending"}
    phases["fix"] = fix

    # --- Phase 4: VERIFY ---
    import time as _t2
    _t2.sleep(5)

    verify: Dict = {"outcome": "pass", "recovery": True, "source": "mock"}
    if kubeconfig:
        from engine.rollback import _run_oc
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
