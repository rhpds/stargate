"""Stuck teardown detector — finds AnarchySubjects stuck in destroying state.

Read-only. Checks AnarchySubject CRDs for subjects that have been
in 'destroying' or 'destroy-failed' state for longer than a threshold.

Age is measured from when teardown was requested (metadata.deletionTimestamp),
falling back to the last state transition, then creation. Measuring from
creation overstates the wait by the environment's whole lifetime — a subject
created 58 days ago and deleted 20 days ago is stuck for 20 days, not 58.

'destroy-pending' is a queue, not a failure: it is reported separately so a
slow queue is never counted as a broken teardown.
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


def _identity(spec_vars: Dict, subject_name: str) -> tuple:
    """Resolve a subject's lab namespace and target cluster.

    ``job_vars.namespace`` / ``job_vars.cluster_name`` were the only keys
    read. Neither exists on the live control plane: of 2,692 AnarchySubjects
    on the Babylon cluster, ``namespace`` and ``cluster_name`` are present on
    zero. The real keys are ``sandbox_openshift_namespace`` (1,305) and
    ``sandbox_openshift_cluster`` (1,002).

    That mattered because ``cluster`` = "unknown" silently disabled the
    namespace-existence check — it returns early on an unknown cluster — so
    the detector could never say whether a stuck teardown still held any
    resources. Measured before the fix: 98 stuck subjects, 98 with cluster
    "unknown", 0 with an observed ``namespace_exists``.

    The fallback is not a cure-all: many stuck subjects are GPTE sandboxes
    and AWS account pools that do not record a cluster at all (57 of the 98
    were ``sandboxes-gpte``). Those stay "unknown", which is honest, and
    ``namespace_exists`` stays None. ``unattributable_count`` exists so the
    alarm can say so instead of implying every row is a remediable lab.
    """
    job_vars = (spec_vars or {}).get("job_vars") or {}
    namespace = (
        job_vars.get("namespace")
        or job_vars.get("sandbox_openshift_namespace")
        or subject_name
    )
    cluster = job_vars.get("cluster_name") or job_vars.get("sandbox_openshift_cluster")
    return namespace, cluster or "unknown"


def detect_stuck_teardowns(kubeconfig: str = "", anarchy_namespaces: str = None) -> Dict:
    # NOTE: the -A query over ~2,600 AnarchySubjects takes >30s on the
    # Babylon control-plane — the old 30s timeout made the live detector
    # PARTIAL on most runs (ages lost, snapshot-only rows). 90s: it runs
    # in the monitoring-gaps background thread, so nothing blocks on it.
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
                capture_output=True, text=True, timeout=90, env=env,
            )
            if r.returncode != 0:
                query_error = (query_error or "") + f"{target}: {r.stderr.strip()[:150]}; "
                continue
            items.extend(json.loads(r.stdout).get("items", []))
        except Exception as e:
            query_error = (query_error or "") + f"{target}: {e}; "

    stuck = []
    pending_ages = []
    now = datetime.now(timezone.utc)

    def _hours_since(ts: str) -> Optional[float]:
        if not ts:
            return None
        try:
            parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None
        return (now - parsed).total_seconds() / 3600

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

        created = metadata.get("creationTimestamp", "")
        deleted = metadata.get("deletionTimestamp", "")
        last_transition = status.get("lastTransitionTime", "")

        # destroy-pending is a queue, not a failure. Report it separately so a
        # slow queue is never confused with a broken teardown.
        if state == "destroy-pending":
            pending_age = _hours_since(deleted)
            if pending_age is None:
                pending_age = _hours_since(created)
            if pending_age is not None:
                pending_ages.append(pending_age)
            continue

        if state not in ("destroying", "destroy-failed", "destroy-error"):
            continue

        # Age from the delete request when one exists: creation time includes
        # the environment's whole life, which is not time spent stuck.
        if deleted:
            age_basis = "deletionTimestamp"
            age_hours = _hours_since(deleted)
        elif last_transition:
            age_basis = "lastTransitionTime"
            age_hours = _hours_since(last_transition)
        else:
            age_basis = "creationTimestamp"
            age_hours = _hours_since(created)
        if age_hours is None:
            age_hours = 0

        if age_hours >= STUCK_THRESHOLD_HOURS:
            name = metadata.get("name", "unknown")
            namespace, cluster = _identity(spec_vars, name)
            created_hours = _hours_since(created)
            stuck.append({
                "anarchy_subject": name,
                "namespace": namespace,
                "state": state,
                "age_hours": round(age_hours, 1),
                "age_basis": age_basis,
                "created_hours": round(created_hours, 1) if created_hours is not None else None,
                "cluster": cluster,
            })

    # Check whether stuck namespaces still exist on their TARGET cluster
    if stuck:
        _check_namespace_existence(stuck, env, kubeconfig)

    result = {
        "total_subjects": len(items),
        "stuck": stuck,
        "stuck_count": len(stuck),
        # A stuck subject we cannot place on a cluster is still stuck, but it
        # is not necessarily something StarGate can remediate — split them out
        # so the headline number is not read as "98 broken lab teardowns".
        "attributable_count": sum(
            1 for s in stuck if s.get("cluster") and s["cluster"] != "unknown"
        ),
        "unattributable_count": sum(
            1 for s in stuck if not s.get("cluster") or s["cluster"] == "unknown"
        ),
        "threshold_hours": STUCK_THRESHOLD_HOURS,
        "pending": {
            "count": len(pending_ages),
            "oldest_hours": round(max(pending_ages), 1) if pending_ages else 0,
            "over_24h": sum(1 for h in pending_ages if h > 24),
            "over_7d": sum(1 for h in pending_ages if h > 168),
        },
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
