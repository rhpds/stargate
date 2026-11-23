"""Session coverage — planned seats vs provisioned and healthy labs.

For a scheduled session of N attendees, how many sandboxes actually exist, how
many are healthy, and how many never appeared. This is the join that was
missing: the schedule knows seats, evaluations know namespaces, and nothing
connected them.

Shape 1 (one sandbox per attendee) is measurable here. Shape 2 (multi-user
services: one namespace, many seats) needs app-level or RUM telemetry and is
reported as a single namespace, not N seats.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

_CHANNEL = re.compile(r"\.(prod|dev|event)$")
_ORG = re.compile(r"^(published|enterprise|agd-v2|partner)\.", re.IGNORECASE)


def normalize_catalog(item: str) -> str:
    """`published.ocp4-cluster.prod` → `ocp4-cluster`."""
    value = (item or "").strip().lower().replace("/", ".")
    value = _CHANNEL.sub("", value)
    value = _ORG.sub("", value)
    return value


def _parse(session: Dict[str, Any], now: datetime) -> Optional[Dict[str, Any]]:
    date = str(session.get("session_date") or "")
    start = str(session.get("start_time") or "")
    end = str(session.get("end_time") or "")
    if not date or not start:
        return None
    try:
        starts = datetime.fromisoformat(f"{date}T{start}")
        ends = datetime.fromisoformat(f"{date}T{end}") if end else starts + timedelta(hours=8)
    except ValueError:
        return None
    if starts.tzinfo is None:
        starts = starts.replace(tzinfo=timezone.utc)
        ends = ends.replace(tzinfo=timezone.utc)
    return {
        "starts": starts,
        "ends": max(ends, starts + timedelta(minutes=30)),
        "date": date,
        "room": session.get("room") or "",
        "lab_code": session.get("lab_code") or "",
        "attendees": int(session.get("attendees") or 0),
    }


def coverage(
    db,
    sessions: List[Dict[str, Any]],
    catalog_by_code: Dict[str, str],
    now: Optional[datetime] = None,
    hours_back: int = 6,
    hours_ahead: int = 6,
    grace_minutes: int = 120,
) -> Dict[str, Any]:
    """Planned vs provisioned vs healthy, per session."""
    from db.models import EvaluationRecord, LabMapping
    from db.lab_identity import lab_code_filter

    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(hours=hours_back)
    window_end = now + timedelta(hours=hours_ahead)
    grace = timedelta(minutes=grace_minutes)

    planned = []
    for session in sessions:
        parsed = _parse(session, now)
        if not parsed or parsed["attendees"] <= 0:
            continue
        if not (window_start <= parsed["starts"] <= window_end):
            continue
        catalog = catalog_by_code.get(parsed["lab_code"], parsed["lab_code"])
        parsed["catalog_item"] = normalize_catalog(catalog)
        planned.append(parsed)

    if not planned:
        return {
            "generated_at": now.isoformat(),
            "window_hours": {"back": hours_back, "ahead": hours_ahead},
            "summary": {"sessions": 0, "planned_seats": 0, "provisioned": 0},
            "sessions": [],
        }

    query_start = min(item["starts"] for item in planned) - grace
    query_end = max(item["ends"] for item in planned) + grace

    rows = (
        db.query(
            EvaluationRecord.lab_code,
            EvaluationRecord.stage_id,
            EvaluationRecord.outcome,
            EvaluationRecord.evaluated_at,
        )
        .filter(
            EvaluationRecord.evaluated_at >= query_start,
            EvaluationRecord.evaluated_at <= query_end,
            lab_code_filter(EvaluationRecord.lab_code),
        )
        .order_by(EvaluationRecord.evaluated_at.asc())
        .all()
    )

    def _aware(value):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    labs: Dict[str, Dict[str, Any]] = {}
    for lab, stage, outcome, at in rows:
        at = _aware(at)
        entry = labs.setdefault(lab, {"first": at, "stages": {}})
        if at < entry["first"]:
            entry["first"] = at
        entry["stages"][stage] = outcome

    slugs = {}
    if labs:
        for mapping in db.query(LabMapping).filter(LabMapping.lab_code.in_(list(labs))).all():
            slugs[mapping.lab_code] = normalize_catalog(mapping.ci_slug or "")

    by_family = defaultdict(list)
    for lab, entry in labs.items():
        by_family[slugs.get(lab, "")].append((lab, entry))

    results = []
    for session in planned:
        candidates = by_family.get(session["catalog_item"], [])
        matched = [
            (lab, entry) for lab, entry in candidates
            if session["starts"] - grace <= entry["first"] <= session["ends"] + grace
        ]
        states = Counter()
        for _, entry in matched:
            outcomes = set(entry["stages"].values())
            states["failing" if "fail" in outcomes else "ready" if outcomes == {"pass"} else "unknown"] += 1
        provisioned = len(matched)
        missing = max(0, session["attendees"] - provisioned)
        results.append({
            "date": session["date"],
            "start": session["starts"].isoformat(),
            "end": session["ends"].isoformat(),
            "room": session["room"],
            "lab_code": session["lab_code"],
            "catalog_item": session["catalog_item"],
            "planned_seats": session["attendees"],
            "provisioned": provisioned,
            "ready": states.get("ready", 0),
            "failing": states.get("failing", 0),
            "unknown": states.get("unknown", 0),
            "missing": missing,
            "coverage_pct": round(100 * provisioned / session["attendees"]),
        })

    results.sort(key=lambda row: (-row["planned_seats"], row["start"]))
    total_planned = sum(row["planned_seats"] for row in results)
    total_provisioned = sum(row["provisioned"] for row in results)
    return {
        "generated_at": now.isoformat(),
        "window_hours": {"back": hours_back, "ahead": hours_ahead},
        "summary": {
            "sessions": len(results),
            "planned_seats": total_planned,
            "provisioned": total_provisioned,
            "ready": sum(row["ready"] for row in results),
            "failing": sum(row["failing"] for row in results),
            "unknown": sum(row["unknown"] for row in results),
            "missing": sum(row["missing"] for row in results),
            "coverage_pct": round(100 * total_provisioned / total_planned) if total_planned else 0,
        },
        "sessions": results,
    }
