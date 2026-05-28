"""Demolition collector — session results, run outcomes, failure data.

Read-only. Pulls from Demolition integration REST API.
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

DEFAULT_URL = os.environ.get("STARGATE_DEMOLITION_URL", "")


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
        logger.error(f"Demolition API error: {e}")
        return None


def collect_sessions(base_url: str = DEFAULT_URL) -> List[Dict]:
    """Collect all Demolition sessions."""
    return _get(f"{base_url}/integration/sessions") or []


def collect_session_status(base_url: str = DEFAULT_URL, session_id: int = 0) -> Optional[Dict]:
    """Collect status and latest run for a session."""
    return _get(f"{base_url}/integration/sessions/{session_id}/status")


def summarize_sessions(base_url: str = DEFAULT_URL) -> Dict:
    """Summarize all Demolition sessions with results."""
    sessions = collect_sessions(base_url)

    from collections import Counter
    status_counts = Counter(s.get("status", "unknown") for s in sessions)

    # Analyze results
    total_runs = 0
    total_passed = 0
    total_failed = 0
    failing_sessions = []
    recent_sessions = []

    for s in sessions:
        result = s.get("last_result") or {}
        session_total = result.get("total", 0)
        session_completed = result.get("completed", 0)
        session_failed = result.get("failed", 0)

        total_runs += session_total
        total_passed += session_completed
        total_failed += session_failed

        if session_failed > 0:
            failing_sessions.append({
                "id": s.get("id"),
                "name": s.get("name", "")[:60],
                "status": s.get("status"),
                "workers": s.get("worker_count"),
                "completed": session_completed,
                "failed": session_failed,
                "total": session_total,
                "failure_rate": round(session_failed / max(session_total, 1) * 100, 1),
            })

        # Recent sessions (last 50 by ID)
        recent_sessions.append({
            "id": s.get("id"),
            "name": s.get("name", "")[:60],
            "status": s.get("status"),
            "workers": s.get("worker_count"),
            "result": result,
        })

    # Sort failing by failure rate
    failing_sessions.sort(key=lambda x: -x.get("failure_rate", 0))

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_sessions": len(sessions),
        "status_counts": dict(status_counts),
        "total_runs": total_runs,
        "total_passed": total_passed,
        "total_failed": total_failed,
        "overall_pass_rate": round(total_passed / max(total_runs, 1) * 100, 1),
        "failing_sessions": failing_sessions[:20],
        "recent_sessions": recent_sessions[-10:],
    }


def find_tracked_sessions(base_url: str = DEFAULT_URL, prefix: str = "") -> List[Dict]:
    """Find Demolition sessions matching a prefix filter (or all if empty)."""
    sessions = collect_sessions(base_url)
    tracked = []
    for s in sessions:
        name = s.get("name", "").lower()
        url = s.get("workshop_url", "").lower()
        if prefix and prefix.lower() not in name and prefix.lower() not in url:
            continue
        result = s.get("last_result") or {}
        tracked.append({
            "id": s.get("id"),
            "name": s.get("name", "")[:80],
            "status": s.get("status"),
            "workers": s.get("worker_count"),
            "workshop_url": s.get("workshop_url", "")[:80],
            "completed": result.get("completed", 0),
            "failed": result.get("failed", 0),
            "total": result.get("total", 0),
        })
    return tracked


# Backward compat
find_summit_sessions = find_tracked_sessions
