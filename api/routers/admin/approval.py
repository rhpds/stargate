"""Per-lab auto-remediation config, approval queue, and execution endpoints."""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from db.database import get_db
from db import repository
from api.constants import VALID_EXECUTION_MODES
from api.routers._shared import (
    limiter,
    require_admin,
    require_admin_read,
)

logger = logging.getLogger("stargate.admin.approval")

router = APIRouter()


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
    catalog_path = Path(__file__).parent.parent.parent.parent / "remediations" / "catalog.yaml"
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

    action_type = body.action_type or ""
    if not action_type:
        for at, fcs in ACTION_TO_FAILURE_CLASSES.items():
            if failure_class in fcs:
                action_type = at
                break
        if not action_type:
            action_type = "cleanup_stuck"

    _safe_name = re.compile(r"^[a-zA-Z0-9._\-]*$")
    def _sub(cmd: str) -> str:
        return cmd.replace("{namespace}", namespace).replace("{pod}", "{pod}").replace("{deployment}", "{deployment}")

    from api.constants import REMEDIATION_ALLOWED_PREFIXES
    ns_allowed = namespace == TEST_NAMESPACE or any(
        namespace.startswith(p) for p in REMEDIATION_ALLOWED_PREFIXES
    )

    mode = _get_lab_execution_mode(db, lab_code)
    is_test = namespace == TEST_NAMESPACE

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

    commands_to_run = []
    for entry in executable_entries:
        commands_to_run.extend(entry["commands"])

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

    dry_run = _dry_run_enabled

    confidence = 1.0

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
