"""RHDP API client — route remediation actions through the RHDP ecosystem.

Instead of executing raw oc commands that bypass RHDP controllers,
this client calls the appropriate RHDP APIs:
- Anarchy: retry/destroy AnarchySubjects via CRD patch
- Poolboy: request pool scaling via ResourcePool patch
- Sandbox API: trigger placement actions (start/stop/destroy)
"""

import json
import logging
import os
import ssl
import urllib.request
from typing import Any, Dict, Optional

logger = logging.getLogger("stargate.rhdp_client")

SANDBOX_API_URL = os.environ.get("STARGATE_SANDBOX_API_URL", "")


def _make_ssl_ctx():
    ctx = ssl.create_default_context()
    if os.environ.get("STARGATE_SSL_VERIFY", "true").lower() == "false":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _run_oc_patch(resource: str, name: str, namespace: str, patch: Dict, kubeconfig: str = "") -> Dict[str, Any]:
    """Patch a Kubernetes resource via oc (used for Anarchy/Poolboy CRDs)."""
    import subprocess
    cmd = ["oc", "patch", resource, name, "-n", namespace, "--type=merge", "-p", json.dumps(patch)]
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        return {"success": r.returncode == 0, "output": r.stdout.strip(), "error": r.stderr.strip()}
    except Exception as e:
        return {"success": False, "error": str(e)}


def retry_provision(anarchy_subject: str, namespace: str = "babylon-anarchy-events", kubeconfig: str = "") -> Dict[str, Any]:
    """Request Anarchy to retry a failed provision by patching the AnarchySubject."""
    logger.info(f"RHDP: Requesting provision retry for {anarchy_subject}")
    patch = {"spec": {"vars": {"desired_state": "started"}}}
    return _run_oc_patch("anarchysubject", anarchy_subject, namespace, patch, kubeconfig)


def destroy_gracefully(anarchy_subject: str, namespace: str = "babylon-anarchy-events", kubeconfig: str = "") -> Dict[str, Any]:
    """Request Anarchy to gracefully destroy an AnarchySubject."""
    logger.info(f"RHDP: Requesting graceful destroy for {anarchy_subject}")
    patch = {"spec": {"vars": {"desired_state": "destroyed"}}}
    return _run_oc_patch("anarchysubject", anarchy_subject, namespace, patch, kubeconfig)


def request_pool_scaling(pool: str, min_available: int, namespace: str = "poolboy", kubeconfig: str = "") -> Dict[str, Any]:
    """Request pool scaling through Poolboy by patching the ResourcePool spec."""
    logger.info(f"RHDP: Requesting pool {pool} scaling to minAvailable={min_available}")
    patch = {"spec": {"minAvailable": min_available}}
    return _run_oc_patch("resourcepool", pool, namespace, patch, kubeconfig)


def sandbox_api_action(placement_uuid: str, action: str = "delete") -> Dict[str, Any]:
    """Trigger a Sandbox API placement action (start/stop/destroy/delete)."""
    if not SANDBOX_API_URL:
        return {"success": False, "error": "STARGATE_SANDBOX_API_URL not configured"}

    logger.info(f"RHDP: Sandbox API {action} for placement {placement_uuid}")
    ctx = _make_ssl_ctx()

    try:
        if action == "delete":
            url = f"{SANDBOX_API_URL}/api/v1/placements/{placement_uuid}"
            req = urllib.request.Request(url, method="DELETE")
        else:
            url = f"{SANDBOX_API_URL}/api/v1/placements/{placement_uuid}/action"
            data = json.dumps({"action": action}).encode()
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="PUT")

        resp = urllib.request.urlopen(req, timeout=30, context=ctx)
        return {"success": True, "status_code": resp.status, "response": resp.read().decode()}
    except urllib.error.HTTPError as e:
        return {"success": e.code < 500, "status_code": e.code, "error": e.read().decode()[:500]}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_anarchy_state(namespace: str, kubeconfig: str = "") -> Optional[str]:
    """Get the current state of an AnarchySubject in a namespace."""
    import subprocess
    cmd = ["oc", "get", "anarchysubject", "-n", namespace, "-o", "jsonpath={.items[0].spec.vars.current_state}"]
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=env)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None
    except Exception:
        return None


def execute_rhdp_action(action_type: str, target: str, parameters: Dict[str, Any], kubeconfig: str = "") -> Dict[str, Any]:
    """Route an RHDP remediation action to the correct API."""
    command = parameters.get("command", "")

    if command.startswith("anarchy:retry:"):
        subject = command.split(":", 2)[2]
        return retry_provision(subject, kubeconfig=kubeconfig)

    elif command.startswith("anarchy:destroy:"):
        subject = command.split(":", 2)[2]
        return destroy_gracefully(subject, kubeconfig=kubeconfig)

    elif command.startswith("sandbox-api:delete:"):
        uuid = command.split(":", 2)[2]
        return sandbox_api_action(uuid, action="delete")

    elif command.startswith("poolboy:scale:"):
        parts = command.split(":")
        pool = parts[2] if len(parts) > 2 else target
        min_avail = int(parts[3]) if len(parts) > 3 else 5
        return request_pool_scaling(pool, min_avail, kubeconfig=kubeconfig)

    else:
        logger.warning(f"Unknown RHDP action: {command}")
        return {"success": False, "error": f"Unknown RHDP action: {command}"}
