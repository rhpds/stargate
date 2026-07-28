"""Failure injector — creates broken K8s resources in the test namespace.

SAFETY: Only operates on the designated test namespace. Refuses all
operations on any other namespace. Every function validates this.

Each injector documents:
- What it creates and why
- What the catalog remediation does
- Whether the remediation fixes the root cause
- The honest proof outcome (remediation_proven vs investigation_proven)

Two categories:
  REMEDIATION: catalog action actually fixes the failure → prove it works
  INVESTIGATION: no catalog fix exists → prove diagnostic commands work
"""

import json
import logging
import os
import subprocess
import time
from typing import Dict, List

logger = logging.getLogger("stargate.failure_injector")

ALLOWED_NAMESPACE = os.environ.get("STARGATE_TEST_NAMESPACE", "stargate-test")


def _validate_namespace(namespace: str):
    if namespace != ALLOWED_NAMESPACE:
        raise ValueError(f"Failure injection BLOCKED: namespace '{namespace}' is not the test namespace '{ALLOWED_NAMESPACE}'")


def _run_oc(args: List[str], kubeconfig: str = "") -> Dict:
    cmd_str = "oc " + " ".join(args)
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    start = time.time()
    r = subprocess.run(["oc"] + args, capture_output=True, text=True, timeout=30, env=env)
    duration_ms = int((time.time() - start) * 1000)
    output = r.stdout.strip() if r.returncode == 0 else r.stderr.strip()
    if r.returncode != 0 and "not found" not in output and "No resources" not in output:
        logger.warning("oc %s failed: %s", " ".join(args[:3]), output[:200])
    return {"command": cmd_str, "output": output, "exit_code": r.returncode, "duration_ms": duration_ms}


def _apply_manifest(manifest: dict, namespace: str, kubeconfig: str = "") -> Dict:
    cmd_str = f"oc apply -f - -n {namespace}"
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    start = time.time()
    r = subprocess.run(
        ["oc", "apply", "-f", "-", "-n", namespace],
        input=json.dumps(manifest), capture_output=True, text=True, timeout=30, env=env,
    )
    return {"command": cmd_str, "output": r.stdout.strip() or r.stderr.strip(), "exit_code": r.returncode, "duration_ms": int((time.time() - start) * 1000)}


# ---------------------------------------------------------------------------
# REMEDIATION PROVABLE
# Catalog action fixes these — inject a failure the action can resolve
# ---------------------------------------------------------------------------

def inject_pods_crashlooping(namespace: str, kubeconfig: str = "") -> Dict:
    """Inject a crashlooping pod (exits immediately with /bin/false).

    Catalog action: oc delete pod --force (restart the pod)
    Reality: restart does NOT fix a fundamentally broken command.
    This is honestly an INVESTIGATION case — the pod will crash again
    after restart because the spec is wrong. Proving that the catalog
    action doesn't resolve this is a valid finding.

    Honest outcome: The proof system will show remediate succeeded
    (pod deleted) but verify failed (new pod still crashes). This
    proves the catalog needs a better action for this failure class.
    """
    _validate_namespace(namespace)
    name = "proof-crashloop"
    commands = []
    commands.append(_run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    commands.append(_run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
        "--", "/bin/false"
    ], kubeconfig))
    return {
        "failure_class": "pods_crashlooping",
        "injected_resources": [f"deployment/{name}"],
        "namespace": namespace,
        "commands": commands,
        "proof_type": "investigation",
        "catalog_action": "restart_crashlooping_pod",
        "why": "Pod command is /bin/false — restart cannot fix a bad spec. Proving catalog action is insufficient.",
    }


