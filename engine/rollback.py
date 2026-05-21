"""Rollback engine — capture, restore, and verify namespace state.

Captures the state of a namespace before an action, and restores it
if the action fails or verification doesn't pass.
"""

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("stargate.rollback")


def _run_oc(args: List[str], kubeconfig: str, timeout: int = 30) -> str:
    """Run an oc command with the given kubeconfig."""
    cmd = ["oc"] + args
    env = {**os.environ, "KUBECONFIG": kubeconfig}
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    if result.returncode != 0 and "not found" not in result.stderr.lower() and "no resources" not in result.stderr.lower():
        if "cannot" in result.stderr.lower() or "forbidden" in result.stderr.lower():
            return result.stderr.strip()
        if result.stderr.strip():
            logger.warning(f"oc {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip() or result.stderr.strip()


def capture_state(namespace: str, kubeconfig: str) -> Dict[str, Any]:
    """Snapshot current state of a namespace."""
    snapshot = {
        "namespace": namespace,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "deployments": [],
        "pods": [],
        "services": [],
    }

    for kind in ["deployments", "services"]:
        try:
            result = _run_oc(["get", kind, "-n", namespace, "-o", "json"], kubeconfig)
            if result and result.startswith("{"):
                data = json.loads(result)
                items = data.get("items", [])
                for item in items:
                    meta = item.get("metadata", {})
                    for key in ["managedFields", "resourceVersion", "uid", "creationTimestamp", "generation"]:
                        meta.pop(key, None)
                    item.get("status", {}).clear()
                snapshot[kind] = items
        except Exception as e:
            logger.warning(f"Failed to capture {kind}: {e}")

    try:
        result = _run_oc(["get", "pods", "-n", namespace, "-o", "json"], kubeconfig)
        if result and result.startswith("{"):
            data = json.loads(result)
            snapshot["pods"] = [
                {"name": p["metadata"]["name"], "phase": p.get("status", {}).get("phase", "Unknown")}
                for p in data.get("items", [])
            ]
    except Exception:
        pass

    return snapshot


def restore_state(snapshot: Dict[str, Any], namespace: str, kubeconfig: str) -> Dict[str, Any]:
    """Restore namespace to a previous state snapshot."""
    restored = 0
    deleted = 0
    errors = []

    for kind in ["deployments", "services"]:
        for resource in snapshot.get(kind, []):
            try:
                resource_json = json.dumps(resource)
                result = subprocess.run(
                    ["oc", "apply", "-f", "-", "-n", namespace],
                    input=resource_json,
                    capture_output=True, text=True, timeout=30,
                    env={**os.environ, "KUBECONFIG": kubeconfig},
                )
                if result.returncode == 0:
                    restored += 1
                else:
                    errors.append(f"Failed to restore {kind}/{resource.get('metadata', {}).get('name')}: {result.stderr}")
            except Exception as e:
                errors.append(str(e))

    return {"restored": restored, "deleted": deleted, "errors": errors}


def verify_restore(snapshot: Dict[str, Any], namespace: str, kubeconfig: str) -> bool:
    """Verify current state matches snapshot."""
    current = capture_state(namespace, kubeconfig)

    for kind in ["deployments", "services"]:
        snapshot_names = {r.get("metadata", {}).get("name") for r in snapshot.get(kind, [])}
        current_names = {r.get("metadata", {}).get("name") for r in current.get(kind, [])}
        if snapshot_names != current_names:
            logger.warning(f"{kind} mismatch: expected {snapshot_names}, got {current_names}")
            return False

    return True
