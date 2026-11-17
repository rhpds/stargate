"""Rotation view — two truths side by side.

Jira says what the plan is (tickets, owners, status). The audit ingest says what
is actually live (verified values, locations, untracked credentials). The page
is deliberately not a reconciliation: where the two disagree, it shows both
numbers and lets the disagreement be the signal.

All reads come from `rotation_snapshots`, written by `collectors/rotation_sync.py`
and `POST /integration/rotation-snapshot` — never from Jira on a page load.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
from datetime import date, datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from db.database import get_db

logger = logging.getLogger("stargate.dashboard.rotation")

router = APIRouter()


def _links() -> List[Dict[str, str]]:
    """Source-data links (Drive/Sheets), configured by deployment.

    The page never fetches these; it only points at them. Drive permissions are
    enforced by Google, so a link is safe to render for anyone who can already
    open the page.
    """
    raw = os.environ.get("STARGATE_ROTATION_LINKS", "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except ValueError:
        logger.warning("STARGATE_ROTATION_LINKS is not valid JSON; ignoring")
        return []
    if not isinstance(parsed, list):
        logger.warning("STARGATE_ROTATION_LINKS must be a JSON list; ignoring")
        return []
    links = []
    for item in parsed:
        if isinstance(item, dict) and item.get("url"):
            links.append({
                "label": str(item.get("label") or "Source data"),
                "url": str(item["url"]),
            })
    return links


def _row(row) -> Dict[str, Any]:
    tickets = row.tickets or 0
    closed = row.closed or 0
    return {
        "provider": row.provider,
        "tickets": tickets,
        "closed": closed,
        "in_progress": row.in_progress or 0,
        "new": row.new or 0,
        "unassigned": row.unassigned or 0,
        "closed_pct": round(100 * closed / tickets) if tickets else 0,
        "verified_live": row.verified_live or 0,
        "live_locations": row.live_locations or 0,
        "untracked_live": row.untracked_live or 0,
    }


_STATUS_RANK = {"in progress": 0, "new": 1, "closed": 2}


@router.get("/dashboard/rotation/provider")
def rotation_provider(name: str = Query(...), db: Session = Depends(get_db)):
    """One provider's tickets, with the audit's numbers beside them.

    Reads the tickets the sync stored — never Jira — so this cannot disagree
    with the counts on the table.
    """
    from db.models import RotationSnapshot, RotationTicket

    tickets = (
        db.query(RotationTicket)
        .filter(RotationTicket.provider == name)
        .all()
    )

    latest_date = db.query(func.max(RotationSnapshot.snapshot_date)).scalar()
    snapshot = None
    if latest_date is not None:
        snapshot = (
            db.query(RotationSnapshot)
            .filter_by(snapshot_date=latest_date, provider=name)
            .first()
        )

    if not tickets and snapshot is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {name}")

    tickets.sort(key=lambda t: (_STATUS_RANK.get((t.status or "").lower(), 1), t.issue_key))
    base_url = os.environ.get("STARGATE_JIRA_URL", "https://redhat.atlassian.net").rstrip("/")
    keys = ",".join(t.issue_key for t in tickets)
    jira_url = (
        f"{base_url}/issues/?jql=" + urllib.parse.quote(f"key in ({keys})")
        if tickets
        else None
    )

    closed = sum(1 for t in tickets if (t.status or "").lower() == "closed")
    in_progress = sum(1 for t in tickets if (t.status or "").lower() == "in progress")
    return {
        "provider": name,
        "counts": {
            "tickets": len(tickets),
            "closed": closed,
            "in_progress": in_progress,
            "new": len(tickets) - closed - in_progress,
            "unassigned": sum(1 for t in tickets if not t.assignee),
        },
        "audit": (
            {
                "verified_live": snapshot.verified_live or 0,
                "live_locations": snapshot.live_locations or 0,
                "untracked_live": snapshot.untracked_live or 0,
            }
            if snapshot
            else None
        ),
        "jira_url": jira_url,
        "tickets": [
            {
                "key": t.issue_key,
                "summary": t.summary,
                "status": t.status,
                "assignee": t.assignee,
                "url": f"{base_url}/browse/{t.issue_key}",
            }
            for t in tickets
        ],
    }


@router.get("/dashboard/rotation")
def dashboard_rotation(db: Session = Depends(get_db)):
    """Latest per-provider rotation state, totals and the daily trend."""
    from db.models import RotationSnapshot

    latest_date = db.query(func.max(RotationSnapshot.snapshot_date)).scalar()

    if latest_date is None:
        from collectors.rotation_sync import jira_configured

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "last_sync": None,
            "source": {
                "jira": "unconfigured" if not jira_configured() else "ok",
                "verification": "none",
                "verification_at": None,
            },
            "links": _links(),
            "summary": {
                "tickets": 0,
                "closed": 0,
                "closed_pct": 0,
                "in_progress": 0,
                "new": 0,
                "unassigned": 0,
                "verified_live": 0,
                "live_locations": 0,
                "untracked_live": 0,
                "providers": 0,
            },
            "providers": [],
            "trend": [],
        }

    latest_rows = (
        db.query(RotationSnapshot)
        .filter(RotationSnapshot.snapshot_date == latest_date)
        .order_by(RotationSnapshot.tickets.desc(), RotationSnapshot.provider.asc())
        .all()
    )
    providers = [_row(r) for r in latest_rows]

    totals: Dict[str, int] = {
        key: sum(p[key] for p in providers)
        for key in (
            "tickets",
            "closed",
            "in_progress",
            "new",
            "unassigned",
            "verified_live",
            "live_locations",
            "untracked_live",
        )
    }
    totals["closed_pct"] = (
        round(100 * totals["closed"] / totals["tickets"]) if totals["tickets"] else 0
    )
    totals["providers"] = len(providers)

    # Trend: one point per day, summed across providers. Never mix days in the
    # totals above — a credential counted twice is worse than an empty chart.
    trend_rows = (
        db.query(
            RotationSnapshot.snapshot_date,
            func.sum(RotationSnapshot.tickets),
            func.sum(RotationSnapshot.closed),
            func.sum(RotationSnapshot.in_progress),
            func.sum(RotationSnapshot.new),
            func.sum(RotationSnapshot.unassigned),
            func.sum(RotationSnapshot.verified_live),
            func.sum(RotationSnapshot.live_locations),
            func.sum(RotationSnapshot.untracked_live),
        )
        .group_by(RotationSnapshot.snapshot_date)
        .order_by(RotationSnapshot.snapshot_date.asc())
        .all()
    )
    trend = [
        {
            "date": (day.isoformat() if isinstance(day, date) else str(day)),
            "tickets": tickets or 0,
            "closed": closed or 0,
            "in_progress": in_progress or 0,
            "new": new or 0,
            "unassigned": unassigned or 0,
            "verified_live": verified_live or 0,
            "live_locations": live_locations or 0,
            "untracked_live": untracked_live or 0,
        }
        for (
            day,
            tickets,
            closed,
            in_progress,
            new,
            unassigned,
            verified_live,
            live_locations,
            untracked_live,
        ) in trend_rows
    ]

    verified = any(
        (r.verified_live or 0) + (r.live_locations or 0) + (r.untracked_live or 0) > 0
        for r in latest_rows
    )
    synced = [r.synced_at for r in latest_rows if r.synced_at]
    verified_times = [r.verified_at for r in latest_rows if r.verified_at]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "last_sync": max(synced).isoformat() if synced else None,
        "source": {
            "jira": "ok",
            "verification": "snapshot" if verified else "none",
            "verification_at": max(verified_times).isoformat() if verified_times else None,
        },
        "links": _links(),
        "summary": totals,
        "providers": providers,
        "trend": trend,
    }
