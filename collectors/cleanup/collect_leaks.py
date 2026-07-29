"""Resource leak detector — finds orphaned PVs and PVCs.

Read-only. Checks for PVs bound to namespaces that no longer exist.
"""

import logging
import os
import subprocess
import json
from typing import Dict, List

logger = logging.getLogger("stargate.resource_leaks")


def detect_resource_leaks(kubeconfig: str = "") -> Dict:
    """Find orphaned PVs bound to deleted namespaces."""
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig

    orphaned_pvs = []

    try:
        # Get all PVs
        r = subprocess.run(
            ["oc", "get", "pv", "-o", "json"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if r.returncode != 0:
            return {"error": r.stderr.strip()[:200], "orphaned_pvs": []}

        pvs = json.loads(r.stdout).get("items", [])

        # Get existing namespaces
        r2 = subprocess.run(
            ["oc", "get", "namespaces", "-o", "jsonpath={.items[*].metadata.name}"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        existing_ns = set(r2.stdout.strip().split()) if r2.returncode == 0 else set()

        for pv in pvs:
            status = pv.get("status", {}).get("phase", "")
            claim_ref = pv.get("spec", {}).get("claimRef", {})
            claim_ns = claim_ref.get("namespace", "")

            if not claim_ns:
                continue

            # Check if the namespace still exists
            if claim_ns not in existing_ns and status in ("Bound", "Released"):
                name = pv.get("metadata", {}).get("name", "unknown")
                capacity = pv.get("spec", {}).get("capacity", {}).get("storage", "?")
                orphaned_pvs.append({
                    "pv_name": name,
                    "bound_to_namespace": claim_ns,
                    "bound_to_pvc": claim_ref.get("name", "?"),
                    "status": status,
                    "capacity": capacity,
                    "storage_class": pv.get("spec", {}).get("storageClassName", "?"),
                })

    except Exception as e:
        return {"error": str(e), "orphaned_pvs": []}

    total_capacity = sum(
        int(p["capacity"].replace("Gi", "")) for p in orphaned_pvs
        if p["capacity"].endswith("Gi")
    ) if orphaned_pvs else 0

    return {
        "total_pvs": len(pvs) if 'pvs' in dir() else 0,
        "orphaned_pvs": orphaned_pvs,
        "orphaned_count": len(orphaned_pvs),
        "orphaned_capacity_gi": total_capacity,
    }
