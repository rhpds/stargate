"""Resource leak detector — finds orphaned PVs and PVCs.

Read-only. Checks for PVs bound to namespaces that no longer exist,
and PVCs referencing PVs that are gone or in Lost phase.
"""

import logging
import os
import subprocess
import json
from typing import Dict, List, Set

logger = logging.getLogger("stargate.resource_leaks")


def _get_existing_namespaces(env: Dict) -> Set[str]:
    try:
        r = subprocess.run(
            ["oc", "get", "namespaces", "-o", "jsonpath={.items[*].metadata.name}"],
            capture_output=True, text=True, timeout=15, env=env,
        )
        return set(r.stdout.strip().split()) if r.returncode == 0 else set()
    except Exception:
        return set()


def detect_resource_leaks(kubeconfig: str = "") -> Dict:
    """Find orphaned PVs and PVCs."""
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig

    orphaned_pvs = []
    orphaned_pvcs = []
    pvs = []

    try:
        r = subprocess.run(
            ["oc", "get", "pv", "-o", "json"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if r.returncode != 0:
            return {"error": r.stderr.strip()[:200], "orphaned_pvs": [], "orphaned_pvcs": []}

        pvs = json.loads(r.stdout).get("items", [])
        existing_ns = _get_existing_namespaces(env)

        pv_names = {pv.get("metadata", {}).get("name", "") for pv in pvs}
        pv_phases = {
            pv.get("metadata", {}).get("name", ""): pv.get("status", {}).get("phase", "")
            for pv in pvs
        }

        for pv in pvs:
            status = pv.get("status", {}).get("phase", "")
            claim_ref = pv.get("spec", {}).get("claimRef", {})
            claim_ns = claim_ref.get("namespace", "")

            if not claim_ns:
                continue

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

        # Check PVCs across sandbox namespaces for broken volume references
        for ns in existing_ns:
            if not (ns.startswith("sandbox-") or ns.startswith("showroom-")):
                continue
            try:
                r2 = subprocess.run(
                    ["oc", "get", "pvc", "-n", ns, "-o", "json"],
                    capture_output=True, text=True, timeout=10, env=env,
                )
                if r2.returncode != 0:
                    continue

                pvcs = json.loads(r2.stdout).get("items", [])
                for pvc in pvcs:
                    pvc_name = pvc.get("metadata", {}).get("name", "")
                    pvc_phase = pvc.get("status", {}).get("phase", "")
                    volume_name = pvc.get("spec", {}).get("volumeName", "")

                    if pvc_phase == "Lost" or (volume_name and volume_name not in pv_names):
                        orphaned_pvcs.append({
                            "pvc_name": pvc_name,
                            "namespace": ns,
                            "status": pvc_phase,
                            "volume_name": volume_name or "(none)",
                            "volume_exists": volume_name in pv_names,
                            "storage_class": pvc.get("spec", {}).get("storageClassName", "?"),
                        })
            except Exception:
                continue

    except Exception as e:
        return {"error": str(e), "orphaned_pvs": [], "orphaned_pvcs": []}

    total_capacity = sum(
        int(p["capacity"].replace("Gi", "")) for p in orphaned_pvs
        if p["capacity"].endswith("Gi")
    ) if orphaned_pvs else 0

    return {
        "total_pvs": len(pvs),
        "orphaned_pvs": orphaned_pvs,
        "orphaned_count": len(orphaned_pvs),
        "orphaned_capacity_gi": total_capacity,
        "orphaned_pvcs": orphaned_pvcs,
        "orphaned_pvc_count": len(orphaned_pvcs),
    }
