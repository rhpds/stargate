"""Provisioning intelligence API — cluster capacity, placement scoring, and forecasting.

Called by Launchpad/DeepField to decide WHERE and WHEN to provision workloads.
All data sourced from existing scanner cache, Babylon pool data, and evaluation history.
"""

import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from db.database import get_db
from api.routers._shared import (
    _load_latest_scan,
    _load_latest_babylon,
    _scan_to_worker_format,
    require_admin,
)

router = APIRouter(prefix="/api/v1")


@router.get("/clusters/capacity")
def cluster_capacity():
    """Per-cluster capacity data for placement decisions.

    Returns CPU utilization, VM density, sandbox health, and pool availability
    for each scanned cluster. Launchpad uses this to choose the best cluster
    for a new lab session.
    """
    scans = _load_latest_scan()
    babylon = _load_latest_babylon()
    pools = babylon.get("pools", {})
    all_pools = pools.get("all_pools", pools.get("summit_pools", []))

    clusters = []
    for s in scans:
        name = s.get("cluster", "")
        avg_cpu = s.get("avg_cpu_pct", 0) or 0
        vms_per_node = s.get("vms_per_node", 0) or 0
        sandbox_active = s.get("sandbox_active", 0) or 0
        sandbox_failing = s.get("sandbox_failing", 0) or 0
        health_rate = s.get("health_rate", 0) or 0

        cluster_pools = [p for p in all_pools if name in p.get("name", "")]
        pool_available = sum(p.get("available", 0) for p in cluster_pools)
        pool_total = sum(p.get("min", 0) for p in cluster_pools)

        score = _compute_placement_score(
            avg_cpu=avg_cpu,
            vms_per_node=vms_per_node,
            health_rate=health_rate,
            pool_available=pool_available,
            sandbox_active=sandbox_active,
        )

        clusters.append({
            "cluster": name,
            "score": score,
            "cpu_pct": avg_cpu,
            "vms_per_node": vms_per_node,
            "sandbox_active": sandbox_active,
            "sandbox_failing": sandbox_failing,
            "health_rate": health_rate,
            "pool_available": pool_available,
            "pool_total": pool_total,
            "status": s.get("status", "unknown"),
            "hot_nodes": s.get("hot_nodes", 0),
        })

    clusters.sort(key=lambda c: -c["score"])
    return {"clusters": clusters, "total": len(clusters)}


@router.get("/clusters/{name}/score")
def cluster_score(name: str):
    """Detailed placement suitability score for a specific cluster."""
    scans = _load_latest_scan()
    cluster_scan = next((s for s in scans if s.get("cluster") == name), None)
    if not cluster_scan:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Cluster '{name}' not found in scanner data")

    avg_cpu = cluster_scan.get("avg_cpu_pct", 0) or 0
    vms_per_node = cluster_scan.get("vms_per_node", 0) or 0
    health_rate = cluster_scan.get("health_rate", 0) or 0
    sandbox_active = cluster_scan.get("sandbox_active", 0) or 0

    babylon = _load_latest_babylon()
    all_pools = babylon.get("pools", {}).get("all_pools", babylon.get("pools", {}).get("summit_pools", []))
    cluster_pools = [p for p in all_pools if name in p.get("name", "")]
    pool_available = sum(p.get("available", 0) for p in cluster_pools)

    score = _compute_placement_score(
        avg_cpu=avg_cpu,
        vms_per_node=vms_per_node,
        health_rate=health_rate,
        pool_available=pool_available,
        sandbox_active=sandbox_active,
    )

    return {
        "cluster": name,
        "score": score,
        "breakdown": {
            "cpu_score": max(0, 100 - avg_cpu),
            "density_score": max(0, 100 - vms_per_node),
            "health_score": health_rate,
            "capacity_score": min(pool_available * 10, 100),
        },
        "raw": {
            "cpu_pct": avg_cpu,
            "vms_per_node": vms_per_node,
            "health_rate": health_rate,
            "pool_available": pool_available,
            "sandbox_active": sandbox_active,
            "hot_nodes": cluster_scan.get("hot_nodes", 0),
            "status": cluster_scan.get("status", "unknown"),
        },
    }


