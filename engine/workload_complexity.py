"""Workload complexity scoring — compute deployment complexity from AgnosticV constraints.

Uses already-loaded AgnosticV data (ai_workers_cores, collections, timeout_seconds,
workload_count, worker_instance_count, components) to score how complex a lab is
to provision and how many resources it consumes.
"""

from __future__ import annotations

from typing import Any, Dict


CLOUD_MULTIPLIERS = {
    "cnv": 1.2,
    "aws": 1.0,
    "azure": 1.0,
    "gcp": 1.0,
    "tenant": 0.5,
}

DEFAULT_TIMEOUT_SECONDS = 3600
MAX_TIMEOUT_SECONDS = 14400


def compute_complexity_score(constraints: Dict[str, Any]) -> Dict[str, Any]:
    """Compute a normalized complexity score from AgnosticV lab constraints.

    Returns dict with:
      score: float 0.0-1.0 (normalized complexity)
      components: breakdown of contributing factors
      estimated_provision_minutes: int
      resource_weight: float (relative cluster resource consumption)
    """
    workload_count = _int(constraints.get("workload_count", 0))
    collections = constraints.get("collections", [])
    collections_count = len(collections) if isinstance(collections, list) else 0
    worker_count = _int(constraints.get("worker_instance_count", 0))
    ai_cores = _int(constraints.get("ai_workers_cores", 0))
    timeout = _int(constraints.get("timeout_seconds", 0)) or DEFAULT_TIMEOUT_SECONDS
    components = constraints.get("components", [])
    components_count = len(components) if isinstance(components, list) else 0
    cloud = (constraints.get("cloud_provider") or constraints.get("config") or "").lower()

    workload_score = min(workload_count / 10.0, 1.0) * 0.15
    collection_score = min(collections_count / 8.0, 1.0) * 0.10
    worker_score = min(worker_count / 5.0, 1.0) * 0.20
    ai_score = min(ai_cores / 64.0, 1.0) * 0.15
    timeout_score = min(timeout / MAX_TIMEOUT_SECONDS, 1.0) * 0.20
    component_score = min(components_count / 5.0, 1.0) * 0.10
    base_score = 0.10

    raw_score = base_score + workload_score + collection_score + worker_score + ai_score + timeout_score + component_score

    cloud_mult = CLOUD_MULTIPLIERS.get(cloud, 1.0)
    final_score = min(raw_score * cloud_mult, 1.0)

    est_minutes = int((timeout / 60) * 0.6 + workload_count * 5 + collections_count * 2)

    resource_weight = (
        max(worker_count, 1) * max(ai_cores, 4) / 32.0
    )

    return {
        "score": round(final_score, 3),
        "components": {
            "workloads": workload_count,
            "collections": collections_count,
            "workers": worker_count,
            "ai_cores": ai_cores,
            "timeout_seconds": timeout,
            "components": components_count,
            "cloud": cloud or "unknown",
            "cloud_multiplier": cloud_mult,
        },
        "estimated_provision_minutes": est_minutes,
        "resource_weight": round(resource_weight, 2),
    }


def _int(val) -> int:
    """Safely convert to int, handling string values from AgnosticV."""
    if val is None:
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0
