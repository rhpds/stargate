"""Outbound event publisher — pushes evaluation results to DeepField and Launchpad."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEEPFIELD_API_URL = os.environ.get("DEEPFIELD_API_URL")
DEEPFIELD_API_KEY = os.environ.get("DEEPFIELD_API_KEY")
LAUNCHPAD_API_URL = os.environ.get("LAUNCHPAD_API_URL")
LAUNCHPAD_API_KEY = os.environ.get("LAUNCHPAD_API_KEY")
DASHBOARD_AUDIT_URL = os.environ.get("DASHBOARD_AUDIT_URL")
SSL_VERIFY = os.environ.get("INTEGRATION_SSL_VERIFY", "true").lower() != "false"


async def _push(base_url: Optional[str], api_key: Optional[str], payload: dict):
    if not base_url:
        return
    try:
        async with httpx.AsyncClient(verify=SSL_VERIFY, timeout=5.0) as client:
            headers = {"X-API-Key": api_key} if api_key else {}
            await client.post(f"{base_url}/integration/events", json=payload, headers=headers)
    except Exception as e:
        logger.debug("Event push to %s failed (non-critical): %s", base_url, e)


async def notify_deepfield(event_type: str, payload: dict):
    """Push evaluation results to DeepField. Fails silently if not configured."""
    event = {
        "source": "stargate",
        "event_type": event_type,
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    await _push(DEEPFIELD_API_URL, DEEPFIELD_API_KEY, event)
    await _push_audit(event)


async def _push_audit(event: dict):
    """Push to dashboard central audit trail. Fails silently."""
    if not DASHBOARD_AUDIT_URL:
        return
    try:
        async with httpx.AsyncClient(verify=SSL_VERIFY, timeout=5.0) as client:
            await client.post(f"{DASHBOARD_AUDIT_URL}/api/audit/append", json=event)
    except Exception as e:
        logger.debug("Audit push failed (non-critical): %s", e)


async def notify_launchpad(session_id: str, result: str, errors: Optional[list[str]] = None):
    """Push cleanup results to Launchpad. Fails silently if not configured."""
    if not LAUNCHPAD_API_URL:
        return
    try:
        async with httpx.AsyncClient(verify=SSL_VERIFY, timeout=5.0) as client:
            headers = {"X-API-Key": LAUNCHPAD_API_KEY} if LAUNCHPAD_API_KEY else {}
            await client.post(
                f"{LAUNCHPAD_API_URL}/callbacks/cleanup-result",
                json={"session_id": session_id, "result": result, "errors": errors or []},
                headers=headers,
            )
    except Exception as e:
        logger.debug("StarGate -> Launchpad push failed (non-critical): %s", e)
