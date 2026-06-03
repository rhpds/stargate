"""TARSy escalation trigger for unclassified / repeat remediation failures.

Tracks per-lab/cluster failure counts and escalates to TARSy when
remediation has failed 2+ times and the failure remains unclassified.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from events.models import Event

logger = logging.getLogger("stargate.tarsy_escalation")


class TarsyEscalationTracker:
    """Counts failures per lab/cluster and triggers TARSy investigation requests."""

    def __init__(self):
        self._failure_counts: dict[str, int] = {}  # "lab_code:cluster_name" -> count
        self._escalated: set[str] = set()  # keys already escalated

    @staticmethod
    def _key(event: Event) -> str:
        return f"{event.lab_code or 'unknown'}:{event.cluster_name or 'unknown'}"

    def record_failure(self, event: Event) -> None:
        """Increment failure count for this lab/cluster combo."""
        key = self._key(event)
        self._failure_counts[key] = self._failure_counts.get(key, 0) + 1

    def should_escalate(self, event: Event) -> bool:
        """Check if this failure should trigger TARSy investigation.

        Returns True when:
        - failure_class is None or "unclassified"
        - failure count for the lab/cluster >= 2
        - key has not already been escalated
        """
        key = self._key(event)
        if event.failure_class is not None and event.failure_class != "unclassified":
            return False
        if self._failure_counts.get(key, 0) < 2:
            return False
        if key in self._escalated:
            return False
        return True

    def escalate(self, event: Event, db=None) -> None:
        """Build and publish a TARSy investigation request."""
        key = self._key(event)

        # Build recent evaluation history from the event bus if available
        recent_history = []
        try:
            from events.bus import _bus
            if _bus is not None:
                recent_events = _bus.get_recent_for_cluster(
                    event.cluster_name or "", limit=20
                )
                recent_history = [e.to_dict() for e in recent_events]
        except Exception:
            pass

        request = {
            "alert_type": "StarGateFailure",
            "severity": "high",
            "originator_id": event.run_id,
            "data": json.dumps({
                "event": event.to_dict(),
                "recent_history": recent_history,
                "failure_count": self._failure_counts.get(key, 0),
            }),
            "mcp_override": {
                "tools": ["kubernetes-server"],
                "access": "read-only",
            },
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            from integrations.kafka_publisher import publish_tarsy_request
            publish_tarsy_request(request)
            logger.info(
                "TARSy escalation published for %s (failure count: %d)",
                key,
                self._failure_counts.get(key, 0),
            )
        except Exception as e:
            logger.debug("TARSy escalation publish failed: %s", e)

        self._escalated.add(key)


_escalation_tracker = TarsyEscalationTracker()
