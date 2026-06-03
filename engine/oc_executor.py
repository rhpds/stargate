"""OpenShift command executor — maps recommendations to real oc commands.

Tries remediation catalog (remediations/catalog.yaml) first, falls back to
built-in command mapping. Executes real oc commands against a target namespace,
with full command logging and error capture.
"""

import json
import logging
import re
from typing import Any, Dict, List

from engine.rollback import _run_oc

logger = logging.getLogger("stargate.oc_executor")

_SAFE_K8S_NAME = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")


def _validate_k8s_name(value: str, field: str) -> str:
    if not value or not _SAFE_K8S_NAME.match(value):
        raise ValueError(f"Invalid {field}: {value!r}")
    return value


def map_action_to_commands(action_type: str, namespace: str, params: Dict[str, Any]) -> List[str]:
    """Map a recommendation type to oc CLI commands.

    Tries the YAML remediation catalog first; falls back to built-in mapping.
    """
    try:
        from engine.catalog_loader import get_commands_for_action
        catalog_commands = get_commands_for_action(action_type, namespace, params)
        if catalog_commands:
            return catalog_commands
    except Exception:
        pass

    return _builtin_commands(action_type, namespace, params)


def _builtin_commands(action_type: str, namespace: str, params: Dict[str, Any]) -> List[str]:
    """Built-in command mapping — fallback when catalog has no matching entry."""
    commands = []

    _validate_k8s_name(namespace, "namespace")

    if action_type == "cluster_capacity":
        dep = _validate_k8s_name(params.get("deployment", "app"), "deployment")
        replicas = int(params.get("replicas", 3))
        image = params.get("image")
        if image and re.match(r"^[a-zA-Z0-9._/:\-]+$", image):
            commands.append(f"oc create deployment {dep} --image={image} -n {namespace}")
        commands.append(f"oc scale deployment/{dep} --replicas={replicas} -n {namespace}")

    elif action_type == "cleanup_stuck":
        for pod in params.get("pods", []):
            _validate_k8s_name(pod, "pod")
            commands.append(f"oc delete pod {pod} -n {namespace} --force --grace-period=0")

    elif action_type == "provision_blocked_lab":
        commands.append(f"oc apply -f - -n {namespace}")

    elif action_type == "pool_exhaustion":
        pool = _validate_k8s_name(params.get("pool", "default-pool"), "pool")
        commands.append(f"oc patch resourcepool {pool} -n {namespace} --type=merge -p '{{\"spec\":{{\"minAvailable\":5}}}}'")

    elif action_type == "smoke_test_failing":
        dep = _validate_k8s_name(params.get("deployment", "showroom"), "deployment")
        commands.append(f"oc rollout restart deployment/{dep} -n {namespace}")

    return commands


def execute_oc_action(
    action_type: str,
    namespace: str,
    kubeconfig: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute an action as real oc commands against a namespace."""
    # Check if this action maps to an investigation chain
    try:
        from engine.catalog_loader import load_catalog, ACTION_TO_FAILURE_CLASSES
        failure_classes = ACTION_TO_FAILURE_CLASSES.get(action_type, [])
        if failure_classes:
            catalog = load_catalog()
            for entry in catalog:
                if getattr(entry, "type", "remediation") == "investigation":
                    entry_classes = set()
                    for condition in entry.allowed_when:
                        parts = condition.split("==")
                        if len(parts) == 2 and parts[0].strip() == "failure_class":
                            entry_classes.add(parts[1].strip())
                    if entry_classes & set(failure_classes):
                        from engine.investigation_runner import InvestigationRunner
                        runner = InvestigationRunner()
                        return runner.run(
                            entry=entry.model_dump(),
                            namespace=namespace,
                            kubeconfig=kubeconfig,
                            params=params,
                        )
    except Exception:
        logger.debug("Investigation routing check failed, falling back to commands", exc_info=True)

    commands_planned = map_action_to_commands(action_type, namespace, params)
    commands_executed = []
    errors = []

    dep = params.get("deployment", "app")
    image = params.get("image", "registry.access.redhat.com/ubi9/ubi-minimal:latest")
    _validate_k8s_name(dep, "deployment")
    if image and not re.match(r"^[a-zA-Z0-9._/:\-]+$", image):
        raise ValueError(f"Invalid image: {image!r}")

    for cmd_str in commands_planned:
        parts = cmd_str.split()
        if parts[0] == "oc":
            parts = parts[1:]

        try:
            if "create deployment" in cmd_str:
                result = _run_oc([
                    "create", "deployment", dep,
                    f"--image={image}",
                    "-n", namespace,
                ], kubeconfig)
                commands_executed.append({"command": cmd_str, "result": result, "success": "created" in result.lower() or "already exists" in result.lower()})

            elif "scale" in cmd_str:
                replicas = str(params.get("replicas", 3))
                result = _run_oc([
                    "scale", f"deployment/{dep}",
                    f"--replicas={replicas}",
                    "-n", namespace,
                ], kubeconfig)
                commands_executed.append({"command": cmd_str, "result": result, "success": "scaled" in result.lower() or result == ""})

            elif "delete pod" in cmd_str:
                pod = params.get("pod", "")
                if not pod:
                    for p in params.get("pods", []):
                        if p in cmd_str:
                            pod = p
                            break
                _validate_k8s_name(pod, "pod")
                result = _run_oc(["delete", "pod", pod, "-n", namespace, "--ignore-not-found"], kubeconfig)
                commands_executed.append({"command": cmd_str, "result": result, "success": True})

            elif "rollout restart" in cmd_str:
                result = _run_oc(["rollout", "restart", f"deployment/{dep}", "-n", namespace], kubeconfig)
                commands_executed.append({"command": cmd_str, "result": result, "success": "restarted" in result.lower() or result == ""})

            else:
                logger.warning(f"Unrecognized command pattern, skipping: {cmd_str}")
                commands_executed.append({"command": cmd_str, "result": "skipped: unrecognized command pattern", "success": False})

        except Exception as e:
            errors.append({"command": cmd_str, "error": str(e)})
            commands_executed.append({"command": cmd_str, "result": str(e), "success": False})

    success = len(errors) == 0 and all(c.get("success", False) for c in commands_executed)

    logger.info(f"Executed {len(commands_executed)} commands for {action_type} on {namespace}: success={success}")

    return {
        "success": success,
        "action_type": action_type,
        "namespace": namespace,
        "commands_planned": commands_planned,
        "commands_executed": commands_executed,
        "errors": errors,
    }
