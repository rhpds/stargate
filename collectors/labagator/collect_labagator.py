"""Labagator collector — lab schedule, ops status, and session urgency.

Read-only. Pulls from Labagator REST API.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_URL = os.environ.get("STARGATE_LABAGATOR_URL", "")


def _get(url: str) -> Optional[Any]:
    ctx = ssl.create_default_context()
    if os.environ.get("STARGATE_SSL_VERIFY", "true").lower() == "false":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request(url)
        resp = urllib.request.urlopen(req, timeout=15, context=ctx)
        return json.loads(resp.read())
    except Exception as e:
        logger.error(f"Labagator API error: {e}")
        return None


def collect_labs(base_url: str = DEFAULT_URL, event_id: Optional[int] = None, limit: int = 200) -> List[Dict]:
    """Collect all labs from Labagator."""
    url = f"{base_url}/labs/?limit={limit}"
    if event_id:
        url += f"&event_id={event_id}"
    return _get(url) or []


def collect_sessions(base_url: str = DEFAULT_URL, event_id: Optional[int] = None, limit: int = 500) -> List[Dict]:
    """Collect room sessions with schedule and ops data."""
    url = f"{base_url}/room-sessions/?limit={limit}"
    if event_id:
        url += f"&event_id={event_id}"
    return _get(url) or []


def collect_events(base_url: str = DEFAULT_URL) -> List[Dict]:
    """Collect all events."""
    return _get(f"{base_url}/events/") or []


def collect_ops_dashboard(base_url: str = DEFAULT_URL, event_id: int = 1) -> Optional[Dict]:
    """Collect ops dashboard for an event."""
    return _get(f"{base_url}/ops/dashboard/{event_id}")


def summarize_labs(base_url: str = DEFAULT_URL, event_id: Optional[int] = None) -> Dict:
    """Summarize all labs with status and schedule context."""
    labs = collect_labs(base_url, event_id)
    sessions = collect_sessions(base_url, event_id)

    # Build lab lookup
    lab_by_code = {}
    for l in labs:
        code = l.get("lab_code", "")
        if code:
            lab_by_code[code] = l

    # Build session lookup by lab_code
    sessions_by_lab: Dict[str, List] = {}
    for s in sessions:
        code = s.get("lab_code", "")
        if code:
            sessions_by_lab.setdefault(code, []).append(s)

    # Status counts
    from collections import Counter
    status_counts = Counter(l.get("status", "unknown") for l in labs)
    cloud_counts = Counter(l.get("cloud", "unknown") for l in labs)

    # Find upcoming sessions (next 24h)
    now = datetime.now(timezone.utc)
    upcoming = []
    for s in sessions:
        session_date = s.get("session_date")
        start_time = s.get("start_time")
        if session_date and start_time:
            try:
                dt_str = f"{session_date}T{start_time}"
                session_dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
                hours_until = (session_dt - now).total_seconds() / 3600
                if 0 < hours_until < 24:
                    upcoming.append({
                        "lab_code": s.get("lab_code"),
                        "room": s.get("room"),
                        "attendees": s.get("attendees"),
                        "start_time": start_time,
                        "session_date": session_date,
                        "hours_until": round(hours_until, 1),
                        "status": s.get("status"),
                        "ops_deploy_person": s.get("ops_deploy_person"),
                    })
            except (ValueError, TypeError):
                pass

    upcoming.sort(key=lambda x: x.get("hours_until", 999))

    return {
        "timestamp": now.isoformat(),
        "total_labs": len(labs),
        "total_sessions": len(sessions),
        "status_counts": dict(status_counts),
        "cloud_counts": dict(cloud_counts),
        "upcoming_sessions": upcoming[:20],
        "labs_by_code": {
            code: {
                "title": l.get("title", ""),
                "status": l.get("status", ""),
                "cloud": l.get("cloud", ""),
                "deploy_mode": l.get("deploy_mode", ""),
                "ci_name": l.get("ci_name", ""),
                "session_count": len(sessions_by_lab.get(code, [])),
            }
            for code, l in lab_by_code.items()
        },
    }
