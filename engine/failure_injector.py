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


def inject_backoff_limit_exceeded(namespace: str, kubeconfig: str = "") -> Dict:
    """Job that fails and exceeds backoff limit."""
    _validate_namespace(namespace)
    name = "proof-backoff-job"
    commands = []
    commands.append(_run_oc(["delete", "job", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    job = {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {"backoffLimit": 1, "template": {"spec": {
            "restartPolicy": "Never",
            "containers": [{"name": "fail", "image": "registry.access.redhat.com/ubi9/ubi-minimal:latest", "command": ["/bin/false"]}]
        }}}
    }
    commands.append(_apply_manifest(job, namespace, kubeconfig))
    return {
        "failure_class": "backoff_limit_exceeded", "injected_resources": [f"job/{name}"],
        "namespace": namespace, "commands": commands,
        "proof_type": "investigation", "catalog_action": "inspect_backoff_limit_exceeded",
        "why": "Job runs /bin/false — must fix the job spec.",
    }


def inject_image_pull_secret_missing(namespace: str, kubeconfig: str = "") -> Dict:
    """Deploy with image from registry requiring auth, no pull secret."""
    _validate_namespace(namespace)
    name = "proof-no-secret"
    commands = []
    commands.append(_run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    commands.append(_run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.redhat.io/ubi9/ubi-minimal:latest"
    ], kubeconfig))
    return {
        "failure_class": "image_pull_secret_missing", "injected_resources": [f"deployment/{name}"],
        "namespace": namespace, "commands": commands,
        "proof_type": "investigation", "catalog_action": "inspect_image_pull_secret_missing",
        "why": "registry.redhat.io requires auth — must create pull secret.",
    }


def inject_deprecated_api(namespace: str, kubeconfig: str = "") -> Dict:
    """Create resource with deprecated annotation."""
    _validate_namespace(namespace)
    name = "proof-deprecated"
    commands = []
    commands.append(_run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    commands.append(_run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
        "--", "sleep", "3600"
    ], kubeconfig))
    patch = json.dumps({"metadata": {"annotations": {"deprecated-annotation-proof": "true"}}})
    commands.append(_run_oc(["annotate", "deployment", name, "-n", namespace, "deprecated-annotation-proof=true"], kubeconfig))
    return {
        "failure_class": "deprecated_api", "injected_resources": [f"deployment/{name}"],
        "namespace": namespace, "commands": commands,
        "proof_type": "investigation", "catalog_action": "inspect_deprecated_api",
        "why": "Deprecated annotation — must update to current API.",
    }


def inject_sync_failed(namespace: str, kubeconfig: str = "") -> Dict:
    """Create a deployment and scale to trigger controller reconciliation events.

    Catalog action: inspect sync/reconcile events
    Reality: Controller activity generates events — detection relies on
    SyncFailed or ReconcileFailed events appearing in the namespace.

    Honest outcome: Detection may timeout if the cluster doesn't emit
    these specific event types — that's an honest result showing this
    failure class is hard to synthetically reproduce.
    """
    _validate_namespace(namespace)
    name = "proof-sync-fail"
    commands = []
    commands.append(_run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    commands.append(_run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
        "--", "sleep", "3600"
    ], kubeconfig))
    commands.append(_run_oc(["scale", "deployment", name, "--replicas=2", "-n", namespace], kubeconfig))
    return {
        "failure_class": "sync_failed",
        "injected_resources": [f"deployment/{name}"],
        "namespace": namespace,
        "commands": commands,
        "proof_type": "investigation",
        "catalog_action": "inspect_sync_failed",
        "why": "Controller reconciliation triggered — detection relies on SyncFailed/ReconcileFailed events.",
    }


