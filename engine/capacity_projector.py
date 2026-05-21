"""Capacity projector — workload-aware demand/supply projection over time.

Projects per-hour capacity demand (from session schedule + workload complexity)
against supply (pool available + recycling rate) to identify bottleneck pools
and hours where capacity will be exceeded.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


def project_capacity(
    sessions: List[Dict],
    pools: Dict[str, Dict],
    complexities: Dict[str, Dict],
    pool_velocities: Dict[str, Dict],
    hours: int = 6,
) -> Dict[str, Any]:
    """Project capacity demand vs supply over the next N hours.

    Args:
        sessions: list of {lab_code, start_time (ISO), attendees, pool_name}
        pools: {pool_name: {available, min_required, ready}}
        complexities: {lab_slug: {score, estimated_provision_minutes}}
        pool_velocities: {pool_name: {handles_per_hour, recycling_rate}}
        hours: forecast window

    Returns:
        hourly_projections: per-hour demand/supply per pool
        bottleneck_pools: pools that hit zero
        bottleneck_hour: when first pool exhausts
        risk_level: overall risk (low, medium, high, critical)
    """
    now = datetime.now(timezone.utc)
    hourly = []

    for h in range(hours):
        hour_start = now + timedelta(hours=h)
        hour_end = hour_start + timedelta(hours=1)
        hour_label = hour_start.strftime("%Y-%m-%dT%H:00")

        sessions_this_hour = [
            s for s in sessions
            if _parse_time(s.get("start_time", "")) is not None
            and hour_start <= _parse_time(s["start_time"]) < hour_end
        ]

        demand_by_pool: Dict[str, float] = {}
        labs_starting = []
        for s in sessions_this_hour:
            lab = s.get("lab_code", "")
            pool = s.get("pool_name", "default")
            attendees = s.get("attendees", 0) or 0
            complexity = complexities.get(lab, {}).get("score", 0.3)
            weighted_demand = attendees * max(complexity, 0.1)
            demand_by_pool[pool] = demand_by_pool.get(pool, 0) + weighted_demand
            labs_starting.append({"lab": lab, "attendees": attendees, "complexity": complexity})

        supply_by_pool: Dict[str, float] = {}
        for pname, pdata in pools.items():
            available = pdata.get("available", 0)
            velocity = pool_velocities.get(pname, {}).get("handles_per_hour", 0)
            recycling = pool_velocities.get(pname, {}).get("recycling_rate", 0)
            projected = available + (velocity + recycling) * h
            supply_by_pool[pname] = max(projected, 0)

        hourly.append({
            "hour": hour_label,
            "sessions_starting": len(sessions_this_hour),
            "demand_by_pool": demand_by_pool,
            "supply_by_pool": supply_by_pool,
            "labs_starting": labs_starting,
        })

    bottleneck_pools = []
    bottleneck_hour = None
    for entry in hourly:
        for pool, demand in entry["demand_by_pool"].items():
            supply = entry["supply_by_pool"].get(pool, 0)
            if demand > supply and pool not in bottleneck_pools:
                bottleneck_pools.append(pool)
                if bottleneck_hour is None:
                    bottleneck_hour = entry["hour"]

    total_demand = sum(sum(e["demand_by_pool"].values()) for e in hourly)
    total_supply = sum(sum(e["supply_by_pool"].values()) for e in hourly) / max(hours, 1)

    if bottleneck_pools and any(
        sum(e["demand_by_pool"].values()) > sum(e["supply_by_pool"].values()) * 0.5
        for e in hourly[:3]
    ):
        risk_level = "critical"
    elif bottleneck_pools:
        risk_level = "high"
    elif total_demand > total_supply * 0.8:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "hourly_projections": hourly,
        "bottleneck_pools": bottleneck_pools,
        "bottleneck_hour": bottleneck_hour,
        "risk_level": risk_level,
        "total_demand": round(total_demand, 1),
        "total_supply": round(total_supply, 1),
    }


def _parse_time(val: str) -> Optional[datetime]:
    """Parse ISO datetime string."""
    if not val:
        return None
    try:
        return datetime.fromisoformat(val)
    except (ValueError, TypeError):
        return None
