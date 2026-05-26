"""Cluster health collector — parse cluster-scheduler evaluate response into evidence.

Read-only. No mutation. No write verbs.
Works with pre-collected evaluation results (fixture JSON or live API response).
"""

from __future__ import annotations

from typing import Dict

from collectors.openshift.collect_resource_state import CollectedEvidence

CPU_THRESHOLD_PCT = 90
MEMORY_THRESHOLD_PCT = 90


def collect_cluster_health(data: Dict) -> CollectedEvidence:
    """Parse cluster-scheduler /evaluate response into normalized evidence."""
    metadata = data.get("metadata", {})
    metrics = data.get("metrics", {})

    cpu_usage = metrics.get("cpu_usage_pct", 100)
    memory_usage = metrics.get("memory_usage_pct", 100)
    critical_alerts = metrics.get("critical_alerts", 0)
    unhealthy_nodes = metrics.get("unhealthy_nodes", 0)

    return CollectedEvidence(
        resource_kind="ClusterHealth",
        resource_name=metadata.get("name", "unknown"),
        namespace="cluster",
        observed={
            "cluster_reachable": True,
            "health_score": metrics.get("health_score", 0),
            "cpu_usage_acceptable": cpu_usage < CPU_THRESHOLD_PCT,
            "memory_usage_acceptable": memory_usage < MEMORY_THRESHOLD_PCT,
            "no_critical_alerts": critical_alerts == 0,
            "nodes_healthy": unhealthy_nodes == 0,
        },
    )
