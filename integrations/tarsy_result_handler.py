"""Handler for TARSy investigation results consumed from Kafka."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from events.models import Event

logger = logging.getLogger("stargate.tarsy_result")


def handle_tarsy_result(message: dict) -> None:
    """Process TARSy investigation results.

    Extracts the payload from the EcosystemEvent envelope, logs the outcome,
    maps recommended actions to the remediation catalog, and emits an event
    through the bus for dashboard visibility.
    """
    # Extract payload from EcosystemEvent envelope
    payload = message.get("data")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            logger.debug("TARSy result payload not valid JSON: %s", payload)
            payload = {}
    if payload is None:
        payload = {}

    originator_id = message.get("originator_id", "")
    severity = message.get("severity", "unknown")
    status = payload.get("status", "unknown")
    recommended_actions = payload.get("recommended_actions", [])
    root_cause = payload.get("root_cause")

    logger.info(
        "TARSy result received — run_id=%s status=%s root_cause=%s actions=%d",
        originator_id,
        status,
        root_cause,
        len(recommended_actions),
    )

    # Map recommended_actions to remediation catalog entries
    catalog_entries = _map_to_catalog(recommended_actions)

    # Emit event through the event bus for dashboard visibility
    try:
        from events.bus import _bus
        if _bus is not None:
            event = Event(
                event_type="tarsy.result.received",
                run_id=originator_id,
                outcome=status,
                message=f"TARSy investigation complete: {root_cause or 'no root cause identified'}",
                metadata={
                    "tarsy_status": status,
                    "root_cause": root_cause,
                    "recommended_actions": recommended_actions,
                    "catalog_entries": catalog_entries,
                    "severity": severity,
                },
            )
            _bus.emit(event)
    except Exception as e:
        logger.debug("Failed to emit TARSy result event: %s", e)


def _map_to_catalog(actions: list) -> list[dict]:
    """Map TARSy recommended actions to remediation catalog entries."""
    catalog_entries = []
    for action in actions:
        if isinstance(action, str):
            catalog_entries.append({"action": action, "catalog_match": None})
        elif isinstance(action, dict):
            catalog_entries.append({
                "action": action.get("description", str(action)),
                "catalog_match": action.get("catalog_id"),
            })
    return catalog_entries
