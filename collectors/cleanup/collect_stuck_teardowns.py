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
from typing import Dict, List, Optional

logger = logging.getLogger("stargate.stuck_teardowns")

# Mirrors STARGATE_WORKSHOP_PROVISION_STALL_HOURS configurability.
STUCK_THRESHOLD_HOURS = float(os.environ.get("STARGATE_STUCK_TEARDOWN_HOURS", "2"))


def detect_stuck_teardowns(kubeconfig: str = "", anarchy_namespaces: str = None) -> Dict:
    """Find AnarchySubjects stuck in destroying state.

    Returns list of stuck subjects with namespace, state, age.

    anarchy_namespaces: comma-separated namespaces to query, or "-A" for all
    namespaces. AnarchySubjects live in sharded babylon-anarchy-* namespaces
    on the Babylon control-plane cluster, so "-A" (the default, or
    STARGATE_ANARCHY_NAMESPACES) is usually right.
    """
    namespaces = anarchy_namespaces or os.environ.get("STARGATE_ANARCHY_NAMESPACES", "-A")
    env = {**os.environ}
    if kubeconfig:
        env["KUBECONFIG"] = kubeconfig

    items = []
    query_error = None
    targets = ["-A"] if namespaces.strip() == "-A" else [
        n.strip() for n in namespaces.split(",") if n.strip()
    ]
    for target in targets:
        args = ["oc", "get", "anarchysubjects"]
        args += ["-A"] if target == "-A" else ["-n", target]
        args += ["-o", "json"]
        try:
            r = subprocess.run(
                args,
                capture_output=True, text=True, timeout=30, env=env,
            )
            if r.returncode != 0:
                query_error = (query_error or "") + f"{target}: {r.stderr.strip()[:150]}; "
                continue
            items.extend(json.loads(r.stdout).get("items", []))
        except Exception as e:
            query_error = (query_error or "") + f"{target}: {e}; "

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

    # Check whether stuck namespaces still exist on their TARGET cluster
    if stuck:
        _check_namespace_existence(stuck, env, kubeconfig)

    result = {
        "total_subjects": len(items),
        "stuck": stuck,
        "stuck_count": len(stuck),
        "threshold_hours": STUCK_THRESHOLD_HOURS,
    }
    if query_error:
        # Partial or total query failure: visible, but findings are still
        # findings (a zero here is only healthy when every query succeeded).
        result["error"] = query_error.strip()[:200]
        result["partial"] = True
    return result


def _cluster_kubeconfig(base_kubeconfig: str, cluster: str) -> str:
    """Resolve the per-cluster kubeconfig that sits beside the base one.

    Follows the repo convention (see api/routers/dashboard/remediation.py):
    kubeconfig-{cluster} files live in the same secrets directory as the
    executor kubeconfig.
    """
    if not base_kubeconfig or not cluster:
        return ""
    candidate = os.path.join(os.path.dirname(base_kubeconfig), f"kubeconfig-{cluster}")
    return candidate if os.path.exists(candidate) else ""


def _namespaces_on_cluster(cluster: str, env: Dict, base_kubeconfig: str) -> Optional[set]:
    """List namespaces on the target cluster, or None when unobserved.

    A namespace list from the wrong cluster is worse than no observation:
    when no per-cluster kubeconfig resolves or the query fails, return
    None so callers treat existence as unobserved rather than false.
    """
    if not cluster or cluster == "unknown":
        return None
    kc = _cluster_kubeconfig(base_kubeconfig, cluster)
    if not kc:
        logger.info("namespace existence unobserved: no kubeconfig for cluster=%s", cluster)
        return None
    query_env = {**env, "KUBECONFIG": kc}
    try:
        r = subprocess.run(
            ["oc", "get", "namespaces", "-o", "jsonpath={.items[*].metadata.name}"],
            capture_output=True, text=True, timeout=15, env=query_env,
        )
        if r.returncode != 0:
            logger.warning("namespace query failed for cluster=%s: %s", cluster, r.stderr.strip()[:120])
            return None
        return set(r.stdout.strip().split())
    except Exception as e:
        logger.warning("namespace query error for cluster=%s: %s", cluster, e)
        return None


def _check_namespace_existence(stuck_entries: List[Dict], env: Dict, base_kubeconfig: str = "") -> None:
    """Add namespace_exists to each stuck entry, observed on its target cluster.

    Entries whose target cluster cannot be queried keep namespace_exists
    as None (unobserved) — never a false negative from the wrong cluster.
    """
    observed: Dict[str, Optional[set]] = {}
    for entry in stuck_entries:
        cluster = entry.get("cluster", "")
        if cluster not in observed:
            observed[cluster] = _namespaces_on_cluster(cluster, env, base_kubeconfig)
        namespaces = observed[cluster]
        entry["namespace_exists"] = (
            entry["namespace"] in namespaces if namespaces is not None else None
        )
