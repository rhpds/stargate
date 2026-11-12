"""Per-pool demand projection — the event-pool capacity class.

The join the authority gate's first evaluation demanded: sessions ->
Labagator lab records -> deploy_limit (concurrent environment slots).
Occupancy = attendees across the session's duration; deficit when
occupancy exceeds the limit; at_limit (full utilization, no headroom)
is amber, distinct from deficit. `known_since` carries when the demand
became schedulable — the honest lead-time evidence, since a crossing
visible in the schedule was knowable at session creation.

Validated against the documented event-pool exhaustion (Nov 13 2026
live data): LB1758 15 attendees vs 15 slots (the documented 98
percent), LB2645 23 vs 11 (209 percent), both scheduled Sep 30 15:30.

Semantics follow the house contract rules: a missing deploy_limit is
indeterminate (never zero); unmapped labs are counted, never dropped.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

DEFAULT_SESSION_DURATION_HOURS = 4.0


def _parse_ts(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace(" ", "T"))
    except (ValueError, TypeError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def project_pool_demand(
    sessions: List[Dict],
    labs_by_code: Dict[str, Dict],
    hours: int = 72,
    start: Optional[datetime] = None,
) -> Dict:
    """Per-pool occupancy vs deploy_limit over the window."""
    base = start or datetime.now(timezone.utc)
    base = base.replace(minute=0, second=0, microsecond=0)
    window_end = base + timedelta(hours=hours)

    parsed = []
    unmapped = 0
    # Shared-cohort (roadshow) semantics: sessions sharing (event_id,
    # session_date) are one group of people rotating through rooms —
    # the event's attendance stamped on every room is the cohort size,
    # not per-room concurrency. Found in the first forward pass: event
    # 46, 11 rooms x 70 attendees, all 08:00-18:00 — 70 people, not 770.
    cohort_counts = {}
    for s in sessions or []:
        if s.get("event_id") is not None:
            cohort_key = (s.get("event_id"), s.get("session_date"))
            cohort_counts[cohort_key] = cohort_counts.get(cohort_key, 0) + 1
        # Full-ISO start_time (projector shape) or date+time (Labagator raw)
        ts = _parse_ts(s.get("start_time"))
        if ts is None and s.get("session_date"):
            ts = _parse_ts("%sT%s" % (s["session_date"], s.get("start_time", "")))
        if ts is None or not (base <= ts < window_end):
            continue
        lab_code = str(s.get("lab_code") or "")
        lab = labs_by_code.get(lab_code)
        if lab is None:
            unmapped += 1
            continue
        parsed.append((ts, s, lab))

    pools: Dict[str, Dict] = {}
    for ts, s, lab in parsed:
        code = str(lab.get("lab_code") or s.get("lab_code"))
        limit = lab.get("deploy_limit")
        try:
            limit_n = int(limit) if limit is not None else None
        except (ValueError, TypeError):
            limit_n = None
        duration = lab.get("deploy_time_hours")
        try:
            duration_h = float(duration) if duration not in (None, "") else DEFAULT_SESSION_DURATION_HOURS
        except (ValueError, TypeError):
            duration_h = DEFAULT_SESSION_DURATION_HOURS
        if duration_h <= 0:
            # '0.00' is a truthy string but means "no duration declared"
            duration_h = DEFAULT_SESSION_DURATION_HOURS

        entry = pools.setdefault(code, {
            "lab_code": code, "deploy_limit": limit_n,
            "peak_occupancy": 0, "hourly": [],
            "crossing_hour": None, "known_since": None, "_spans": [],
        })
        # Snap outward to hour boundaries: a 15-minute session (found
        # live: LB2645, deploy_time_hours '0.25') still occupies its
        # starting hour; a 4h session starting at :30 spans five hours.
        import math
        hour_floor = ts.replace(minute=0, second=0, microsecond=0)
        fractional = (ts - hour_floor).total_seconds() / 3600
        occupied = max(1, math.ceil(fractional + duration_h))
        entry["_spans"].append((hour_floor, hour_floor + timedelta(hours=occupied),
                                s.get("attendees") or 0))
        created = _parse_ts(s.get("created_at"))
        if created is not None and (entry["known_since"] is None or created < entry["known_since"]):
            entry["known_since"] = created

    for code, entry in pools.items():
        limit_n = entry["deploy_limit"]
        for h in range(hours):
            hour_start = base + timedelta(hours=h)
            occupancy = sum(
                attendees for span_start, span_end, attendees in entry["_spans"]
                if span_start <= hour_start < span_end)
            entry["peak_occupancy"] = max(entry["peak_occupancy"], occupancy)
            if limit_n is not None and occupancy > limit_n and entry["crossing_hour"] is None:
                entry["crossing_hour"] = hour_start.isoformat()
            entry["hourly"].append({
                "hour": hour_start.strftime("%Y-%m-%dT%H:00"),
                "occupancy": occupancy,
            })
        del entry["_spans"]
        if limit_n is None:
            entry["deficit_state"] = "indeterminate"
        elif entry["peak_occupancy"] > limit_n:
            entry["deficit_state"] = "deficit"
        elif entry["peak_occupancy"] == limit_n and limit_n > 0:
            entry["deficit_state"] = "at_limit"
        else:
            entry["deficit_state"] = "headroom"

    # Cohort demand: per (event_id, date) the max attendance (the people
    # are shared across rooms); ungrouped sessions sum their own.
    cohort_demand = 0
    cohorts = {}
    for ts, s, lab in parsed:
        eid = s.get("event_id")
        if eid is not None:
            key = (eid, s.get("session_date"))
            cohorts[key] = max(cohorts.get(key, 0), s.get("attendees") or 0)
        else:
            cohort_demand += s.get("attendees") or 0
    cohort_demand += sum(cohorts.values())

    shared_cohort_sessions = sum(
        n for n in cohort_counts.values() if n > 1)
    return {
        "pools": pools,
        "cohort_demand": cohort_demand,
        "coverage": {"sessions_mapped": len(parsed),
                     "sessions_unmapped": unmapped,
                     "shared_cohort_sessions": shared_cohort_sessions},
    }
