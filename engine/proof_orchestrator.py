"""Proof orchestrator — two-phase inject/detect then remediate/verify.

Phase 1 (run_proof_cycle): inject → detect → create HITL pending → stop
Phase 2 (continue_proof_cycle): remediate → verify → cleanup → record

SAFETY: Only operates on STARGATE_TEST_NAMESPACE.
"""

import logging
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from typing import Dict

from engine.failure_injector import ALLOWED_NAMESPACE, cleanup_all, inject_failure
from engine.proof_tracker import ProofTracker
from engine.rollback import capture_state

logger = logging.getLogger("stargate.proof_orchestrator")

DETECTION_TIMEOUT = 120
DETECTION_POLL_INTERVAL = 10


def _load_failure_patterns() -> Dict[str, str]:
    import yaml
    patterns = {}
    fc_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "failure-classes", "k8s-events.yaml")
    if os.path.exists(fc_file):
        with open(fc_file) as f:
            fc_data = yaml.safe_load(f) or {}
        for cls_name, cls_info in fc_data.get("classes", {}).items():
            patterns[cls_name] = cls_info.get("pattern", "")
    return patterns


def _run_detect(namespace: str, kubeconfig: str, failure_class: str, failure_patterns: Dict[str, str], db=None) -> Dict:
    """Poll cluster events and DB for the injected failure."""
    detected = False
    detected_class = None
    detection_source = None
    detect_commands = []
    poll_attempts = 0

    start_time = time.time()
    while time.time() - start_time < DETECTION_TIMEOUT:
        poll_attempts += 1
        env = {**os.environ}
        if kubeconfig:
            env["KUBECONFIG"] = kubeconfig
        t0 = time.time()
        r = subprocess.run(
            ["oc", "get", "events", "-n", namespace, "--sort-by=.lastTimestamp"],
            capture_output=True, text=True, timeout=10, env=env,
        )
        detect_commands.append({
            "command": f"oc get events -n {namespace} --sort-by=.lastTimestamp",
            "output": r.stdout.strip()[:1500] if r.stdout else r.stderr.strip()[:500],
            "exit_code": r.returncode,
            "duration_ms": int((time.time() - t0) * 1000),
        })
        if r.returncode == 0 and r.stdout:
            pattern = failure_patterns.get(failure_class, "")
            if pattern and re.search(pattern, r.stdout, re.IGNORECASE):
                detected = True
                detected_class = failure_class
                detection_source = "cluster_events"
                break
        if db:
            from db.models import EvaluationRecord
            recent = db.query(EvaluationRecord).filter(
                EvaluationRecord.lab_code == namespace,
                EvaluationRecord.outcome == "fail",
            ).order_by(EvaluationRecord.id.desc()).first()
            if recent and recent.failure_class:
                detected = True
                detected_class = recent.failure_class
                detection_source = "stargate_db"
                break
        time.sleep(DETECTION_POLL_INTERVAL)

    return {
        "status": "detected" if detected else "timeout",
        "commands": detect_commands[-3:],
        "poll_attempts": poll_attempts,
        "detected": detected,
        "detected_class": detected_class,
        "source": detection_source,
        "correct": detected_class == failure_class if detected else False,
    }


