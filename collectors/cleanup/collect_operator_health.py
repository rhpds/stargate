"""Operator health collector — checks critical operator pod status.

Read-only. Checks pods in key operator namespaces for CrashLoopBackOff,
not-ready, or excessive restarts.
"""

import logging
import os
import subprocess
import json
from datetime import datetime, timezone
from typing import Dict, List

logger = logging.getLogger("stargate.operator_health")

OPERATOR_NAMESPACES = [
    "openshift-cnv",
    "openshift-virtualization",
    "openshift-storage",
    "openshift-operators",
]

ANARCHY_NS_PREFIX = "babylon-anarchy"

RESTART_THRESHOLD = 5


def detect_operator_issues(kubeconfig: str = "") -> Dict:
    """Find unhealthy operator pods across key namespaces."""
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig

    unhealthy = []

    namespaces = list(OPERATOR_NAMESPACES)
    try:
        r = subprocess.run(
            ["oc", "get", "namespaces", "-o", "jsonpath={.items[*].metadata.name}"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        if r.returncode == 0:
            for ns in r.stdout.strip().split():
                if ns.startswith(ANARCHY_NS_PREFIX) and ns not in namespaces:
                    namespaces.append(ns)
    except Exception:
        pass

    total_pods = 0

    for ns in namespaces:
        try:
            r = subprocess.run(
                ["oc", "get", "pods", "-n", ns, "-o", "json"],
                capture_output=True, text=True, timeout=15, env=env,
            )
            if r.returncode != 0:
                continue

            pods = json.loads(r.stdout).get("items", [])
            total_pods += len(pods)

            for pod in pods:
                metadata = pod.get("metadata", {})
                pod_name = metadata.get("name", "")
                status = pod.get("status", {})
                phase = status.get("phase", "")

                issues = []
                total_restarts = 0

                for cs in status.get("containerStatuses", []):
                    restarts = cs.get("restartCount", 0)
                    total_restarts += restarts
                    ready = cs.get("ready", False)

                    waiting = cs.get("state", {}).get("waiting", {})
                    reason = waiting.get("reason", "")

                    if reason == "CrashLoopBackOff":
                        issues.append(f"CrashLoopBackOff ({restarts} restarts)")
                    elif reason == "ImagePullBackOff":
                        issues.append("ImagePullBackOff")
                    elif not ready and phase == "Running":
                        issues.append(f"not ready ({restarts} restarts)")

                if total_restarts >= RESTART_THRESHOLD and not issues:
                    issues.append(f"{total_restarts} restarts")

                if issues:
                    unhealthy.append({
                        "pod": pod_name,
                        "namespace": ns,
                        "phase": phase,
                        "restarts": total_restarts,
                        "issues": issues,
                        "since": status.get("startTime", ""),
                    })

        except Exception as e:
            logger.debug("Error checking %s: %s", ns, e)

    return {
        "namespaces_checked": namespaces,
        "total_pods": total_pods,
        "unhealthy": unhealthy,
        "unhealthy_count": len(unhealthy),
    }
