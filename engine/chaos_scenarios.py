"""Chaos test scenarios — deploy deliberately broken workloads for remediation proof.

Each scenario deploys a broken workload in stargate-test, collects evidence,
runs rubric evaluation, calls LLM for classification, applies fix, re-evaluates.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from engine.rollback import _run_oc

logger = logging.getLogger("stargate.chaos")

HARDCODED_NAMESPACE = "stargate-test"



@dataclass
class ChaosScenario:
    name: str
    deployment_name: str
    deploy_commands: List[List[str]]
    rubric_stage: str
    expected_failure_class: str
    fix_commands: List[List[str]]
    cleanup_commands: List[List[str]]
    wait_seconds: int = 15


_PATCH_CRASHLOOP = '[{"op":"replace","path":"/spec/template/spec/containers/0/command","value":["/bin/sh","-c","exit 1"]}]'
_PATCH_FIX = '[{"op":"replace","path":"/spec/template/spec/containers/0/command","value":["/bin/sh","-c","sleep 3600"]}]'

_PATCH_STRATEGY_RECREATE = '[{"op":"replace","path":"/spec/strategy","value":{"type":"Recreate"}}]'

_PATCH_READINESS_BROKEN = json.dumps([{
    "op": "add", "path": "/spec/template/spec/containers/0/readinessProbe",
    "value": {"httpGet": {"path": "/healthz", "port": 9999}, "periodSeconds": 2, "failureThreshold": 2},
}])
_PATCH_READINESS_FIX = '[{"op":"remove","path":"/spec/template/spec/containers/0/readinessProbe"}]'

_PATCH_INIT_BROKEN = json.dumps([{
    "op": "add", "path": "/spec/template/spec/initContainers",
    "value": [{"name": "broken-init", "image": "registry.access.redhat.com/ubi9/ubi-minimal:latest", "command": ["/bin/sh", "-c", "exit 1"]}],
}])
_PATCH_INIT_FIX = '[{"op":"remove","path":"/spec/template/spec/initContainers"}]'

_PATCH_SECRET_BROKEN = json.dumps([{
    "op": "add", "path": "/spec/template/spec/volumes",
    "value": [{"name": "secret-vol", "secret": {"secretName": "does-not-exist-chaos"}}],
}, {
    "op": "add", "path": "/spec/template/spec/containers/0/volumeMounts",
    "value": [{"name": "secret-vol", "mountPath": "/secret"}],
}])

_PATCH_OOM = json.dumps([
    {"op": "replace", "path": "/spec/template/spec/containers/0/command",
     "value": ["/bin/sh", "-c", "dd if=/dev/zero of=/dev/shm/fill bs=1M count=100"]},
    {"op": "add", "path": "/spec/template/spec/containers/0/resources", "value": {"limits": {"memory": "4Mi"}}},
])
_PATCH_OOM_FIX = json.dumps([
    {"op": "replace", "path": "/spec/template/spec/containers/0/command", "value": ["/bin/sh", "-c", "sleep 3600"]},
    {"op": "replace", "path": "/spec/template/spec/containers/0/resources", "value": {"limits": {"memory": "128Mi"}}},
])

CHAOS_SCENARIOS = [
    # --- Original 3 scenarios ---
    ChaosScenario(
        name="crashlooping_pod",
        deployment_name="crash-test",
        deploy_commands=[
            ["create", "deployment", "crash-test", "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest", "-n", "{ns}"],
            ["patch", "deployment", "crash-test", "-n", "{ns}", "--type=json", "-p", _PATCH_CRASHLOOP],
        ],
        rubric_stage="deployment-ready",
        expected_failure_class="pods_crashlooping",
        fix_commands=[
            ["patch", "deployment", "crash-test", "-n", "{ns}", "--type=json", "-p", _PATCH_FIX],
        ],
        cleanup_commands=[["delete", "deployment", "crash-test", "-n", "{ns}", "--ignore-not-found"]],
        wait_seconds=20,
    ),
    ChaosScenario(
        name="zero_replicas",
        deployment_name="zero-test",
        deploy_commands=[
            ["create", "deployment", "zero-test", "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest", "-n", "{ns}", "--", "sleep", "3600"],
            ["scale", "deployment/zero-test", "--replicas=0", "-n", "{ns}"],
        ],
        rubric_stage="deployment-ready",
        expected_failure_class="pods_not_ready",
        fix_commands=[["scale", "deployment/zero-test", "--replicas=2", "-n", "{ns}"]],
        cleanup_commands=[["delete", "deployment", "zero-test", "-n", "{ns}", "--ignore-not-found"]],
        wait_seconds=10,
    ),
    ChaosScenario(
        name="bad_image",
        deployment_name="bad-image-test",
        deploy_commands=[
            ["create", "deployment", "bad-image-test", "--image=does-not-exist-anywhere:v999", "-n", "{ns}"],
        ],
        rubric_stage="deployment-ready",
        expected_failure_class="pods_not_ready",
        fix_commands=[
            ["set", "image", "deployment/bad-image-test", "*=registry.access.redhat.com/ubi9/ubi-minimal:latest", "-n", "{ns}"],
            ["patch", "deployment", "bad-image-test", "-n", "{ns}", "--type=json", "-p", _PATCH_FIX],
        ],
        cleanup_commands=[["delete", "deployment", "bad-image-test", "-n", "{ns}", "--ignore-not-found"]],
        wait_seconds=15,
    ),
    # --- New: missing secret (volume mount to nonexistent secret) ---
    ChaosScenario(
        name="missing_secret",
        deployment_name="secret-test",
        deploy_commands=[
            ["create", "deployment", "secret-test", "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest", "-n", "{ns}", "--", "sleep", "3600"],
            ["patch", "deployment", "secret-test", "-n", "{ns}", "--type=json", "-p", _PATCH_STRATEGY_RECREATE],
            ["patch", "deployment", "secret-test", "-n", "{ns}", "--type=json", "-p", _PATCH_SECRET_BROKEN],
        ],
        rubric_stage="deployment-ready",
        expected_failure_class="pods_not_ready",
        fix_commands=[
            ["create", "secret", "generic", "does-not-exist-chaos", "-n", "{ns}", "--from-literal=placeholder=true"],
            ["rollout", "restart", "deployment/secret-test", "-n", "{ns}"],
        ],
        cleanup_commands=[
            ["delete", "deployment", "secret-test", "-n", "{ns}", "--ignore-not-found"],
            ["delete", "secret", "does-not-exist-chaos", "-n", "{ns}", "--ignore-not-found"],
        ],
        wait_seconds=25,
    ),
    # --- New: readiness probe failing (HTTP probe on wrong port) ---
    ChaosScenario(
        name="readiness_probe_failing",
        deployment_name="readiness-test",
        deploy_commands=[
            ["create", "deployment", "readiness-test", "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest", "-n", "{ns}", "--", "sleep", "3600"],
            ["patch", "deployment", "readiness-test", "-n", "{ns}", "--type=json", "-p", _PATCH_STRATEGY_RECREATE],
            ["patch", "deployment", "readiness-test", "-n", "{ns}", "--type=json", "-p", _PATCH_READINESS_BROKEN],
        ],
        rubric_stage="deployment-ready",
        expected_failure_class="pods_not_ready",
        fix_commands=[
            ["patch", "deployment", "readiness-test", "-n", "{ns}", "--type=json", "-p", _PATCH_READINESS_FIX],
        ],
        cleanup_commands=[["delete", "deployment", "readiness-test", "-n", "{ns}", "--ignore-not-found"]],
        wait_seconds=20,
    ),
    # --- New: init container failure (init exits non-zero) ---
    ChaosScenario(
        name="init_container_failing",
        deployment_name="init-test",
        deploy_commands=[
            ["create", "deployment", "init-test", "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest", "-n", "{ns}", "--", "sleep", "3600"],
            ["patch", "deployment", "init-test", "-n", "{ns}", "--type=json", "-p", _PATCH_STRATEGY_RECREATE],
            ["patch", "deployment", "init-test", "-n", "{ns}", "--type=json", "-p", _PATCH_INIT_BROKEN],
        ],
        rubric_stage="deployment-ready",
        expected_failure_class="pods_not_ready",
        fix_commands=[
            ["patch", "deployment", "init-test", "-n", "{ns}", "--type=json", "-p", _PATCH_INIT_FIX],
        ],
        cleanup_commands=[["delete", "deployment", "init-test", "-n", "{ns}", "--ignore-not-found"]],
        wait_seconds=20,
    ),
    # --- New: OOMKilled (tiny memory limit) ---
    ChaosScenario(
        name="oom_killed",
        deployment_name="oom-test",
        deploy_commands=[
            ["create", "deployment", "oom-test", "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest", "-n", "{ns}"],
            ["patch", "deployment", "oom-test", "-n", "{ns}", "--type=json", "-p", _PATCH_STRATEGY_RECREATE],
            ["patch", "deployment", "oom-test", "-n", "{ns}", "--type=json", "-p", _PATCH_OOM],
        ],
        rubric_stage="deployment-ready",
        expected_failure_class="pods_crashlooping",
        fix_commands=[
            ["patch", "deployment", "oom-test", "-n", "{ns}", "--type=json", "-p", _PATCH_OOM_FIX],
        ],
        cleanup_commands=[["delete", "deployment", "oom-test", "-n", "{ns}", "--ignore-not-found"]],
        wait_seconds=35,
    ),
]


def collect_real_evidence(namespace: str, kubeconfig: str, deployment_name: str = "") -> Dict[str, Any]:
    """Collect actual Kubernetes state as rubric evidence, filtered to a specific deployment."""
    evidence = {"namespace_exists": True}

    try:
        if deployment_name:
            dep_raw = _run_oc(["get", "deployment", deployment_name, "-n", namespace, "-o", "json"], kubeconfig)
            dep_data = json.loads(dep_raw) if dep_raw else {}
            items = [dep_data] if dep_data.get("kind") == "Deployment" else []
        else:
            dep_raw = _run_oc(["get", "deployments", "-n", namespace, "-o", "json"], kubeconfig)
            dep_data = json.loads(dep_raw) if dep_raw else {"items": []}
            items = dep_data.get("items", [])
        evidence["deployment_exists"] = len(items) > 0
        desired = sum(d.get("spec", {}).get("replicas", 0) for d in items)
        ready = sum(d.get("status", {}).get("readyReplicas", 0) for d in items)
        evidence["desired_replicas_ready"] = desired > 0 and ready >= desired
    except Exception as e:
        logger.warning(f"Failed to get deployments: {e}")
        evidence["deployment_exists"] = False
        evidence["desired_replicas_ready"] = False

    try:
        if deployment_name:
            pod_raw = _run_oc(["get", "pods", "-n", namespace, "-l", f"app={deployment_name}", "-o", "json"], kubeconfig)
        else:
            pod_raw = _run_oc(["get", "pods", "-n", namespace, "-o", "json"], kubeconfig)
        pod_data = json.loads(pod_raw) if pod_raw else {"items": []}
        crashlooping = False
        config_error = False
        init_error = False
        oom_killed = False
        for p in pod_data.get("items", []):
            for cs in p.get("status", {}).get("containerStatuses", []):
                waiting = cs.get("state", {}).get("waiting", {})
                reason = waiting.get("reason", "")
                if reason in ("CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull"):
                    crashlooping = True
                if reason in ("CreateContainerConfigError",):
                    config_error = True
                terminated = cs.get("state", {}).get("terminated", {})
                if terminated.get("reason") == "OOMKilled":
                    crashlooping = True
                    oom_killed = True
                last_terminated = cs.get("lastState", {}).get("terminated", {})
                if last_terminated.get("reason") == "OOMKilled":
                    oom_killed = True
                    crashlooping = True
            for ics in p.get("status", {}).get("initContainerStatuses", []):
                waiting = ics.get("state", {}).get("waiting", {})
                if waiting.get("reason") in ("CrashLoopBackOff", "Error"):
                    init_error = True
                terminated = ics.get("state", {}).get("terminated", {})
                if terminated.get("reason") in ("Error",) or terminated.get("exitCode", 0) != 0:
                    init_error = True
        evidence["no_crashloop_pods"] = not crashlooping
        evidence["no_config_error_pods"] = not config_error
        evidence["no_init_error_pods"] = not init_error
        evidence["no_oom_killed_pods"] = not oom_killed
    except Exception:
        evidence["no_crashloop_pods"] = True
        evidence["no_config_error_pods"] = True
        evidence["no_init_error_pods"] = True
        evidence["no_oom_killed_pods"] = True

    return evidence


def run_chaos_scenario(scenario: ChaosScenario, kubeconfig: str, db=None) -> Dict:
    """Run a single chaos scenario: deploy → evaluate → classify → fix → verify."""
    ns = HARDCODED_NAMESPACE
    result = {"scenario": scenario.name, "steps": {}, "passed": False}

    # Step 0: Pre-cleanup to ensure no leftover from previous runs
    for cmd_parts in scenario.cleanup_commands:
        parts = [p.replace("{ns}", ns) for p in cmd_parts]
        try:
            _run_oc(parts, kubeconfig)
        except Exception:
            pass
    time.sleep(2)

    # Step 1: Deploy broken workload
    deploy_ok = True
    for cmd_parts in scenario.deploy_commands:
        parts = [p.replace("{ns}", ns) for p in cmd_parts]
        try:
            _run_oc(parts, kubeconfig)
        except Exception as e:
            deploy_ok = False
            logger.warning(f"Deploy failed: {' '.join(parts)}: {e}")
    result["steps"]["deploy"] = {"success": deploy_ok}

    time.sleep(scenario.wait_seconds)

    # Step 2: Evaluate BEFORE (should be FAIL)
    evidence_before = collect_real_evidence(ns, kubeconfig, deployment_name=scenario.deployment_name)
    from engine.rubric_evaluator import evaluate_rubric
    from api.routers._shared import _load_rubric_for_stage
    rubric = _load_rubric_for_stage(scenario.rubric_stage)
    eval_before = evaluate_rubric(rubric, evidence_before) if rubric else None

    result["steps"]["evaluate_before"] = {
        "outcome": eval_before.outcome.value if eval_before else "unknown",
        "failure_class": eval_before.failure_class if eval_before else None,
        "evidence": evidence_before,
        "expected_outcome": "fail",
        "match": eval_before and eval_before.outcome.value == "fail",
    }

    # Step 3: LLM classify (if DB available)
    llm_class = None
    llm_confidence = None
    if db and eval_before and eval_before.outcome.value == "fail":
        try:
            from api.llm import call_llm, load_prompt, LLM_MODEL
            prompt = load_prompt("classify")
            evidence_str = f"""## Failure Details