def inject_pod_pending(namespace: str, kubeconfig: str = "") -> Dict:
    """Deploy with enormous CPU request (100 cores) that no node can satisfy.

    Catalog action: inspect pending pods
    Reality: No node has 100 CPU cores available — pod stays Pending
    with FailedScheduling events forever.

    Honest outcome: Pod remains Pending — must reduce CPU request or
    add capacity.
    """
    _validate_namespace(namespace)
    name = "proof-pending"
    commands = []
    commands.append(_run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    commands.append(_run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
        "--", "sleep", "3600"
    ], kubeconfig))
    patch = json.dumps({
        "spec": {"template": {"spec": {"containers": [{"name": "ubi-minimal", "resources": {
            "requests": {"cpu": "100"}
        }}]}}}
    })
    commands.append(_run_oc(["patch", "deployment", name, "-n", namespace, "-p", patch, "--type=strategic"], kubeconfig))
    return {
        "failure_class": "pod_pending",
        "injected_resources": [f"deployment/{name}"],
        "namespace": namespace,
        "commands": commands,
        "proof_type": "investigation",
        "catalog_action": "inspect_pod_pending",
        "why": "CPU request is 100 cores — no node can satisfy this. Must reduce request or add capacity.",
    }


def inject_volume_mount_failed(namespace: str, kubeconfig: str = "") -> Dict:
    """Deploy with a volume referencing a non-existent secret.

    Catalog action: inspect volume mount failures
    Reality: Secret doesn't exist — pod stuck in ContainerCreating with
    FailedMount events.

    Honest outcome: Must create the secret or remove the volume mount.
    """
    _validate_namespace(namespace)
    name = "proof-volmount"
    commands = []
    commands.append(_run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    deploy = {
        "apiVersion": "apps/v1", "kind": "Deployment",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {"replicas": 1, "selector": {"matchLabels": {"app": name}},
            "template": {"metadata": {"labels": {"app": name}},
                "spec": {"containers": [{"name": "app", "image": "registry.access.redhat.com/ubi9/ubi-minimal:latest",
                    "command": ["sleep", "3600"],
                    "volumeMounts": [{"name": "secret-vol", "mountPath": "/secret"}]}],
                    "volumes": [{"name": "secret-vol", "secret": {"secretName": "nonexistent-secret-proof"}}]}}}
    }
    commands.append(_apply_manifest(deploy, namespace, kubeconfig))
    return {
        "failure_class": "volume_mount_failed",
        "injected_resources": [f"deployment/{name}"],
        "namespace": namespace,
        "commands": commands,
        "proof_type": "investigation",
        "catalog_action": "inspect_volume_mount_failed",
        "why": "Secret 'nonexistent-secret-proof' doesn't exist — must create it or remove the volume mount.",
    }


def inject_invalid_configuration(namespace: str, kubeconfig: str = "") -> Dict:
    """Deploy a pod that references a non-existent configmap as envFrom.

    Catalog action: inspect invalid configuration
    Reality: ConfigMap doesn't exist — pod stuck in CreateContainerConfigError.

    Honest outcome: Must create the configmap or remove the envFrom reference.
    """
    _validate_namespace(namespace)
    name = "proof-invalid-config"
    commands = []
    commands.append(_run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    deploy = {
        "apiVersion": "apps/v1", "kind": "Deployment",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {"replicas": 1, "selector": {"matchLabels": {"app": name}},
            "template": {"metadata": {"labels": {"app": name}},
                "spec": {"containers": [{"name": "app", "image": "registry.access.redhat.com/ubi9/ubi-minimal:latest",
                    "command": ["sleep", "3600"],
                    "envFrom": [{"configMapRef": {"name": "nonexistent-config-proof"}}]}]}}}
    }
    commands.append(_apply_manifest(deploy, namespace, kubeconfig))
    return {
        "failure_class": "invalid_configuration",
        "injected_resources": [f"deployment/{name}"],
        "namespace": namespace,
        "commands": commands,
        "proof_type": "investigation",
        "catalog_action": "inspect_invalid_configuration",
        "why": "ConfigMap 'nonexistent-config-proof' doesn't exist — must create it or remove the envFrom reference.",
    }


def inject_datasource_unrecognized(namespace: str, kubeconfig: str = "") -> Dict:
    """Deploy with an annotation marking an unrecognized datasource.

    Catalog action: inspect unrecognized datasource
    Reality: CDI DataVolume with invalid source would fail — we simulate
    this with an annotation since CDI may not be installed.

    Honest outcome: Must fix the datasource reference or install CDI.
    """
    _validate_namespace(namespace)
    name = "proof-datasource"
    commands = []
    commands.append(_run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    commands.append(_run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
        "--", "sleep", "3600"
    ], kubeconfig))
    commands.append(_run_oc(["annotate", "deployment", name, "cdi.kubevirt.io/unrecognizedDataSource=true", "-n", namespace], kubeconfig))
    return {
        "failure_class": "datasource_unrecognized",
        "injected_resources": [f"deployment/{name}"],
        "namespace": namespace,
        "commands": commands,
        "proof_type": "investigation",
        "catalog_action": "inspect_datasource_unrecognized",
        "why": "Unrecognized datasource annotation — must fix datasource reference or install CDI.",
    }


def inject_volume_attach_failed(namespace: str, kubeconfig: str = "") -> Dict:
    """Create a PVC with a specific volumeName that doesn't exist, then
    create a pod that tries to use it.

    Catalog action: inspect volume attach failures
    Reality: PV doesn't exist — PVC stays Pending and pod can't start,
    generating FailedAttachVolume events.

    Honest outcome: Must create the PV or rebind the PVC.
    """
    _validate_namespace(namespace)
    name = "proof-volattach"
    pvc_name = f"{name}-pvc"
    commands = []
    commands.append(_run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    commands.append(_run_oc(["delete", "pvc", pvc_name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    pvc = {
        "apiVersion": "v1", "kind": "PersistentVolumeClaim",
        "metadata": {"name": pvc_name, "namespace": namespace},
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": "1Gi"}},
            "volumeName": "nonexistent-pv-attach-proof",
            "storageClassName": "",
        }
    }
    commands.append(_apply_manifest(pvc, namespace, kubeconfig))
    deploy = {
        "apiVersion": "apps/v1", "kind": "Deployment",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {"replicas": 1, "selector": {"matchLabels": {"app": name}},
            "template": {"metadata": {"labels": {"app": name}},
                "spec": {"containers": [{"name": "app", "image": "registry.access.redhat.com/ubi9/ubi-minimal:latest",
                    "command": ["sleep", "3600"],
                    "volumeMounts": [{"name": "data", "mountPath": "/data"}]}],
                    "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": pvc_name}}]}}}
    }
    commands.append(_apply_manifest(deploy, namespace, kubeconfig))
    return {
        "failure_class": "volume_attach_failed",
        "injected_resources": [f"pvc/{pvc_name}", f"deployment/{name}"],
        "namespace": namespace,
        "commands": commands,
        "proof_type": "investigation",
        "catalog_action": "inspect_volume_attach_failed",
        "why": "PV 'nonexistent-pv-attach-proof' doesn't exist — PVC stays Pending and pod can't mount volume.",
    }


def inject_volume_resize_failed(namespace: str, kubeconfig: str = "") -> Dict:
    """Create a small PVC then try to resize it beyond capacity.

    Catalog action: inspect volume resize failures
    Reality: Resizing to 1000Ti likely exceeds capacity or the storage
    class doesn't support expansion — generates VolumeResizeFailed events.

    Honest outcome: Must use a supported size or enable volume expansion
    on the storage class.
    """
    _validate_namespace(namespace)
    name = "proof-volresize"
    pvc_name = f"{name}-pvc"
    commands = []
    commands.append(_run_oc(["delete", "pvc", pvc_name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    pvc = {
        "apiVersion": "v1", "kind": "PersistentVolumeClaim",
        "metadata": {"name": pvc_name, "namespace": namespace},
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": "1Gi"}},
            "storageClassName": "ocs-storagecluster-ceph-rbd",
        }
    }
    commands.append(_apply_manifest(pvc, namespace, kubeconfig))
    patch = json.dumps({"spec": {"resources": {"requests": {"storage": "1000Ti"}}}})
    commands.append(_run_oc(["patch", "pvc", pvc_name, "-n", namespace, "-p", patch], kubeconfig))
    return {
        "failure_class": "volume_resize_failed",
        "injected_resources": [f"pvc/{pvc_name}"],
        "namespace": namespace,
        "commands": commands,
        "proof_type": "investigation",
        "catalog_action": "inspect_volume_resize_failed",
        "why": "Resize to 1000Ti exceeds capacity — must use a supported size or enable expansion.",
    }


def inject_resolution_failed(namespace: str, kubeconfig: str = "") -> Dict:
    """Create a Subscription referencing a non-existent operator.

    Catalog action: inspect resolution failures
    Reality: Operator doesn't exist in the catalog — Subscription stays
    in ResolutionFailed state.

    Honest outcome: Must fix the operator name or ensure the catalog source
    contains the operator.
    """
    _validate_namespace(namespace)
    name = "proof-resolution"
    commands = []
    commands.append(_run_oc(["delete", "subscription", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    sub = {
        "apiVersion": "operators.coreos.com/v1alpha1", "kind": "Subscription",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "channel": "stable",
            "name": "nonexistent-operator-proof",
            "source": "redhat-operators",
            "sourceNamespace": "openshift-marketplace",
        }
    }
    commands.append(_apply_manifest(sub, namespace, kubeconfig))
    return {
        "failure_class": "resolution_failed",
        "injected_resources": [f"subscription/{name}"],
        "namespace": namespace,
        "commands": commands,
        "proof_type": "investigation",
        "catalog_action": "inspect_resolution_failed",
        "why": "Operator 'nonexistent-operator-proof' doesn't exist — must fix operator name or catalog source.",
    }


def inject_hpa_metric_failure(namespace: str, kubeconfig: str = "") -> Dict:
    """Create a deployment with no CPU requests, then create an HPA targeting it.

    Catalog action: inspect HPA metric failures
    Reality: HPA can't compute CPU utilization percentage without a CPU
    request — generates FailedGetResourceMetric events.

    Honest outcome: Must add CPU requests to the deployment or change
    the HPA metric type.
    """
    _validate_namespace(namespace)
    name = "proof-hpa"
    commands = []
    commands.append(_run_oc(["delete", "hpa", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    commands.append(_run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    commands.append(_run_oc([
        "create", "deployment", name, "-n", namespace,
        "--image=registry.access.redhat.com/ubi9/ubi-minimal:latest",
        "--", "sleep", "3600"
    ], kubeconfig))
    hpa = {
        "apiVersion": "autoscaling/v2", "kind": "HorizontalPodAutoscaler",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {
            "scaleTargetRef": {"apiVersion": "apps/v1", "kind": "Deployment", "name": name},
            "minReplicas": 1, "maxReplicas": 3,
            "metrics": [{"type": "Resource", "resource": {
                "name": "cpu", "target": {"type": "Utilization", "averageUtilization": 50}
            }}]
        }
    }
    commands.append(_apply_manifest(hpa, namespace, kubeconfig))
    return {
        "failure_class": "hpa_metric_failure",
        "injected_resources": [f"deployment/{name}", f"hpa/{name}"],
        "namespace": namespace,
        "commands": commands,
        "proof_type": "investigation",
        "catalog_action": "inspect_hpa_metric_failure",
        "why": "No CPU request on deployment — HPA can't compute utilization. Must add CPU requests.",
    }


def inject_pvc_binding_failed(namespace: str, kubeconfig: str = "") -> Dict:
    """PVC requesting non-existent storage class."""
    _validate_namespace(namespace)
    name = "proof-pvc-nobind"
    commands = []
    commands.append(_run_oc(["delete", "pvc", name, "-n", namespace, "--ignore-not-found"], kubeconfig))
    pvc = {
        "apiVersion": "v1", "kind": "PersistentVolumeClaim",
        "metadata": {"name": name, "namespace": namespace},
        "spec": {"accessModes": ["ReadWriteOnce"], "resources": {"requests": {"storage": "1Gi"}},
                 "storageClassName": "nonexistent-storage-class-proof"}
    }
    commands.append(_apply_manifest(pvc, namespace, kubeconfig))
    return {
        "failure_class": "pvc_binding_failed", "injected_resources": [f"pvc/{name}"],
        "namespace": namespace, "commands": commands,
        "proof_type": "investigation", "catalog_action": "inspect_pvc_binding_failed",
        "why": "Storage class doesn't exist — must create it or use a valid one.",
    }


INJECTORS = {
    "pods_crashlooping": inject_pods_crashlooping,
    "readiness_probe_failed": inject_readiness_probe_failed,
    "image_pull_backoff": inject_image_pull_backoff,
    "claim_misbound": inject_claim_misbound,
    "oom_killed": inject_oom_killed,
    "quota_exceeded": inject_quota_exceeded,
    "scheduling_failed": inject_scheduling_failed,
    "backoff_limit_exceeded": inject_backoff_limit_exceeded,
    "image_pull_secret_missing": inject_image_pull_secret_missing,
    "deprecated_api": inject_deprecated_api,
    "pvc_binding_failed": inject_pvc_binding_failed,
    "sync_failed": inject_sync_failed,
    "pod_pending": inject_pod_pending,
    "volume_mount_failed": inject_volume_mount_failed,
    "invalid_configuration": inject_invalid_configuration,
    "datasource_unrecognized": inject_datasource_unrecognized,
    "volume_attach_failed": inject_volume_attach_failed,
    "volume_resize_failed": inject_volume_resize_failed,
    "resolution_failed": inject_resolution_failed,
    "hpa_metric_failure": inject_hpa_metric_failure,
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
    for name in [
        "proof-crashloop", "proof-readiness", "proof-imagepull", "proof-oom",
        "proof-quota-exceed", "proof-unschedulable", "proof-no-secret", "proof-deprecated",
        "proof-sync-fail", "proof-pending", "proof-volmount", "proof-invalid-config",
        "proof-datasource", "proof-volattach", "proof-volresize", "proof-hpa",
    ]:
        trace = _run_oc(["delete", "deployment", name, "-n", namespace, "--ignore-not-found"], kubeconfig)
        commands.append(trace)
        if "deleted" in trace["output"].lower():
            deleted.append(f"deployment/{name}")
    # Jobs
    for name in ["proof-backoff-job"]:
        trace = _run_oc(["delete", "job", name, "-n", namespace, "--ignore-not-found"], kubeconfig)
        commands.append(trace)
        if "deleted" in trace["output"].lower():
            deleted.append(f"job/{name}")
    # PVCs, quotas, configmaps
    for name, kind in [
        ("proof-misbound-pvc", "pvc"), ("proof-pvc-nobind", "pvc"),
        ("proof-volattach-pvc", "pvc"), ("proof-volresize-pvc", "pvc"),
        ("proof-quota", "resourcequota"), ("proof-crashloop-ready", "configmap"),
    ]:
        trace = _run_oc(["delete", kind, name, "-n", namespace, "--ignore-not-found"], kubeconfig)
        commands.append(trace)
        if "deleted" in trace["output"].lower():
            deleted.append(f"{kind}/{name}")
    # HPAs
    for name in ["proof-hpa"]:
        trace = _run_oc(["delete", "hpa", name, "-n", namespace, "--ignore-not-found"], kubeconfig)
        commands.append(trace)
        if "deleted" in trace["output"].lower():
            deleted.append(f"hpa/{name}")
    # Subscriptions
    for name in ["proof-resolution"]:
        trace = _run_oc(["delete", "subscription", name, "-n", namespace, "--ignore-not-found"], kubeconfig)
        commands.append(trace)
        if "deleted" in trace["output"].lower():
            deleted.append(f"subscription/{name}")
    return {"namespace": namespace, "deleted": deleted, "commands": commands}
