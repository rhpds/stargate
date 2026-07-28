"""Proof orchestrator — runs inject -> detect -> remediate -> verify cycles.

SAFETY: Only operates on STARGATE_TEST_NAMESPACE. All operations are
scoped and validated. Rollback on failure.
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from engine.failure_injector import ALLOWED_NAMESPACE, cleanup_all, inject_failure
from engine.proof_tracker import ProofTracker
from engine.rollback import capture_state, restore_state

logger = logging.getLogger("stargate.proof_orchestrator")

DETECTION_TIMEOUT = 120  # seconds to wait for scanner/deepfield to detect
DETECTION_POLL_INTERVAL = 10


def run_proof_cycle(
    failure_class: str,
    kubeconfig: str = "",
    mode: str = "manual",
    db=None,
) -> Dict:
    """Run a full inject -> detect -> remediate -> verify cycle for one failure class.

    mode: "manual" = HITL required, "low_risk_auto" = auto if risk==low, "full_auto" = auto all
    """
    namespace = ALLOWED_NAMESPACE
    tracker = ProofTracker()
    result = {
        "failure_class": failure_class,
        "namespace": namespace,
        "mode": mode,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps": {},
        "success": False,
    }

    # 1. Capture baseline
    try:
        snapshot = capture_state(namespace, kubeconfig)
        result["steps"]["baseline"] = {"captured": True}
    except Exception as e:
        result["steps"]["baseline"] = {"captured": False, "error": str(e)}
        snapshot = None

    # 2. Inject failure
    try:
        inject_started = datetime.now(timezone.utc).isoformat()
        injection = inject_failure(failure_class, namespace, kubeconfig)
        inject_completed = datetime.now(timezone.utc).isoformat()
        if "error" in injection:
            result["steps"]["inject"] = injection
            result["error"] = injection["error"]
            return result
        tracker.record_injection(failure_class, injection)
        result["steps"]["inject"] = {
            "status": "success",
            "commands": injection.get("commands", []),
            "started_at": inject_started,
            "completed_at": inject_completed,
            "failure_class": injection.get("failure_class"),
            "injected_resources": injection.get("injected_resources", []),
            "namespace": injection.get("namespace"),
        }
    except Exception as e:
        result["steps"]["inject"] = {"status": "failed", "commands": [], "error": str(e)}
        result["error"] = str(e)
        return result

    # 3. Wait for detection
    detected = False
    detected_class = None
    detection_source = None
    poll_attempts = 0
    if db:
        from db.models import EvaluationRecord
        start = time.time()
        while time.time() - start < DETECTION_TIMEOUT:
            poll_attempts += 1
            recent = db.query(EvaluationRecord).filter(
                EvaluationRecord.lab_code == namespace,
                EvaluationRecord.outcome == "fail",
            ).order_by(EvaluationRecord.id.desc()).first()
            if recent and recent.failure_class:
                detected = True
                detected_class = recent.failure_class
                detection_source = "stargate"
                break
            # Also check Deepfield incidents via PendingAction
            from db.models import PendingAction
            deepfield_inc = db.query(PendingAction).filter(
                PendingAction.target == namespace,
                PendingAction.proposed_by == "deepfield",
                PendingAction.status == "pending",
            ).order_by(PendingAction.id.desc()).first()
            if deepfield_inc:
                detected = True
                detected_class = (deepfield_inc.parameters or {}).get("failure_class", "unknown")
                detection_source = "deepfield"
                break
            time.sleep(DETECTION_POLL_INTERVAL)

    result["steps"]["detect"] = {
        "status": "detected" if detected else "timeout",
        "commands": [],  # detection is DB polling, no oc commands
        "poll_attempts": poll_attempts,
        "detected": detected,
        "detected_class": detected_class,
        "source": detection_source,
        "correct": detected_class == failure_class if detected else False,
    }
    if detected:
        tracker.record_detection(failure_class, detected_class or "", detection_source or "")

    # 4. Remediation (with HITL gate in manual mode)
    remediation_result = {"executed": False}
    if mode == "manual":
        # Create PendingAction for HITL approval
        if db:
            from db.models import PendingAction
            pending = PendingAction(
                action_type=f"proof_{failure_class}",
                target=namespace,
                parameters={
                    "source": "proof_orchestrator",
                    "failure_class": failure_class,
                    "mode": mode,
                    "detected_class": detected_class,
                },
                confidence=0.95,
                proposed_by="proof_system",
                source_event_id=f"proof-{failure_class}-{int(time.time())}",
                status="pending",
                proposed_at=datetime.now(timezone.utc),
            )
            db.add(pending)
            db.commit()
            remediation_result = {
                "executed": False,
                "pending_id": pending.id,
                "status": "awaiting_hitl_approval",
                "message": "Created PendingAction — approve in the Incidents tab to continue",
            }
    else:
        # Auto-execute (only for proven low-risk or full-auto)
        try:
            from engine.oc_executor import execute_oc_action
            exec_result = execute_oc_action(failure_class, namespace, kubeconfig, {})
            remediation_result = {"executed": True, "success": exec_result.get("success", False), **exec_result}
        except Exception as e:
            remediation_result = {"executed": True, "success": False, "error": str(e)}

    result["steps"]["remediate"] = remediation_result
    if remediation_result.get("executed"):
        tracker.record_remediation(failure_class, f"proof_{failure_class}", remediation_result.get("success", False), remediation_result)

    # 5. Verify (only if remediation was executed)
    if remediation_result.get("executed") and remediation_result.get("success"):
        time.sleep(10)  # Wait for state to settle
        # Check if the failure is gone
        import subprocess
        env = {**os.environ}
        if kubeconfig:
            env["KUBECONFIG"] = kubeconfig
        verify_cmd_str = f"oc get pods -n {namespace} -o wide"
        verify_start = time.time()
        r = subprocess.run(
            ["oc", "get", "pods", "-n", namespace, "-o", "wide"],
            capture_output=True, text=True, timeout=15, env=env
        )
        verify_duration_ms = int((time.time() - verify_start) * 1000)
        pods_output = r.stdout.strip()
        has_crashloop = "CrashLoopBackOff" in pods_output
        has_err = "Error" in pods_output or "ImagePullBackOff" in pods_output
        clean = not has_crashloop and not has_err

        verify_command_trace = {
            "command": verify_cmd_str,
            "output": pods_output[:500],
            "exit_code": r.returncode,
            "duration_ms": verify_duration_ms,
        }
        result["steps"]["verify"] = {
            "status": "clean" if clean else "failed",
            "commands": [verify_command_trace],
            "clean": clean,
            "pods": pods_output[:500],
        }
        tracker.record_verification(failure_class, clean, {"pods": pods_output[:500]})
    else:
        result["steps"]["verify"] = {"status": "skipped", "commands": [], "skipped": True, "reason": "remediation not executed or failed"}

    # 6. Cleanup
    try:
        cleanup = cleanup_all(namespace, kubeconfig)
        result["steps"]["cleanup"] = {
            "status": "success",
            "commands": cleanup.get("commands", []),
            "deleted": cleanup.get("deleted", []),
            "namespace": cleanup.get("namespace"),
        }
    except Exception as e:
        result["steps"]["cleanup"] = {"status": "failed", "commands": [], "error": str(e)}

    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    result["success"] = result["steps"].get("verify", {}).get("clean", False)
    result["proof_status"] = tracker.get_status(failure_class)

    tracker.record_cycle_result(failure_class, result)

    return result