def inject_readiness_probe_failed(namespace: str, kubeconfig: str = "") -> Dict:
    """Inject a pod with a failing readiness probe (port 9999, nothing listens).

    Catalog action: oc rollout restart deployment
    Reality: restart creates new pods with the same bad probe config.
    The probe is misconfigured — restart cannot fix configuration.

    Honest outcome: remediate runs (rollout restart) but verify fails
    (new pods still fail readiness). Proves investigation needed.
    """
    _validate_namespace(namespace)
    name = "proof-readiness"
    commands = []
    commands.append(_run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    commands.append(_run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
        "--", "sleep", "3600"
    ], kubeconfig))
    patch = json.dumps({
        "spec": {"template": {"spec": {"containers": [{"name": "ubi-minimal", "readinessProbe": {
            "httpGet": {"port": 9999, "path": "/health"}, "periodSeconds": 5, "failureThreshold": 2
        }}]}}}
    })
    commands.append(_run_oc(["patch", "deployment", name, "-n", namespace, "-p", patch, "--type=strategic"], kubeconfig))
    return {
        "failure_class": "readiness_probe_failed",
        "injected_resources": [f"deployment/{name}"],
        "namespace": namespace,
        "commands": commands,
        "proof_type": "investigation",
        "catalog_action": "restart_readiness_failed_deployment",
        "why": "Probe targets port 9999 with no listener — rollout restart recreates the same misconfigured pods.",
    }


# ---------------------------------------------------------------------------
# INVESTIGATION PROVABLE
# No catalog auto-fix — prove diagnostic commands produce useful output
# ---------------------------------------------------------------------------

def inject_image_pull_backoff(namespace: str, kubeconfig: str = "") -> Dict:
    """Non-existent image → ImagePullBackOff. No auto-fix possible."""
    _validate_namespace(namespace)
    name = "proof-imagepull"
    commands = []
    commands.append(_run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    commands.append(_run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.example.com/nonexistent/image:v999"
    ], kubeconfig))
    return {
        "failure_class": "image_pull_backoff",
        "injected_resources": [f"deployment/{name}"],
        "namespace": namespace,
        "commands": commands,
        "proof_type": "investigation",
        "catalog_action": "inspect_image_pull_backoff",
        "why": "Image doesn't exist — must be fixed at source (registry/Containerfile).",
    }


def inject_claim_misbound(namespace: str, kubeconfig: str = "") -> Dict:
    """PVC referencing non-existent PV. No auto-fix possible."""
    _validate_namespace(namespace)
    name = "proof-misbound-pvc"
    commands = []
    commands.append(_run_oc(["delete", "pvc", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    pvc = {
        "apiVersion": "v1", "kind": "PersistentVolumeClaim",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": "1Gi"}},
            "volumeName": "nonexistent-pv-proof-test",
            "storageClassName": "",
        }
    }
    commands.append(_apply_manifest(pvc, namespace, kubeconfig))
    return {
        "failure_class": "claim_misbound",
        "injected_resources": [f"pvc/{name}"],
        "namespace": namespace,
        "commands": commands,
        "proof_type": "investigation",
        "catalog_action": "inspect_claim_misbound",
        "why": "PV doesn't exist — must recreate PV or rebind PVC.",
    }


def inject_oom_killed(namespace: str, kubeconfig: str = "") -> Dict:
    """Tiny memory limit causes OOM. No auto-fix possible."""
    _validate_namespace(namespace)
    name = "proof-oom"
    commands = []
    commands.append(_run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    commands.append(_run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
        "--", "sh", "-c", "head -c 10M /dev/urandom > /dev/null; sleep 3600"
    ], kubeconfig))
    patch = json.dumps({
        "spec": {"template": {"spec": {"containers": [{"name": "ubi-minimal", "resources": {
            "limits": {"memory": "4Mi"}
        }}]}}}
    })
    commands.append(_run_oc(["patch", "deployment", name, "-n", namespace, "-p", patch, "--type=strategic"], kubeconfig))
    return {
        "failure_class": "oom_killed",
        "injected_resources": [f"deployment/{name}"],
        "namespace": namespace,
        "commands": commands,
        "proof_type": "investigation",
        "catalog_action": "inspect_oom_killed",
        "why": "Memory limit is 4Mi — must increase limits in deployment spec.",
    }


def inject_quota_exceeded(namespace: str, kubeconfig: str = "") -> Dict:
    """Tight pod quota then over-deploy. No auto-fix possible."""
    _validate_namespace(namespace)
    commands = []
    quota = {
        "apiVersion": "v1", "kind": "ResourceQuota",
        "metadata": {"name": "proof-quota", "namespace": namespace},
        "spec": {"hard": {"pods": "1"}}
    }
    commands.append(_apply_manifest(quota, namespace, kubeconfig))
    name = "proof-quota-exceed"
    commands.append(_run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    commands.append(_run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
        "--replicas=3", "--", "sleep", "3600"
    ], kubeconfig))
    return {
        "failure_class": "quota_exceeded",
        "injected_resources": [f"resourcequota/proof-quota", f"deployment/{name}"],
        "namespace": namespace,
        "commands": commands,
        "proof_type": "investigation",
        "catalog_action": "inspect_quota_exceeded",
        "why": "Pod quota is 1, requesting 3 — must increase quota or reduce replicas.",
    }


