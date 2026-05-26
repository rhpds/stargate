"""Showroom health collector — parse showroom probe results into evidence.

Read-only. No mutation. No write verbs.
Works with pre-collected health check results (fixture JSON or live probes).
"""

from __future__ import annotations

from typing import Dict

from collectors.openshift.collect_resource_state import CollectedEvidence

RESPONSE_TIME_THRESHOLD_MS = 5000


def collect_showroom_health(data: Dict) -> CollectedEvidence:
    """Parse ShowroomHealth JSON into normalized evidence."""
    metadata = data.get("metadata", {})
    status = data.get("status", {})

    response_time = status.get("response_time_ms", 99999)

    return CollectedEvidence(
        resource_kind="ShowroomHealth",
        resource_name=metadata.get("name", "showroom"),
        namespace=metadata.get("namespace", "unknown"),
        observed={
            "showroom_pod_running": status.get("pod_running", False),
            "showroom_route_reachable": status.get("route_reachable", False),
            "readyz_returns_200": status.get("readyz_status") == 200,
            "content_loaded": status.get("content_loaded", False),
            "response_time_acceptable": response_time < RESPONSE_TIME_THRESHOLD_MS,
        },
    )