@router.get("/pools/availability")
def pool_availability():
    """Pool handle availability across all clusters."""
    babylon = _load_latest_babylon()
    pools_data = babylon.get("pools", {})
    all_pools = pools_data.get("all_pools", pools_data.get("summit_pools", []))
    exhausted = pools_data.get("exhausted", [])
    low = pools_data.get("low", [])

    exhausted_names = {p.get("name") for p in exhausted if isinstance(p, dict)}
    low_names = {p.get("name") for p in low if isinstance(p, dict)}

    result = []
    for p in all_pools:
        name = p.get("name", "")
        available = p.get("available", 0)
        ready = p.get("ready", 0)
        min_req = p.get("min", 0)

        if name in exhausted_names:
            status = "exhausted"
        elif name in low_names:
            status = "low"
        else:
            status = "healthy"

        result.append({
            "name": name,
            "available": available,
            "ready": ready,
            "min": min_req,
            "status": status,
        })

    total_available = sum(p["available"] for p in result)
    total_exhausted = sum(1 for p in result if p["status"] == "exhausted")

    return {
        "pools": result,
        "total_pools": len(result),
        "total_available": total_available,
        "total_exhausted": total_exhausted,
        "platform_status": pools_data.get("status", "unknown"),
    }


@router.get("/forecast")
def capacity_forecast(hours: int = Query(default=7, le=48)):
    """Capacity forecast for the next N hours based on cluster utilization trends."""
    scans = _load_latest_scan()
    babylon = _load_latest_babylon()
    all_pools = babylon.get("pools", {}).get("all_pools", babylon.get("pools", {}).get("summit_pools", []))

    total_pool_available = sum(p.get("available", 0) for p in all_pools)

    cluster_projections = []
    for s in scans:
        r = _scan_to_worker_format(s)
        n = r["nodes"]
        p = r["pods"]
        avg_cpu = n.get("avg_cpu", 0)

        cluster_projections.append({
            "cluster": r["cluster"],
            "current_cpu": avg_cpu,
            "current_vms": p.get("total_vms", 0),
            "current_sandboxes": p.get("sandbox_active", 0),
            "capacity_warning": avg_cpu > 60 or p.get("vms_per_node", 0) > 80,
        })

    return {
        "pools_available": total_pool_available,
        "cluster_projections": cluster_projections,
        "risk": "high" if total_pool_available < 5 else "medium" if total_pool_available < 20 else "low",
    }


@router.get("/health/summary")
def health_summary():
    """Quick per-cluster health check for placement gating.

    Returns a simple pass/fail/warn per cluster that Launchpad can use
    to gate provisioning decisions.
    """
    scans = _load_latest_scan()
    clusters = {}
    for s in scans:
        name = s.get("cluster", "")
        clusters[name] = {
            "status": s.get("status", "unknown"),
            "healthy": s.get("status") == "healthy",
            "cpu_pct": s.get("avg_cpu_pct", 0),
            "health_rate": s.get("health_rate", 0),
            "sandbox_failing": s.get("sandbox_failing", 0),
        }

    healthy_count = sum(1 for c in clusters.values() if c["healthy"])
    return {
        "clusters": clusters,
        "total": len(clusters),
        "healthy": healthy_count,
        "degraded": len(clusters) - healthy_count,
        "platform_healthy": healthy_count >= len(clusters) * 0.7,
    }


def _compute_placement_score(
    avg_cpu: float,
    vms_per_node: float,
    health_rate: float,
    pool_available: int,
    sandbox_active: int,
) -> float:
    """Compute a 0-100 placement suitability score.

    Higher = more suitable for new workloads.
    Weights: CPU(30%) + density(20%) + health(30%) + capacity(20%)
    """
    cpu_score = max(0, 100 - avg_cpu)
    density_score = max(0, 100 - vms_per_node)
    health_score = health_rate
    capacity_score = min(pool_available * 10, 100)

    return round(
        cpu_score * 0.30 +
        density_score * 0.20 +
        health_score * 0.30 +
        capacity_score * 0.20,
        1,
    )