def run_proof_cycle(
    failure_class: str,
    kubeconfig: str = "",
    mode: str = "manual",
    db=None,
) -> Dict:
    """Phase 1: inject → detect → create HITL pending action → stop.

    Does NOT remediate or cleanup. The injected failure stays live
    until the user approves via continue_proof_cycle.
    """
    namespace = ALLOWED_NAMESPACE
    tracker = ProofTracker()
    result = {
        "failure_class": failure_class,
        "namespace": namespace,
        "mode": mode,
        "phase": "inject_detect",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps": {},
        "success": False,
        "awaiting_approval": False,
    }

    # 1. Capture baseline
    try:
        capture_state(namespace, kubeconfig)
        result["steps"]["baseline"] = {"captured": True}
    except Exception as e:
        result["steps"]["baseline"] = {"captured": False, "error": str(e)}

    # 2. Inject failure
    try:
        inject_started = datetime.now(timezone.utc).isoformat()
        injection = inject_failure(failure_class, namespace, kubeconfig)
        inject_completed = datetime.now(timezone.utc).isoformat()
        if "error" in injection:
            result["steps"]["inject"] = {"status": "failed", "commands": [], **injection}
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

    # 3. Detect
    failure_patterns = _load_failure_patterns()
    detect_result = _run_detect(namespace, kubeconfig, failure_class, failure_patterns, db)
    result["steps"]["detect"] = detect_result
    if detect_result["detected"]:
        tracker.record_detection(failure_class, detect_result["detected_class"] or "", detect_result["source"] or "")

    # 4. Create HITL pending action (in manual mode)
    if mode == "manual" and db:
        from db.models import PendingAction
        pending = PendingAction(
            action_type=f"proof_{failure_class}",
            target=namespace,
            parameters={
                "source": "proof_orchestrator",
                "failure_class": failure_class,
                "mode": mode,
                "detected_class": detect_result.get("detected_class"),
                "phase": "awaiting_approval",
            },
            confidence=0.95,
            proposed_by="proof_system",
            source_event_id=f"proof-{failure_class}-{int(time.time())}",
            status="pending",
            proposed_at=datetime.now(timezone.utc),
        )
        db.add(pending)
        db.commit()
        result["steps"]["remediate"] = {
            "status": "awaiting_hitl_approval",
            "pending_id": pending.id,
            "message": "Approve to proceed with remediation, verify, and cleanup.",
        }
        result["awaiting_approval"] = True
        result["pending_id"] = pending.id
    elif mode != "manual":
        # Auto mode — run phase 2 immediately
        phase2 = continue_proof_cycle(failure_class, kubeconfig, db)
        result["steps"]["remediate"] = phase2["steps"].get("remediate", {})
        result["steps"]["verify"] = phase2["steps"].get("verify", {})
        result["steps"]["cleanup"] = phase2["steps"].get("cleanup", {})
        result["success"] = phase2.get("success", False)
        result["proof_status"] = phase2.get("proof_status")

    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    tracker.record_cycle_result(failure_class, result)
    return result


def continue_proof_cycle(
    failure_class: str,
    kubeconfig: str = "",
    db=None,
) -> Dict:
    """Phase 2: remediate → verify → cleanup. Called after HITL approval."""
    namespace = ALLOWED_NAMESPACE
    tracker = ProofTracker()
    result = {
        "failure_class": failure_class,
        "namespace": namespace,
        "phase": "remediate_verify",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps": {},
        "success": False,
    }

    # 1. Remediate
    try:
        from engine.oc_executor import execute_oc_action
        exec_result = execute_oc_action(failure_class, namespace, kubeconfig, {})
        result["steps"]["remediate"] = {
            "status": "success" if exec_result.get("success") else "failed",
            "executed": True,
            "commands": exec_result.get("commands", []),
            **{k: v for k, v in exec_result.items() if k != "commands"},
        }
        tracker.record_remediation(failure_class, f"proof_{failure_class}", exec_result.get("success", False), exec_result)
    except Exception as e:
        result["steps"]["remediate"] = {"status": "failed", "executed": True, "error": str(e), "commands": []}
        tracker.record_remediation(failure_class, f"proof_{failure_class}", False, {"error": str(e)})

    # 2. Verify
    remediated_ok = result["steps"]["remediate"].get("status") == "success"
    if remediated_ok:
        time.sleep(10)
        env = {**os.environ}
        if kubeconfig:
            env["KUBECONFIG"] = kubeconfig
        verify_start = time.time()
        r = subprocess.run(
            ["oc", "get", "pods", "-n", namespace, "-o", "wide"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        pods_output = r.stdout.strip()
        has_crashloop = "CrashLoopBackOff" in pods_output
        has_err = "Error" in pods_output or "ImagePullBackOff" in pods_output
        clean = not has_crashloop and not has_err

        result["steps"]["verify"] = {
            "status": "clean" if clean else "failed",
            "commands": [{
                "command": f"oc get pods -n {namespace} -o wide",
                "output": pods_output[:500],
                "exit_code": r.returncode,
                "duration_ms": int((time.time() - verify_start) * 1000),
            }],
            "clean": clean,
        }
        tracker.record_verification(failure_class, clean, {"pods": pods_output[:500]})
    else:
        result["steps"]["verify"] = {"status": "skipped", "commands": [], "reason": "remediation failed"}

    # 3. Cleanup
    try:
        cleanup = cleanup_all(namespace, kubeconfig)
        result["steps"]["cleanup"] = {
            "status": "success",
            "commands": cleanup.get("commands", []),
            "deleted": cleanup.get("deleted", []),
        }
    except Exception as e:
        result["steps"]["cleanup"] = {"status": "failed", "commands": [], "error": str(e)}

    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    result["success"] = result["steps"].get("verify", {}).get("clean", False)
    result["proof_status"] = tracker.get_status(failure_class)

    tracker.record_cycle_result(failure_class, result)
    return result
