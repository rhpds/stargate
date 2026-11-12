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
        # Labagator session times are date+time without a timezone; treat
        # naive values as UTC so comparisons against aware 'now' work.
        # (Found by test_resource_demand.py — the previous naive/aware
        # mismatch crashed the projection on real session shapes.)
        parsed = datetime.fromisoformat(val)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, TypeError):
        return None


def project_resource_demand(
    sessions: List[Dict],
    profiles: Dict[str, Any],
    hours: int = 72,
    start: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Per-hour resource demand in real units: sessions x resource profiles.

    The resource-level join from the capacity forecaster plan (Phase 1).
    Demand is honest about what it does not know:

    - a unit is summed only from profiles that carry it; an hour where no
      session contributes a unit reports None (unobserved), never zero
    - labs without profiles (or with fallback coverage) contribute no
      units and are counted per hour — observed demand is explicitly a
      LOWER BOUND (the catalog audits ~28 percent profile coverage)
    - every hour carries citations: which sessions produced its units

    Args:
        sessions: [{lab_code, start_time (ISO), attendees}]
        profiles: {lab_code: ResourceProfile} (engine.resource_profiles)
        hours: forecast window
        start: window origin (default now)

    Returns:
        hourly: per-hour {vm_slots, ai_cores, ai_memory_gib,
                          sessions_without_profiles, demand_citations}
        coverage: {sessions_total, sessions_with_profiles,
                   sessions_fallback, lower_bound: True}
        peak_hour: the hour entry with the highest observed VM demand
    """
    base = start or datetime.now(timezone.utc)
    # Align to the wall-clock hour: session times arrive at second
    # precision (Labagator shape), and relative-hour buckets made them
    # slip a bucket on sub-second offsets. Hour 0 is the current hour.
    base = base.replace(minute=0, second=0, microsecond=0)

    parsed = []
    for s in sessions or []:
        t = _parse_time(s.get("start_time", ""))
        if t is None or not (base <= t < base + timedelta(hours=hours)):
            continue
        parsed.append((t, s))

    totals = {"sessions_total": 0, "sessions_with_profiles": 0,
              "sessions_fallback": 0}
    hourly = []
    for h in range(hours):
        hour_start = base + timedelta(hours=h)
        hour_end = hour_start + timedelta(hours=1)
        in_hour = [(t, s) for t, s in parsed if hour_start <= t < hour_end]

        vm_slots = ai_cores = ai_memory = None
        without_profiles = 0
        citations = []
        for _, s in in_hour:
            lab = s.get("lab_code", "")
            attendees = s.get("attendees") or 0
            totals["sessions_total"] += 1
            profile = (profiles or {}).get(lab)
            has_units = profile is not None and any(
                v is not None
                for v in (profile.worker_count, profile.ai_cores, profile.ai_memory_gib)
            )
            if not has_units:
                totals["sessions_fallback"] += 1
                without_profiles += 1
                continue

            totals["sessions_with_profiles"] += 1
            citation = {"lab": lab, "attendees": attendees}
            if profile.worker_count is not None:
                citation["vm_slots"] = attendees * profile.worker_count
                vm_slots = (vm_slots or 0) + citation["vm_slots"]
            if profile.ai_cores is not None:
                citation["ai_cores"] = attendees * profile.ai_cores
                ai_cores = (ai_cores or 0) + citation["ai_cores"]
            if profile.ai_memory_gib is not None:
                citation["ai_memory_gib"] = attendees * profile.ai_memory_gib
                ai_memory = (ai_memory or 0) + citation["ai_memory_gib"]
            citations.append(citation)

        hourly.append({
            "hour": hour_start.strftime("%Y-%m-%dT%H:00"),
            "sessions": len(in_hour),
            "vm_slots": vm_slots,
            "ai_cores": ai_cores,
            "ai_memory_gib": ai_memory,
            "sessions_without_profiles": without_profiles,
            "demand_citations": citations,
        })

    peak = max(hourly, key=lambda e: e["vm_slots"] or 0) if hourly else None
    return {
        "hourly": hourly,
        "coverage": {**totals, "lower_bound": True},
        "peak_hour": peak,
    }
