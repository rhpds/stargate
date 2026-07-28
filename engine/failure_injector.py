"""Failure injector — creates broken K8s resources in the test namespace.

SAFETY: Only operates on the designated test namespace. Refuses all
operations on any other namespace. Every function validates this.
"""

import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger("stargate.failure_injector")

ALLOWED_NAMESPACE = os.environ.get("STARGATE_TEST_NAMESPACE", "stargate-test")


def _validate_namespace(namespace: str):
    """Refuse to operate outside the test namespace."""
    if namespace != ALLOWED_NAMESPACE:
        raise ValueError(f"Failure injection BLOCKED: namespace '{namespace}' is not the test namespace '{ALLOWED_NAMESPACE}'")


def _run_oc(args: List[str], kubeconfig: str = "") -> str:
    """Run an oc command and return stdout. Uses engine.rollback._run_oc pattern."""
    import subprocess
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    r = subprocess.run(["oc"] + args, capture_output=True, text=True, timeout=30, env=env)
    if r.returncode != 0 and "not found" not in r.stderr and "No resources" not in r.stderr:
        logger.warning("oc %s failed: %s", " ".join(args[:3]), r.stderr.strip()[:200])
    return r.stdout.strip()


def inject_pods_crashlooping(namespace: str, kubeconfig: str = "") -> Dict:
    """Deploy a pod that immediately CrashLoops (invalid command)."""
    _validate_namespace(namespace)
    name = "proof-crashloop"
    _run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig)
    _run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
        "--", "/bin/false"
    ], kubeconfig)
    return {"failure_class": "pods_crashlooping", "injected_resources": [f"deployment/{name}"], "namespace": namespace}


def inject_readiness_probe_failed(namespace: str, kubeconfig: str = "") -> Dict:
    """Deploy a pod with a readiness probe on a port nothing listens on."""
    _validate_namespace(namespace)
    name = "proof-readiness"
    _run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig)
    _run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
        "--", "sleep", "3600"
    ], kubeconfig)
    # Patch to add a readiness probe on a port that nothing listens on
    import json
    patch = json.dumps({
        "spec": {"template": {"spec": {"containers": [{"name": "ubi-minimal", "readinessProbe": {
            "httpGet": {"port": 9999, "path": "/health"}, "periodSeconds": 5, "failureThreshold": 2
        }}]}}}
    })
    _run_oc(["patch", "deployment", name, "-n", namespace, "-p", patch, "--type=strategic"], kubeconfig)
    return {"failure_class": "readiness_probe_failed", "injected_resources": [f"deployment/{name}"], "namespace": namespace}


def inject_image_pull_backoff(namespace: str, kubeconfig: str = "") -> Dict:
    """Deploy with a non-existent image to trigger ImagePullBackOff."""
    _validate_namespace(namespace)
    name = "proof-imagepull"
    _run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig)
    _run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.example.com/nonexistent/image:v999"
    ], kubeconfig)
    return {"failure_class": "image_pull_backoff", "injected_resources": [f"deployment/{name}"], "namespace": namespace}


def inject_claim_misbound(namespace: str, kubeconfig: str = "") -> Dict:
    """Create a PVC referencing a non-existent PV."""
    _validate_namespace(namespace)
    name = "proof-misbound-pvc"
    _run_oc(["delete", "pvc", name, "-n", namespace, "--ignore-not-found"], kubeconfig)
    import json, subprocess
    pvc = json.dumps({
        "apiVersion": "v1", "kind": "PersistentVolumeClaim",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": "1Gi"}},
            "volumeName": "nonexistent-pv-proof-test",
            "storageClassName": ""
        }
    })
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    subprocess.run(["oc", "apply", "-f", "-", "-n", namespace], input=pvc, capture_output=True, text=True, env=env)
    return {"failure_class": "claim_misbound", "injected_resources": [f"pvc/{name}"], "namespace": namespace}


def inject_oom_killed(namespace: str, kubeconfig: str = "") -> Dict:
    """Deploy a pod with tiny memory limit that OOM kills."""
    _validate_namespace(namespace)
    name = "proof-oom"
    _run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig)
    _run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
        "--", "sh", "-c", "dd if=/dev/zero of=/dev/null bs=1M"
    ], kubeconfig)
    import json
    patch = json.dumps({
        "spec": {"template": {"spec": {"containers": [{"name": "ubi-minimal", "resources": {
            "limits": {"memory": "4Mi"}
        }}]}}}
    })
    _run_oc(["patch", "deployment", name, "-n", namespace, "-p", patch, "--type=strategic"], kubeconfig)
    return {"failure_class": "oom_killed", "injected_resources": [f"deployment/{name}"], "namespace": namespace}


def inject_quota_exceeded(namespace: str, kubeconfig: str = "") -> Dict:
    """Set a tight ResourceQuota then deploy past it."""
    _validate_namespace(namespace)
    import json, subprocess
    quota = json.dumps({
        "apiVersion": "v1", "kind": "ResourceQuota",
        "metadata": {"name": "proof-quota", "namespace": namespace},
        "spec": {"hard": {"pods": "1"}}
    })
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    subprocess.run(["oc", "apply", "-f", "-", "-n", namespace], input=quota, capture_output=True, text=True, env=env)
    name = "proof-quota-exceed"
    _run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig)
    _run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
        "--replicas=3", "--", "sleep", "3600"
    ], kubeconfig)
    return {"failure_class": "quota_exceeded", "injected_resources": [f"resourcequota/proof-quota", f"deployment/{name}"], "namespace": namespace}


def inject_scheduling_failed(namespace: str, kubeconfig: str = "") -> Dict:
    """Deploy with an impossible node selector."""
    _validate_namespace(namespace)
    name = "proof-unschedulable"
    _run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig)
    _run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
        "--", "sleep", "3600"
    ], kubeconfig)
    import json
    patch = json.dumps({
        "spec": {"template": {"spec": {"nodeSelector": {"kubernetes.io/hostname": "nonexistent-node-proof"}}}}
    })
    _run_oc(["patch", "deployment", name, "-n", namespace, "-p", patch, "--type=strategic"], kubeconfig)
    return {"failure_class": "scheduling_failed", "injected_resources": [f"deployment/{name}"], "namespace": namespace}


# Registry of all injectors
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
    """Inject a specific failure class into the test namespace."""
    _validate_namespace(namespace)
    injector = INJECTORS.get(failure_class)
    if not injector:
        return {"error": f"No injector for failure class '{failure_class}'", "available": list(INJECTORS.keys())}
    return injector(namespace, kubeconfig)


def cleanup_all(namespace: str, kubeconfig: str = "") -> Dict:
    """Remove all proof-injected resources from the test namespace."""
    _validate_namespace(namespace)
    deleted = []
    for name in ["proof-crashloop", "proof-readiness", "proof-imagepull", "proof-oom", "proof-quota-exceed", "proof-unschedulable"]:
        out = _run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig)
        if "deleted" in out.lower():
            deleted.append(f"deployment/{name}")
    out = _run_oc(["delete", "pvc", "proof-misbound-pvc", "-n", namespace, "--ignore-not-found"], kubeconfig)
    if "deleted" in out.lower():
        deleted.append("pvc/proof-misbound-pvc")
    out = _run_oc(["delete", "resourcequota", "proof-quota", "-n", namespace, "--ignore-not-found"], kubeconfig)
    if "deleted" in out.lower():
        deleted.append("resourcequota/proof-quota")
    return {"namespace": namespace, "deleted": deleted}
