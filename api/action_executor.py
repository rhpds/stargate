"""Action executor — dry-run gate, confidence gate, audit trail.

Sits between recommendation engine and actual execution. All actions
flow through execute_action() which checks:
1. Dry-run mode → log and skip
2. Confidence gate → queue if below threshold
3. Audit trail → write entry before and after
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("stargate.executor")


def _get_lab_execution_mode(db: Optional[Session], lab_code: Optional[str]) -> str:
    """Look up the per-lab execution mode. Returns 'recommend_only' by default."""
    if not db or not lab_code:
        return "recommend_only"
    try:
        from db import repository
        config = repository.get_lab_remediation_config(db, lab_code)
        return config.execution_mode if config else "recommend_only"
    except Exception:
        return "recommend_only"


def _check_rate_limit(db: Optional[Session], lab_code: str, max_per_hour: int) -> bool:
    """Return True if the lab has exceeded its hourly action limit."""
    if not db or not lab_code:
        return False
    try:
        from db import repository
        count = repository.count_recent_actions(db, lab_code, hours=1)
        return count >= max_per_hour
    except Exception:
        return False


def execute_action(
    action_type: str,
    target: str,
    parameters: Dict[str, Any],
    confidence: float = 1.0,
    db: Optional[Session] = None,
    evidence_source: str = "real",
    scenario_name: Optional[str] = None,
    lab_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute an action with lab-mode, dry-run, confidence, and audit gates."""
    from api.routers._shared import _dry_run_enabled, CONFIDENCE_THRESHOLD, TEST_NAMESPACE

    now = datetime.now(timezone.utc)
    audit_params = {
        "evidence_source": evidence_source,
        "scenario_name": scenario_name,
        "confidence": confidence,
        "recommendation_type": action_type,
        "lab_code": lab_code,
        **parameters,
    }

    # Write audit entry (proposed)
    audit_id = None
    if db:
        try:
            from db.models import AuditLog
            entry = AuditLog(
                action_type=action_type,
                target=target,
                parameters=audit_params,
                proposed_by="stargate-policy-engine",
                status="proposed",
                created_at=now,
            )
            db.add(entry)
            db.commit()
            audit_id = entry.id
        except Exception as e:
            logger.warning(f"Failed to write audit entry: {e}")

    # Gate -1: namespace allowlist — NEVER remediate outside our ecosystem
    REMEDIATION_ALLOWED_PREFIXES = os.environ.get(
        "STARGATE_REMEDIATION_NS",
        "launchpad-,stargate,deepfield,intel-rh-,user-demo-,partner-ai-",
    ).split(",")
    target_ns = target or parameters.get("namespace", "")
    ns_allowed = target_ns == TEST_NAMESPACE or any(
        target_ns.startswith(p.strip()) for p in REMEDIATION_ALLOWED_PREFIXES if p.strip()
    )
    if not ns_allowed:
        _update_audit(db, audit_id, "blocked_namespace")
        logger.warning(f"BLOCKED: {action_type} on {target_ns} — outside remediation namespace allowlist")
        return {"executed": False, "reason": "namespace_not_allowed", "namespace": target_ns, "audit_id": audit_id}

    # Gate 0: lab execution mode (stargate-test always passes)
    is_test_ns = target_ns == TEST_NAMESPACE
    if not is_test_ns:
        mode = _get_lab_execution_mode(db, lab_code)
        if mode == "recommend_only":
            _update_audit(db, audit_id, "skipped_recommend_only")
            logger.info(f"RECOMMEND ONLY: {action_type} on {target} (lab={lab_code}) — skipped")
            return {"executed": False, "reason": "recommend_only", "audit_id": audit_id}

        from engine.models import RemediationRisk
        max_risk = RemediationRisk.LOW if mode == "low_risk_auto" else RemediationRisk.MEDIUM
        from engine.catalog_loader import get_commands_for_action
        allowed_commands = get_commands_for_action(action_type, target, parameters, max_risk=max_risk)
        if not allowed_commands:
            _update_audit(db, audit_id, "skipped_risk_too_high")
            logger.info(f"RISK GATE: {action_type} on {target} — no commands at risk<={max_risk.value}")
            return {"executed": False, "reason": "risk_too_high", "max_risk": max_risk.value, "audit_id": audit_id}

        if db and lab_code:
            from db import repository as repo
            config = repo.get_lab_remediation_config(db, lab_code)
            max_per_hour = config.max_actions_per_hour if config else 5
            if _check_rate_limit(db, lab_code, max_per_hour):
                _update_audit(db, audit_id, "skipped_rate_limit")
                logger.info(f"RATE LIMIT: {action_type} on {target} (lab={lab_code}) — {max_per_hour}/hr exceeded")
                return {"executed": False, "reason": "rate_limited", "audit_id": audit_id}

    # Gate 1: dry-run
    if _dry_run_enabled:
        _update_audit(db, audit_id, "skipped_dry_run")
        logger.info(f"DRY RUN: {action_type} on {target} — skipped")
        return {"executed": False, "reason": "dry_run", "audit_id": audit_id}

    # Gate 2: confidence
    if confidence < CONFIDENCE_THRESHOLD:
        pending_id = _queue_for_approval(db, action_type, target, parameters, confidence, now)
        _update_audit(db, audit_id, "queued_low_confidence")
        logger.info(f"LOW CONFIDENCE ({confidence}): {action_type} on {target} — queued for approval")
        _notify_pending_approval(action_type, target, confidence, pending_id)
        return {"executed": False, "reason": "low_confidence", "pending_id": pending_id, "audit_id": audit_id}

    # Execute
    result = _do_execute(action_type, target, parameters)
    _update_audit(db, audit_id, "executed" if result.get("success") else "failed")
    return {"executed": True, "result": result, "audit_id": audit_id}


