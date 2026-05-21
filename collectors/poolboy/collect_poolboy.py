"""Poolboy collectors — ResourcePool capacity and ResourceHandle health.

Read-only. No mutation. No write verbs.
"""

from __future__ import annotations

from typing import Any, Dict, List

from collectors.openshift.collect_resource_state import CollectedEvidence


def collect_resource_pool(data: Dict) -> CollectedEvidence:
    """Parse ResourcePool CRD JSON into evidence."""
    metadata = data.get("metadata", {})
    spec = data.get("spec", {})
    status = data.get("status", {})

    min_available = spec.get("minAvailable", 0)

    handle_count = status.get("resourceHandleCount", {})
    if isinstance(handle_count, dict):
        available = handle_count.get("available", 0)
        ready = handle_count.get("ready", 0)
    else:
        available = handle_count or 0
        ready = 0

    handles = status.get("resourceHandles", [])
    healthy_handles = sum(1 for h in handles if h.get("healthy"))
    ready_handles = sum(1 for h in handles if h.get("ready"))

    return CollectedEvidence(
        resource_kind="ResourcePool",
        resource_name=metadata.get("name", "unknown"),
        namespace=metadata.get("namespace", "poolboy"),
        observed={
            "pool_exists": True,
            "min_available": min_available,
            "total_handles": available,
            "ready_handles": ready_handles,
            "healthy_handles": healthy_handles,
            "pool_exhausted": available == 0 and min_available > 0,
            "pool_low": available <= 1 and min_available > 0,
            "handle_details": [
                {"name": h.get("name"), "healthy": h.get("healthy"), "ready": h.get("ready")}
                for h in handles[:10]
            ],
        },
    )


def collect_resource_handle(data: Dict) -> CollectedEvidence:
    """Parse ResourceHandle CRD JSON into evidence."""
    metadata = data.get("metadata", {})
    spec = data.get("spec", {})

    claim_ref = spec.get("resourceClaim", {})
    provider_ref = spec.get("provider", {})

    resources = spec.get("resources", [])
    resource_providers = [r.get("provider", {}).get("name", "") for r in resources]

    return CollectedEvidence(
        resource_kind="ResourceHandle",
        resource_name=metadata.get("name", "unknown"),
        namespace=metadata.get("namespace", "poolboy"),
        observed={
            "handle_exists": True,
            "claim_name": claim_ref.get("name"),
            "claim_namespace": claim_ref.get("namespace"),
            "provider_name": provider_ref.get("name"),
            "resource_providers": resource_providers,
        },
    )


def collect_resource_claim(data: Dict) -> CollectedEvidence:
    """Parse ResourceClaim CRD JSON into evidence."""
    metadata = data.get("metadata", {})
    spec = data.get("spec", {})
    status = data.get("status", {})

    provider = spec.get("provider", {})
    resources = status.get("resources", [])

    resource_states = []
    for r in resources[:5]:
        state = r.get("state", {})
        state_spec = state.get("spec", {})
        state_vars = state_spec.get("vars", {})
        resource_states.append({
            "name": state.get("name"),
            "current_state": state_vars.get("current_state"),
            "desired_state": state_vars.get("desired_state"),
        })

    labels = metadata.get("labels", {})

    return CollectedEvidence(
        resource_kind="ResourceClaim",
        resource_name=metadata.get("name", "unknown"),
        namespace=metadata.get("namespace", "unknown"),
        observed={
            "claim_exists": True,
            "provider_name": provider.get("name"),
            "resource_count": len(resources),
            "resource_states": resource_states,
            "catalog_item": labels.get("babylon.gpte.redhat.com/catalogItemName", ""),
        },
    )


def summarize_pools(pools: List[Dict]) -> Dict[str, Any]:
    """Summarize all ResourcePools into aggregate capacity data."""
    total = len(pools)
    exhausted = 0
    low = 0
    healthy = 0

    for p in pools:
        ev = collect_resource_pool(p)
        obs = ev.observed
        if obs.get("pool_exhausted"):
            exhausted += 1
        elif obs.get("pool_low"):
            low += 1
        else:
            healthy += 1

    return {
        "total_pools": total,
        "exhausted": exhausted,
        "low": low,
        "healthy": healthy,
        "capacity_status": "critical" if exhausted > 0 else "warning" if low > total * 0.3 else "healthy",
    }