- Stage: {scenario.rubric_stage}
- Message: {eval_before.message}
- Failure class: {eval_before.failure_class}
- Evidence: {json.dumps(evidence_before)}

## Known Failure Classes
- pods_not_ready, pods_crashlooping, deployment_missing"""

            llm_result = call_llm(
                endpoint="classify",
                messages=[
                    {"role": "system", "content": prompt.get("system", "Classify this failure. Respond with JSON only.")},
                    {"role": "user", "content": evidence_str},
                ],
                max_tokens=300, temperature=0.1, timeout=30, db=db,
                prompt_version=prompt.get("version"),
            )
            if llm_result["success"]:
                parsed = json.loads(llm_result["content"])
                llm_class = parsed.get("proposed_class", "unknown")
                llm_confidence = parsed.get("confidence", 0)
        except Exception as e:
            logger.warning(f"LLM classify failed: {e}")

    result["steps"]["llm_classify"] = {
        "proposed_class": llm_class,
        "expected_class": scenario.expected_failure_class,
        "match": llm_class == scenario.expected_failure_class if llm_class else None,
        "confidence": llm_confidence,
    }

    # Step 4: Execute fix
    fix_ok = True
    fix_cmds = []
    for cmd_parts in scenario.fix_commands:
        parts = [p.replace("{ns}", ns) for p in cmd_parts]
        cmd_str = " ".join(parts)
        try:
            output = _run_oc(parts, kubeconfig)
            fix_cmds.append({"command": cmd_str, "success": True, "output": output[:100]})
        except Exception as e:
            fix_ok = False
            fix_cmds.append({"command": cmd_str, "success": False, "error": str(e)[:100]})

    result["steps"]["execute_fix"] = {"success": fix_ok, "commands": fix_cmds}

    # Step 5: Wait for recovery
    time.sleep(scenario.wait_seconds)

    # Step 6: Evaluate AFTER (should be PASS)
    evidence_after = collect_real_evidence(ns, kubeconfig, deployment_name=scenario.deployment_name)
    eval_after = evaluate_rubric(rubric, evidence_after) if rubric else None

    result["steps"]["evaluate_after"] = {
        "outcome": eval_after.outcome.value if eval_after else "unknown",
        "evidence": evidence_after,
        "expected_outcome": "pass",
        "match": eval_after and eval_after.outcome.value in ("pass", "warn"),
        "recovery": (eval_before and eval_before.outcome.value == "fail" and
                     eval_after and eval_after.outcome.value in ("pass", "warn")),
    }

    # Step 7: Cleanup
    for cmd_parts in scenario.cleanup_commands:
        parts = [p.replace("{ns}", ns) for p in cmd_parts]
        try:
            _run_oc(parts, kubeconfig)
        except Exception:
            pass

    result["passed"] = (
        result["steps"]["deploy"].get("success", False) and
        result["steps"]["evaluate_before"].get("match", False) and
        result["steps"]["execute_fix"].get("success", False) and
        result["steps"]["evaluate_after"].get("recovery", False)
    )

    return result