def _notify_pending_approval(action_type, target, confidence, pending_id):
    """Send Slack notification for pending approval."""
    import os
    webhook_url = os.environ.get("STARGATE_SLACK_WEBHOOK_URL")
    if not webhook_url:
        return
    try:
        import urllib.request
        import json
        payload = json.dumps({
            "text": f":warning: *StarGate Action Pending Approval*\n"
                    f"• Action: `{action_type}`\n"
                    f"• Target: `{target}`\n"
                    f"• Confidence: {confidence*100:.0f}%\n"
                    f"• Pending ID: #{pending_id}\n"
                    f"• <{os.environ.get('STARGATE_DASHBOARD_URL', '')}/admin|Review in Dashboard>",
        }).encode()
        req = urllib.request.Request(webhook_url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logger.debug(f"Slack notification failed: {e}")


def _queue_for_approval(db, action_type, target, parameters, confidence, now):
    if not db:
        return None
    try:
        from db.models import PendingAction
        pending = PendingAction(
            action_type=action_type,
            target=target,
            parameters=parameters,
            confidence=confidence,
            status="pending",
            proposed_at=now,
        )
        db.add(pending)
        db.commit()
        return pending.id
    except Exception as e:
        logger.warning(f"Failed to queue pending action: {e}")
        return None


def _update_audit(db, audit_id, status):
    if not db or not audit_id:
        return
    try:
        from db.models import AuditLog
        entry = db.query(AuditLog).filter(AuditLog.id == audit_id).first()
        if entry:
            entry.status = status
            if status == "executed":
                entry.executed_at = datetime.now(timezone.utc)
            db.commit()
    except Exception:
        pass


def _is_rhdp_action(action_type: str, parameters: Dict[str, Any]) -> bool:
    """Check if this action should be routed through RHDP APIs."""
    method = parameters.get("execution_method", "kubernetes")
    return method.startswith("rhdp_")


def _preflight_check(target: str, parameters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Check RHDP state before executing — skip if mid-provision."""
    try:
        from engine.rhdp_client import get_anarchy_state
        from api.routers._shared import EXECUTOR_KUBECONFIG
        state = get_anarchy_state(target, kubeconfig=EXECUTOR_KUBECONFIG)
        if state in ("provisioning", "starting"):
            logger.info(f"PRE-FLIGHT: {target} is {state} — skipping remediation")
            return {"executed": False, "reason": "provisioning_in_progress", "anarchy_state": state}
    except Exception:
        pass
    return None


def _do_execute(action_type, target, parameters):
    """Execute the action based on configured execution target and method."""
    from api.routers._shared import EXECUTION_TARGET, EXECUTOR_KUBECONFIG, TEST_NAMESPACE

    preflight = _preflight_check(target, parameters)
    if preflight:
        return preflight

    if _is_rhdp_action(action_type, parameters):
        from engine.rhdp_client import execute_rhdp_action
        logger.info(f"RHDP EXECUTE: {action_type} on {target}")
        return execute_rhdp_action(action_type, target, parameters, kubeconfig=EXECUTOR_KUBECONFIG)

    if EXECUTION_TARGET == "test" and EXECUTOR_KUBECONFIG:
        from engine.oc_executor import execute_oc_action
        from engine.rollback import capture_state, restore_state
        namespace = TEST_NAMESPACE

        snapshot = capture_state(namespace, EXECUTOR_KUBECONFIG)
        try:
            result = execute_oc_action(action_type, namespace, EXECUTOR_KUBECONFIG, parameters)
            if not result.get("success"):
                restore_state(snapshot, namespace, EXECUTOR_KUBECONFIG)
                result["rolled_back"] = True
            return result
        except Exception as e:
            restore_state(snapshot, namespace, EXECUTOR_KUBECONFIG)
            return {"success": False, "error": str(e), "rolled_back": True}

    elif EXECUTION_TARGET == "production":
        logger.warning("Production execution not yet enabled — requires Phase D approval")
        return {"success": False, "error": "Production execution requires Phase D write SA + approval gate"}

    else:
        from engine.mock_cluster import MockCluster
        from engine.oc_executor import map_action_to_commands
        mc = MockCluster()
        namespace = target or "mock-namespace"
        commands = map_action_to_commands(action_type, namespace, parameters)
        results = []
        for cmd in commands:
            r = mc.execute(cmd)
            results.append({"command": cmd, **r})
        all_ok = all(r.get("success", False) for r in results)
        logger.info(f"MOCK EXECUTE: {action_type} on {target} — {len(commands)} commands, success={all_ok}")
        return {
            "success": all_ok,
            "action_type": action_type,
            "target": target,
            "mode": "mock",
            "commands": results,
            "state_after": mc.get_state(namespace),
            "audit_trail": mc.history,
        }
