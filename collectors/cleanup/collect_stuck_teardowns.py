"""Stuck teardown detector — finds AnarchySubjects stuck in destroying state.

Read-only. Checks AnarchySubject CRDs for subjects that have been
in 'destroying' or 'destroy-failed' state for longer than a threshold.
"""

import logging
import os
import subprocess
import json
import time
from datetime import datetime, timezone
from typing import Dict, List

logger = logging.getLogger("stargate.stuck_teardowns")

STUCK_THRESHOLD_HOURS = 2


def detect_stuck_teardowns(kubeconfig: str = "", anarchy_namespace: str = "babylon-anarchy-events") -> Dict:
    """Find AnarchySubjects stuck in destroying state.

    Returns list of stuck subjects with namespace, state, age.
    """
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig

    try:
        r = subprocess.run(
            ["oc", "get", "anarchysubjects", "-n", anarchy_namespace, "-o", "json"],
            capture_output=True, text=True, timeout=30, env=env,
        )
        if r.returncode != 0:
            return {"error": r.stderr.strip()[:200], "stuck": []}

        data = json.loads(r.stdout)
        items = data.get("items", [])
    except Exception as e:
        return {"error": str(e), "stuck": []}

    stuck = []
    now = datetime.now(timezone.utc)

    for item in items:
        metadata = item.get("metadata", {})
        status = item.get("status", {})
        spec = item.get("spec", {})
        spec_vars = spec.get("vars", {})

        state = (
            status.get("state")
            or spec_vars.get("current_state")
            or "unknown"
        )

        if state not in ("destroying", "destroy-failed", "destroy-error"):
            continue

        # Calculate age
        created = metadata.get("creationTimestamp", "")
        last_transition = status.get("lastTransitionTime", created)
        try:
            ts = datetime.fromisoformat(last_transition.replace("Z", "+00:00"))
            age_hours = (now - ts).total_seconds() / 3600
        except Exception:
            age_hours = 0

        if age_hours >= STUCK_THRESHOLD_HOURS:
            name = metadata.get("name", "unknown")
            namespace = spec_vars.get("job_vars", {}).get("namespace", name)
            cluster = spec_vars.get("job_vars", {}).get("cluster_name", "unknown")
            stuck.append({
                "anarchy_subject": name,
                "namespace": namespace,
                "state": state,
                "age_hours": round(age_hours, 1),
                "cluster": cluster,
            })

    # Check whether stuck namespaces still exist on the target cluster
    if stuck:
        _check_namespace_existence(stuck, env)

    return {
        "total_subjects": len(items),
        "stuck": stuck,
        "stuck_count": len(stuck),
        "threshold_hours": STUCK_THRESHOLD_HOURS,
    }


def _check_namespace_existence(stuck_entries: List[Dict], env: Dict) -> None:
    """Add namespace_exists boolean to each stuck entry by querying the cluster."""
    clusters_checked: Dict[str, set] = {}
    for entry in stuck_entries:
        cluster = entry.get("cluster", "")
        if cluster not in clusters_checked:
            try:
                r = subprocess.run(
                    ["oc", "get", "namespaces", "-o", "jsonpath={.items[*].metadata.name}"],
                    capture_output=True, text=True, timeout=15, env=env,
                )
                clusters_checked[cluster] = set(r.stdout.strip().split()) if r.returncode == 0 else set()
            except Exception:
                clusters_checked[cluster] = set()

        entry["namespace_exists"] = entry["namespace"] in clusters_checked[cluster]
