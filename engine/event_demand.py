"""Event-grouped demand — the Summit/RH1-scale forecast view.

Per event, per day: session count, the COHORT bound (shared rotating
people — roadshow semantics) and the SUMMED bound (separate audiences
— workshop semantics), plus peak concurrent attendance computed from
the sessions' real start/end times.

The two bounds are the honest answer: whether an event's rooms share
one cohort or hold separate audiences is not recorded in Labagator,
so demand is bounded, not pointed. Capacity decisions read the bound
appropriate to their question (people vs environments) and the fleet
comparison applies the profile multiplier downstream.
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional


def _parse_time(val, date_str=None):
    if val is None:
        return None
    try:
        text = str(val)
        if date_str and "T" not in text:
            text = "%sT%s" % (date_str, text)
        ts = datetime.fromisoformat(text)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except (ValueError, TypeError):
        return None


def _peak_concurrent(spans) -> int:
    """Max over time of summed attendance across overlapping spans."""
    if not spans:
        return 0
    events_points = []
    for start, end, attendees in spans:
        events_points.append((start, attendees))
        events_points.append((end, -attendees))
    events_points.sort()
    current = peak = 0
    for _, delta in events_points:
        current += delta
        peak = max(peak, current)
    return peak


def project_event_demand(
    sessions: List[Dict],
    start: Optional[datetime] = None,
    days: int = 120,
) -> Dict:
    """Per-event, per-day demand bounds from real session times."""
    base = (start or datetime.now(timezone.utc)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    window_end = base + timedelta(days=days)

    events: Dict[str, Dict] = {}
    for s in sessions or []:
        date_str = str(s.get("session_date") or "")[:10]
        if not date_str:
            continue
        try:
            day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if not (base <= day < window_end):
            continue

        eid = s.get("event_id")
        key = str(eid) if eid is not None else "ungrouped"
        ev = events.setdefault(key, {"event_id": eid, "days": {}})
        day_rec = ev["days"].setdefault(date_str, {
            "sessions": 0, "cohort_bound": 0, "summed_bound": 0,
            "_spans": [],
        })
        attendees = s.get("attendees") or 0
        day_rec["sessions"] += 1
        day_rec["summed_bound"] += attendees
        day_rec["cohort_bound"] = max(day_rec["cohort_bound"], attendees)

        s_ts = _parse_time(s.get("start_time"), date_str)
        e_ts = _parse_time(s.get("end_time"), date_str)
        if s_ts and e_ts and e_ts > s_ts:
            day_rec["_spans"].append((s_ts, e_ts, attendees))

    for ev in events.values():
        for date_str, day_rec in ev["days"].items():
            day_rec["peak_concurrent"] = _peak_concurrent(day_rec.pop("_spans"))

    return {"events": events, "window": {"start": base.isoformat(),
                                          "days": days}}
