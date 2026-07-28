"""Proof orchestrator — two-phase inject/detect then remediate/verify.

Phase 1 (run_proof_cycle): inject → detect → create HITL pending → stop
Phase 2 (continue_proof_cycle): remediate → verify → cleanup

Results are merged — the UI always sees one complete 5-step cycle.

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

DETECTION_TIMEOUT = 60
DETECTION_POLL_INTERVAL = 5


def _oc(args, kubeconfig=""):
    """Run an oc command and return trace dict."""
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    cmd_str = "oc " + " ".join(args)
    t0 = time.time()
    r = subprocess.run(["oc"] + args, capture_output=True, text=True, timeout=30, env=env)
    return {
        "command": cmd_str,
        "output": (r.stdout.strip() if r.returncode == 0 else r.stderr.strip())[:2000],
        "exit_code": r.returncode,
        "duration_ms": int((time.time() - t0) * 1000),
    }


def _load_failure_patterns():
    import yaml
    patterns = {}
    fc_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "failure-classes", "k8s-events.yaml")
    if os.path.exists(fc_file):
        with open(fc_file) as f:
            fc_data = yaml.safe_load(f) or {}
        for cls_name, cls_info in fc_data.get("classes", {}).items():
            patterns[cls_name] = cls_info.get("pattern", "")
    return patterns


def run_proof_cycle(
    failure_class: str,
    kubeconfig: str = "",
    mode: str = "manual",
    db=None,
) -> Dict:
    """Phase 1: inject → detect → create HITL pending → stop.

    The injected failure stays live until approve triggers Phase 2.
    """
    namespace = ALLOWED_NAMESPACE
    tracker = ProofTracker()
    now = datetime.now(timezone.utc).isoformat()
    result = {
        "failure_class": failure_class,
        "namespace": namespace,
        "mode": mode,
        "started_at": now,
        "steps": {},
        "success": False,
        "awaiting_approval": False,
    }

    # 1. Baseline — snapshot current state
    baseline_cmd = _oc(["get", "pods", "-n", namespace, "-o", "wide"], kubeconfig)
    result["steps"]["inject"] = {"status": "pending", "commands": []}

    # 2. Inject failure
    try:
        injection = inject_failure(failure_class, namespace, kubeconfig)
        if "error" in injection:
            result["steps"]["inject"] = {"status": "failed", "commands": [], **injection}
            return result
        tracker.record_injection(failure_class, injection)

        # Also capture pod state right after injection
        after_inject = _oc(["get", "pods", "-n", namespace, "-o", "wide"], kubeconfig)

        result["steps"]["inject"] = {
            "status": "success",
            "commands": injection.get("commands", []) + [
                {"command": "--- before injection ---", "output": baseline_cmd["output"] or "(empty namespace)", "exit_code": 0, "duration_ms": 0},
                {"command": "--- after injection ---", "output": after_inject["output"] or "(no pods yet)", "exit_code": 0, "duration_ms": 0},
            ],
            "failure_class": injection.get("failure_class"),
            "injected_resources": injection.get("injected_resources", []),
        }
        result["steps"]["detect"] = {"status": "running", "commands": [], "message": "Polling cluster events..."}
        result["steps"]["remediate"] = {"status": "waiting", "commands": [], "message": "Waiting for detection."}
        result["steps"]["verify"] = {"status": "waiting", "commands": [], "message": "Waiting for remediation."}
        result["steps"]["cleanup"] = {"status": "waiting", "commands": [], "message": "Waiting for verification."}
        tracker.record_cycle_result(failure_class, result)
    except Exception as e:
        result["steps"]["inject"] = {"status": "failed", "commands": [], "error": str(e)}
        return result

    # 3. Detect — poll cluster events for the failure pattern
    detect_commands = []
    detected = False
    detected_class = None
    detection_source = None
    poll_attempts = 0
    failure_patterns = _load_failure_patterns()

    start_time = time.time()
    while time.time() - start_time < DETECTION_TIMEOUT:
        poll_attempts += 1
        trace = _oc(["get", "events", "-n", namespace, "--sort-by=.lastTimestamp"], kubeconfig)
        detect_commands.append(trace)
        if trace["exit_code"] == 0 and trace["output"]:
            pattern = failure_patterns.get(failure_class, "")
            if pattern and re.search(pattern, trace["output"], re.IGNORECASE):
                detected = True
                detected_class = failure_class
                detection_source = "cluster_events"
                break
        time.sleep(DETECTION_POLL_INTERVAL)

    result["steps"]["detect"] = {
        "status": "detected" if detected else "timeout",
        "commands": detect_commands[-2:],
        "poll_attempts": poll_attempts,
        "detected_class": detected_class,
        "source": detection_source,
        "correct": detected_class == failure_class if detected else False,
    }
    tracker.record_cycle_result(failure_class, result)
    if detected:
        tracker.record_detection(failure_class, detected_class, detection_source)

    # 4. HITL gate — create pending action and stop
    if mode == "manual" and db:
        from db.models import PendingAction
        pending = PendingAction(
            action_type=f"proof_{failure_class}",
            target=namespace,
            parameters={
                "source": "proof_orchestrator",
                "failure_class": failure_class,
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
        result["steps"]["remediate"] = {
            "status": "awaiting_hitl_approval",
            "pending_id": pending.id,
            "message": "Approve to run remediation → verify → cleanup.",
        }
        result["steps"]["verify"] = {"status": "waiting", "commands": [], "message": "Runs after remediation is approved."}
        result["steps"]["cleanup"] = {"status": "waiting", "commands": [], "message": "Runs after verification."}
        result["awaiting_approval"] = True
        result["pending_id"] = pending.id
    elif mode != "manual":
        phase2 = continue_proof_cycle(failure_class, kubeconfig, db)
        result["steps"]["remediate"] = phase2["steps"].get("remediate", {})
        result["steps"]["verify"] = phase2["steps"].get("verify", {})
        result["steps"]["cleanup"] = phase2["steps"].get("cleanup", {})
        result["success"] = phase2.get("success", False)

    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    tracker.record_cycle_result(failure_class, result)
    return result


def continue_proof_cycle(
    failure_class: str,
    kubeconfig: str = "",
    db=None,
) -> Dict:
    """Phase 2: remediate → verify → cleanup. Merges with Phase 1 result."""
    namespace = ALLOWED_NAMESPACE
    tracker = ProofTracker()

    # Load Phase 1 result so we can merge
    fc_data = tracker._data.get("failure_classes", {}).get(failure_class, {})
    phase1_results = fc_data.get("cycle_results", [])
    phase1 = phase1_results[-1] if phase1_results else {}

    result = dict(phase1) if phase1 else {
        "failure_class": failure_class,
        "namespace": namespace,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps": {},
    }
    result["mode"] = phase1.get("mode", "manual")

    # Re-inject if the failure is no longer present (pod restart or timeout killed it)
    before_check = _oc(["get", "pods", "-n", namespace, "-o", "wide"], kubeconfig)
    fc_data = tracker._data.get("failure_classes", {}).get(failure_class, {})
    expected_resources = []
    for cr in fc_data.get("cycle_results", []):
        res = cr.get("steps", {}).get("inject", {}).get("injected_resources", [])
        if res:
            expected_resources = res
            break

    needs_reinject = not before_check["output"] or all(
        r.split("/")[-1] not in before_check["output"] for r in expected_resources
    )
    reinject_commands = []
    if needs_reinject:
        reinject = inject_failure(failure_class, namespace, kubeconfig)
        reinject_commands = reinject.get("commands", [])
        time.sleep(5)

    before_remediate = _oc(["get", "pods", "-n", namespace, "-o", "wide"], kubeconfig)

    # 1. Remediate — run the catalog action
    remediate_commands = []
    if reinject_commands:
        remediate_commands.append({"command": "--- re-injected failure (was cleaned up) ---", "output": "", "exit_code": 0, "duration_ms": 0})
        remediate_commands.extend(reinject_commands)
    remediate_commands.append({"command": "--- pods before remediation ---", "output": before_remediate["output"] or "(no pods)", "exit_code": 0, "duration_ms": 0})
    try:
        from engine.oc_executor import execute_oc_action
        exec_result = execute_oc_action(failure_class, namespace, kubeconfig, {})
        exec_commands = exec_result.get("commands", [])
        if isinstance(exec_commands, list):
            remediate_commands.extend(exec_commands)
        elif exec_result.get("command"):
            remediate_commands.append({"command": str(exec_result["command"]), "output": str(exec_result.get("result", "")), "exit_code": 0 if exec_result.get("success") else 1, "duration_ms": 0})
        result["steps"]["remediate"] = {
            "status": "success" if exec_result.get("success") else "failed",
            "executed": True,
            "commands": remediate_commands,
            "action": exec_result.get("action_type", failure_class),
        }
        tracker.record_remediation(failure_class, f"proof_{failure_class}", exec_result.get("success", False), exec_result)
    except Exception as e:
        remediate_commands.append({"command": "execute_oc_action", "output": str(e), "exit_code": 1, "duration_ms": 0})
        result["steps"]["remediate"] = {"status": "failed", "executed": True, "commands": remediate_commands, "error": str(e)}
        tracker.record_remediation(failure_class, f"proof_{failure_class}", False, {"error": str(e)})

    # 2. Verify — check if the failure is gone (BEFORE cleanup)
    remediated_ok = result["steps"]["remediate"].get("status") == "success"
    if remediated_ok:
        time.sleep(10)
        verify_pods = _oc(["get", "pods", "-n", namespace, "-o", "wide"], kubeconfig)
        verify_events = _oc(["get", "events", "-n", namespace, "--sort-by=.lastTimestamp", "--field-selector=type=Warning"], kubeconfig)

        pods_output = verify_pods["output"]
        has_crashloop = "CrashLoopBackOff" in pods_output
        has_err = "Error" in pods_output or "ImagePullBackOff" in pods_output
        has_pending = "Pending" in pods_output
        clean = not has_crashloop and not has_err and not has_pending

        result["steps"]["verify"] = {
            "status": "clean" if clean else "failed",
            "commands": [
                {"command": "--- pods after remediation ---", "output": pods_output or "(no pods)", "exit_code": 0, "duration_ms": 0},
                verify_events,
            ],
            "clean": clean,
        }
        tracker.record_verification(failure_class, clean, {"pods": pods_output[:500]})
    else:
        result["steps"]["verify"] = {"status": "skipped", "commands": [], "reason": "remediation failed"}

    # 3. Cleanup — remove all proof resources
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

    # Replace the Phase 1 result with the merged result
    tracker.record_cycle_result(failure_class, result)
    return result