def inject_scheduling_failed(namespace: str, kubeconfig: str = "") -> Dict:
    """Impossible node selector. No auto-fix possible."""
    _validate_namespace(namespace)
    name = "proof-unschedulable"
    commands = []
    commands.append(_run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    commands.append(_run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
        "--", "sleep", "3600"
    ], kubeconfig))
    patch = json.dumps({
        "spec": {"template": {"spec": {"nodeSelector": {"kubernetes.io/hostname": "nonexistent-node-proof"}}}}
    })
    commands.append(_run_oc(["patch", "deployment", name, "-n", namespace, "-p", patch, "--type=strategic"], kubeconfig))
    return {
        "failure_class": "scheduling_failed",
        "injected_resources": [f"deployment/{name}"],
        "namespace": namespace,
        "commands": commands,
        "proof_type": "investigation",
        "catalog_action": "inspect_scheduling_failed",
        "why": "Node 'nonexistent-node-proof' doesn't exist — must fix nodeSelector or add node.",
    }


INJECTORS = {
    "pods_crashlooping": inject_pods_crashlooping,
    "readiness_probe_failed": inject_readiness_probe_failed,
    "image_pull_backoff": inject_image_pull_backoff,
    "claim_misbound": inject_claim_misbound,
    "oom_killed": inject_oom_killed,
    "quota_exceeded": inject_quota_exceeded,
    "scheduling_failed": inject_scheduling_failed,
}


def inject_failure(failure_class: str, namespace: str, kubeconfig: str = "") -> Dict:
    _validate_namespace(namespace)
    injector = INJECTORS.get(failure_class)
    if not injector:
        return {"error": f"No injector for failure class '{failure_class}'", "available": list(INJECTORS.keys())}
    return injector(namespace, kubeconfig)


def cleanup_all(namespace: str, kubeconfig: str = "") -> Dict:
    _validate_namespace(namespace)
    commands = []
    deleted = []
    for name in ["proof-crashloop", "proof-readiness", "proof-imagepull", "proof-oom", "proof-quota-exceed", "proof-unschedulable"]:
        trace = _run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig)
        commands.append(trace)
        if "deleted" in trace["output"].lower():
            deleted.append(f"deployment/{name}")
    for name, kind in [("proof-misbound-pvc", "pvc"), ("proof-quota", "resourcequota"), ("proof-crashloop-ready", "configmap")]:
        trace = _run_oc(["delete", kind, name, "-n", namespace, "--ignore-not-found"], kubeconfig)
        commands.append(trace)
        if "deleted" in trace["output"].lower():
            deleted.append(f"{kind}/{name}")
    return {"namespace": namespace, "deleted": deleted, "commands": commands}
