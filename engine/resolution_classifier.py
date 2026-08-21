"""Resolution classifier — builds profiles from shadow mode data.

Aggregates resolution patterns per failure_class + catalog_item
to determine: self-resolve rate, intervention rate, avg time to resolve.
Recommends: watch_and_wait | investigate | candidate_for_auto_remediation.

Requires minimum 10 resolutions per profile before recommending.
"""

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from engine.historical_miner import SHADOW_STATE_FILE

logger = logging.getLogger("stargate.resolution_classifier")

MIN_RESOLUTIONS = 10


def build_resolution_profiles() -> Dict:
    """Build resolution profiles from accumulated shadow data."""
    if not SHADOW_STATE_FILE.exists():
        return {"status": "no_data", "profiles": {}}

    state = json.loads(SHADOW_STATE_FILE.read_text())
    shadow_log = state.get("shadow_log", [])
    incident_log = state.get("incident_log", [])

    profiles = defaultdict(lambda: {
        "total": 0, "resolved": 0, "unresolved": 0,
        "causes": defaultdict(int),
        "resolve_times_minutes": [],
    })

    for entry in shadow_log + incident_log:
        fc = entry.get("failure_class", "unknown")
        catalog_item = entry.get("catalog_item", entry.get("namespace", "unknown"))
        # Extract catalog item from sandbox namespace
        from engine.namespace import strip_sandbox_prefix
        catalog_item = strip_sandbox_prefix(catalog_item)

        key = f"{catalog_item}:{fc}"
        profiles[key]["total"] += 1
        profiles[key]["failure_class"] = fc
        profiles[key]["catalog_item"] = catalog_item

        if entry.get("resolved"):
            profiles[key]["resolved"] += 1
            cause = entry.get("resolution_cause", {})
            if isinstance(cause, dict) and cause.get("cause"):
                profiles[key]["causes"][cause["cause"]] += 1
            # Calculate time to resolve
            detected = entry.get("detected_at", entry.get("proposed_at"))
            resolved_at = entry.get("resolved_at")
            if detected and resolved_at:
                try:
                    d = datetime.fromisoformat(detected.replace("Z", "+00:00"))
                    r = datetime.fromisoformat(resolved_at.replace("Z", "+00:00"))
                    minutes = (r - d).total_seconds() / 60
                    if minutes > 0:
                        profiles[key]["resolve_times_minutes"].append(minutes)
                except Exception:
                    pass
        else:
            profiles[key]["unresolved"] += 1

    # Build recommendations
    result = {}
    for key, profile in profiles.items():
        total = profile["total"]
        resolved = profile["resolved"]
        causes = dict(profile["causes"])
        times = profile["resolve_times_minutes"]

        rec = {
            "failure_class": profile.get("failure_class"),
            "catalog_item": profile.get("catalog_item"),
            "total_observations": total,
            "resolved": resolved,
            "unresolved": profile["unresolved"],
            "resolution_causes": causes,
            "avg_time_to_resolve_minutes": round(sum(times) / len(times), 1) if times else None,
            "self_resolve_rate": round(causes.get("self_resolved", 0) / max(resolved, 1), 2) if resolved else None,
            "human_intervention_rate": round(causes.get("human_remediated", 0) / max(resolved, 1), 2) if resolved else None,
            "namespace_recycled_rate": round(causes.get("namespace_recycled", 0) / max(resolved, 1), 2) if resolved else None,
            "recommendation": None,
            "sufficient_data": total >= MIN_RESOLUTIONS,
        }

        if total >= MIN_RESOLUTIONS and resolved > 0:
            self_rate = causes.get("self_resolved", 0) / max(resolved, 1)
            human_rate = causes.get("human_remediated", 0) / max(resolved, 1)
            recycled_rate = causes.get("namespace_recycled", 0) / max(resolved, 1)

            if recycled_rate > 0.7:
                rec["recommendation"] = "watch_and_wait"
                rec["reasoning"] = f"{int(recycled_rate*100)}% resolve via namespace lifecycle — no intervention needed"
            elif self_rate > 0.5:
                rec["recommendation"] = "watch_and_wait"
                rec["reasoning"] = f"{int(self_rate*100)}% self-resolve — monitor but don't act"
            elif human_rate > 0.3:
                rec["recommendation"] = "investigate"
                rec["reasoning"] = f"{int(human_rate*100)}% require human intervention — investigate root cause"
            elif profile["unresolved"] > resolved:
                rec["recommendation"] = "investigate"
                rec["reasoning"] = f"More unresolved ({profile['unresolved']}) than resolved ({resolved}) — needs attention"
            else:
                rec["recommendation"] = "candidate_for_auto_remediation"
                rec["reasoning"] = "Resolves consistently, low self-resolve rate — candidate for automation"
        elif total >= MIN_RESOLUTIONS:
            rec["recommendation"] = "investigate"
            rec["reasoning"] = f"{total} observations, 0 resolved — persistent issue"

        result[key] = rec

    return {
        "status": "ok",
        "total_profiles": len(result),
        "sufficient_data_count": sum(1 for r in result.values() if r["sufficient_data"]),
        "profiles": result,
    }
