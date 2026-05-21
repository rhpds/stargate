"""Pool handle velocity tracking — compute depletion rate and estimate exhaustion.

Analyzes time-series pool snapshots to calculate how fast handles are being
consumed vs recycled, and predicts when a pool will hit zero.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def compute_pool_velocity(timeline: List[Dict]) -> Dict[str, Any]:
    """Compute pool handle velocity from a time-series of snapshots.

    Each snapshot dict has: available (int), captured_at (datetime or ISO string).

    Returns:
      handles_per_hour: float (negative = depleting, positive = recovering)
      trend: str ('depleting', 'stable', 'recovering')
      data_points: int
    """
    if len(timeline) < 2:
        return {"handles_per_hour": 0.0, "trend": "stable", "data_points": len(timeline)}

    sorted_tl = sorted(timeline, key=lambda s: _to_ts(s["captured_at"]))
    first = sorted_tl[0]
    last = sorted_tl[-1]

    first_ts = _to_ts(first["captured_at"])
    last_ts = _to_ts(last["captured_at"])
    hours_elapsed = (last_ts - first_ts) / 3600.0

    if hours_elapsed < 0.01:
        return {"handles_per_hour": 0.0, "trend": "stable", "data_points": len(timeline)}

    delta = last["available"] - first["available"]
    velocity = delta / hours_elapsed

    if velocity < -0.5:
        trend = "depleting"
    elif velocity > 0.5:
        trend = "recovering"
    else:
        trend = "stable"

    return {
        "handles_per_hour": round(velocity, 2),
        "trend": trend,
        "data_points": len(timeline),
    }


def estimate_exhaustion(current_available: int, velocity: float) -> Optional[float]:
    """Estimate hours until pool hits zero.

    Returns None if pool is stable or recovering.
    """
    if velocity >= 0 or current_available <= 0:
        return None
    return round(-current_available / velocity, 1)


def compute_recycling_rate(timeline: List[Dict]) -> float:
    """Measure how fast handles return to available (handles/hour recovering).

    Looks at intervals where available increased to estimate recycling velocity.
    """
    if len(timeline) < 2:
        return 0.0

    sorted_tl = sorted(timeline, key=lambda s: _to_ts(s["captured_at"]))
    total_recovered = 0.0
    total_hours = 0.0

    for i in range(1, len(sorted_tl)):
        prev = sorted_tl[i - 1]
        curr = sorted_tl[i]
        delta = curr["available"] - prev["available"]
        hours = (_to_ts(curr["captured_at"]) - _to_ts(prev["captured_at"])) / 3600.0
        if delta > 0 and hours > 0:
            total_recovered += delta
            total_hours += hours

    if total_hours < 0.01:
        return 0.0
    return round(total_recovered / total_hours, 2)


def _to_ts(val) -> float:
    """Convert datetime or ISO string to Unix timestamp."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, datetime):
        return val.timestamp()
    if isinstance(val, str):
        return datetime.fromisoformat(val).timestamp()
    return 0.0
