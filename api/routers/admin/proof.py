"""Admin proof sub-router — synthetic remediation proof system, pipeline rubric,
shadow mode, monitoring gaps, correlated views, namespace detail."""

import json
import logging
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


@router.post("/admin/proof/run-batch")
def run_proof_batch(req: dict, _auth=Depends(require_admin)):
    """Run proof cycles for multiple failure classes sequentially.

    Accepts {"failure_classes": ["pods_crashlooping", ...]} or {"failure_classes": "all"}.
    Runs sequentially because the shared test namespace can't handle parallel injections.
    """
    import threading
    from engine.proof_orchestrator import run_proof_cycle
    from engine.failure_injector import INJECTORS
    from api.routers._shared import EXECUTOR_KUBECONFIG
    from engine.proof_tracker import ProofTracker

    requested = req.get("failure_classes", [])
    mode = req.get("mode", "manual")

    if requested == "all":
        requested = list(INJECTORS.keys())
    elif requested == "untested":
        tracker = ProofTracker()
        matrix = tracker.get_matrix()
        fc_map = matrix.get("failure_classes", {})
        requested = [fc for fc in INJECTORS if fc_map.get(fc, {}).get("status", "UNTESTED") == "UNTESTED"]

    if not requested:
        return {"status": "nothing_to_run", "count": 0}

    def _run_batch():
        import logging
        logger = logging.getLogger("stargate.proof")
        for i, fc in enumerate(requested):
            logger.info("Proof batch %d/%d: %s", i + 1, len(requested), fc)
            try:
                from db.database import get_db as _get_db
                bg_db = next(_get_db())
                run_proof_cycle(failure_class=fc, kubeconfig=EXECUTOR_KUBECONFIG, mode=mode, db=bg_db)
                bg_db.close()
            except Exception as e:
                logger.error("Proof batch %s failed: %s", fc, e)

    thread = threading.Thread(target=_run_batch, daemon=True)
    thread.start()

    return {"status": "started", "count": len(requested), "failure_classes": requested}


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
        cat_path = _CatPath(__file__).parent.parent.parent.parent / "remediations" / "catalog.yaml"
        if cat_path.exists():
            try:
                cat = _yaml.safe_load(cat_path.read_text()) or []
                for entry in cat:
                    for cond in entry.get("allowed_when", []):
                        if f"failure_class == {top_fc}" in cond:
                            # Extract pod name from issue message if available
                            # K8s event format: "pod showroom-5847d87b57-glgkh_namespace(uid)"
                            _pod_name = ""
                            if issues:
                                import re as _pod_re
                                _msg = issues[0].get("message", "")
                                _pm = _pod_re.search(r"pod[/ ]([a-z0-9][a-z0-9.-]+)(?:_|\(| |$)", _msg, _pod_re.IGNORECASE)
                                if _pm:
                                    _pod_name = _pm.group(1).rstrip(".")
                            catalog_commands = [
                                cmd.replace("{namespace}", namespace).replace("{ns}", namespace)
                                   .replace("{pod}", _pod_name) if _pod_name else
                                cmd.replace("{namespace}", namespace).replace("{ns}", namespace)
                                for cmd in entry.get("commands", [])
                                if "{pod}" not in cmd or _pod_name  # skip pod commands if no pod name
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

    # Check if namespace still exists (for stale detection)
    ns_exists = True
    if cluster and issues:
        try:
            import subprocess as _sp
            import os as _os
            _secrets_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(__file__)))), "secrets")
            _kc = _os.path.join(_secrets_dir, f"kubeconfig-{cluster}")
            if not _os.path.exists(_kc):
                try:
                    from api.routers._shared import EXECUTOR_KUBECONFIG
                    _kc = EXECUTOR_KUBECONFIG
                except Exception:
                    _kc = ""
            if _kc and _os.path.exists(_kc):
                _r = _sp.run(["oc", "--kubeconfig", _kc, "get", "ns", namespace, "--no-headers"],
                             capture_output=True, text=True, timeout=8)
                ns_exists = _r.returncode == 0
        except Exception:
            pass

    return {
        "namespace": namespace,
        "cluster": cluster,
        "namespace_exists": ns_exists,
        "total_evals": total_evals,
        "pass_evals": pass_evals,
        "health_pct": round(pass_evals / max(total_evals, 1) * 100, 1),
        "issues": issues,
        "catalog_commands": catalog_commands if ns_exists else [],
        "incidents": incident_list,
        "shadow": shadow_entries,
        "eval_history": eval_history,
    }




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

    from api.constants import INFORMATIONAL_CLASSES

    # Aggregate current failure data by failure class
    fc_agg: Dict[str, Dict] = {}
    for entry in by_namespace:
        ns = entry["namespace"]
        cat = entry.get("catalog_item", "unknown")
        cluster = entry.get("cluster", "")
        d = ns_data.get(ns, {})
        att = entry.get("attention", "expected")

        for fc, cnt in d.get("failure_classes", {}).items():
            if fc in INFORMATIONAL_CLASSES:
                continue
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


