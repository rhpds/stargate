"""Mock cluster — in-memory Kubernetes state for command validation.

Simulates oc command execution without a real cluster. Tracks state changes,
validates command syntax, and produces an audit trail.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger("stargate.mock_cluster")

FORBIDDEN_NAMESPACES = ["openshift-*", "kube-system", "kube-public"]


class MockCluster:

    def __init__(self):
        self._state: Dict[str, Dict] = {}
        self.history: List[Dict] = []

    def get_state(self, namespace: str) -> Dict:
        if namespace not in self._state:
            self._state[namespace] = {"deployments": {}, "pods": {}, "services": {}}
        return self._state[namespace]

    def reset(self):
        self._state.clear()
        self.history.clear()

    def execute(self, command: str) -> Dict:
        ts = datetime.now(timezone.utc).isoformat()
        result = self._execute_inner(command)
        self.history.append({
            "command": command,
            "success": result["success"],
            "timestamp": ts,
            "result": result.get("message", ""),
        })
        return result

    def _execute_inner(self, command: str) -> Dict:
        parts = command.split()
        if not parts or parts[0] != "oc":
            return {"success": False, "error": "Command must start with 'oc'"}

        ns = self._extract_namespace(parts)
        if ns and self._is_forbidden(ns):
            return {"success": False, "error": f"Forbidden namespace: {ns}"}

        verb = parts[1] if len(parts) > 1 else ""

        if verb == "create" and len(parts) > 2 and parts[2] == "deployment":
            return self._create_deployment(parts, ns)
        elif verb == "scale":
            return self._scale(parts, ns)
        elif verb == "delete" and len(parts) > 2 and parts[2] == "pod":
            return self._delete_pod(parts, ns)
        elif verb == "rollout" and len(parts) > 2 and parts[2] == "restart":
            return self._rollout_restart(parts, ns)
        elif verb == "patch":
            return self._patch(parts, ns)
        elif verb == "apply":
            return self._apply(parts, ns)
        else:
            return {"success": False, "error": f"Unknown command verb: {verb}"}

    def _create_deployment(self, parts: List[str], ns: str) -> Dict:
        name = parts[3] if len(parts) > 3 else "unknown"
        if name.startswith("--"):
            return {"success": False, "error": "Missing deployment name"}

        image = "unknown"
        for p in parts:
            if p.startswith("--image="):
                image = p.split("=", 1)[1]

        ns = ns or "default"
        state = self.get_state(ns)
        state["deployments"][name] = {"image": image, "replicas": 1, "ready": True}
        return {"success": True, "message": f"deployment.apps/{name} created"}

    def _scale(self, parts: List[str], ns: str) -> Dict:
        target = None
        replicas = 1
        for p in parts:
            if "/" in p and not p.startswith("--"):
                target = p
            if p.startswith("--replicas="):
                replicas = int(p.split("=")[1])

        if not target:
            return {"success": False, "error": "Missing scale target"}

        kind, name = target.split("/", 1) if "/" in target else ("deployment", target)
        ns = ns or "default"
        state = self.get_state(ns)
        if name in state.get("deployments", {}):
            state["deployments"][name]["replicas"] = replicas
        else:
            state.setdefault("deployments", {})[name] = {"replicas": replicas, "ready": True}
        return {"success": True, "message": f"{target} scaled to {replicas}"}

    def _delete_pod(self, parts: List[str], ns: str) -> Dict:
        pod_name = parts[3] if len(parts) > 3 else "unknown"
        ns = ns or "default"
        state = self.get_state(ns)
        state["pods"].pop(pod_name, None)
        return {"success": True, "message": f"pod \"{pod_name}\" deleted"}

    def _rollout_restart(self, parts: List[str], ns: str) -> Dict:
        target = None
        for p in parts[3:]:
            if "/" in p and not p.startswith("--"):
                target = p
                break
        if not target:
            return {"success": False, "error": "Missing rollout target"}

        ns = ns or "default"
        state = self.get_state(ns)
        kind, name = target.split("/", 1)
        if name in state.get("deployments", {}):
            state["deployments"][name]["restarted"] = True
        return {"success": True, "message": f"{target} restarted"}

    def _patch(self, parts: List[str], ns: str) -> Dict:
        if len(parts) < 3:
            return {"success": False, "error": "Missing patch target"}
        resource_type = parts[2]
        resource_name = parts[3] if len(parts) > 3 and not parts[3].startswith("-") else "unknown"
        ns = ns or "default"
        self.get_state(ns)
        return {"success": True, "message": f"{resource_type}/{resource_name} patched"}

    def _apply(self, parts: List[str], ns: str) -> Dict:
        ns = ns or "default"
        self.get_state(ns)
        return {"success": True, "message": "resources applied"}

    def _extract_namespace(self, parts: List[str]) -> str:
        for i, p in enumerate(parts):
            if p == "-n" and i + 1 < len(parts):
                return parts[i + 1]
        return ""

    def _is_forbidden(self, namespace: str) -> bool:
        for pattern in FORBIDDEN_NAMESPACES:
            if fnmatch.fnmatch(namespace, pattern):
                return True
        return False
