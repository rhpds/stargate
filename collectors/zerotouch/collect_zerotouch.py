"""ZeroTouch collector — observe catalog items, service requests, and workshop availability.

Polls the ZeroTouch API (GET-only, read-only) for catalog item metadata,
active service request status, and workshop seat availability.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("stargate.zerotouch")

_cache: Dict[str, Any] = {"data": None, "ts": 0}
_CACHE_TTL = 300

ZEROTOUCH_URL = os.environ.get("STARGATE_ZEROTOUCH_URL", "")


def _fetch_json(url: str, timeout: int = 15) -> Optional[Dict]:
    """GET JSON from ZeroTouch API."""
    if not url:
        return None
    try:
        ctx = ssl.create_default_context()
        if os.environ.get("STARGATE_SSL_VERIFY", "true").lower() == "false":
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.debug(f"ZeroTouch fetch failed ({url}): {e}")
        return None


def collect_catalog_items(base_url: str = "") -> List[Dict]:
    """GET /catalogItems — available catalog items."""
    url = base_url or ZEROTOUCH_URL
    if not url:
        return []
    data = _fetch_json(f"{url.rstrip('/')}/catalogItems")
    if data is None:
        return []
    items = data if isinstance(data, list) else data.get("items", data.get("catalogItems", []))
    return [
        {
            "name": item.get("name", ""),
            "display_name": item.get("displayName", item.get("display_name", "")),
            "category": item.get("category", ""),
            "provider": item.get("provider", ""),
            "disabled": item.get("disabled", False),
        }
        for item in items
        if isinstance(item, dict)
    ]


def collect_workshop_availability(base_url: str = "", workshop_ids: Optional[List[str]] = None) -> Dict[str, Dict]:
    """GET /workshop/{id} — seat availability per workshop."""
    url = base_url or ZEROTOUCH_URL
    if not url or not workshop_ids:
        return {}
    results = {}
    for wid in workshop_ids:
        data = _fetch_json(f"{url.rstrip('/')}/workshop/{wid}")
        if data:
            results[wid] = {
                "seats_total": data.get("seats_total", data.get("seatsTotal", 0)),
                "seats_available": data.get("seats_available", data.get("seatsAvailable", 0)),
                "seats_claimed": data.get("seats_claimed", data.get("seatsClaimed", 0)),
            }
    return results


def summarize_zerotouch(base_url: str = "", workshop_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Full ZeroTouch summary — catalog + workshops."""
    now = time.time()
    if _cache["data"] and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["data"]

    url = base_url or ZEROTOUCH_URL
    catalog = collect_catalog_items(url)
    workshops = collect_workshop_availability(url, workshop_ids)

    active_items = [c for c in catalog if not c.get("disabled")]

    summary = {
        "available": url != "",
        "catalog_total": len(catalog),
        "catalog_active": len(active_items),
        "catalog_items": catalog[:20],
        "workshops": workshops,
        "workshop_count": len(workshops),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        from api.contracts import record_source_fetch
        record_source_fetch("zerotouch")
    except Exception:
        pass

    _cache["data"] = summary
    _cache["ts"] = now
    return summary
