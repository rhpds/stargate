"""Notification engine — fires webhooks on critical state changes.

Called from MV refresh loop. Compares current state to previous cycle
and fires webhook for new critical events. Avoids repeat notifications.

Configure via STARGATE_WEBHOOK_URL env var.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from sqlalchemy.orm import Session

logger = logging.getLogger("stargate.notifications")

WEBHOOK_URL = os.environ.get("STARGATE_WEBHOOK_URL", "")
_notified_keys: Set[str] = set()


def check_and_notify(db: Session) -> Dict:
    """Check for critical state changes and fire notifications."""
    if not WEBHOOK_URL:
        return {"notifications_sent": 0, "reason": "no webhook configured"}

    from engine.policy import generate_recommendations

    notifications = []

    try:
        from api.routers._shared import _load_latest_scan, _load_latest_babylon
        scan_data = _load_latest_scan()
        babylon_data = _load_latest_babylon()

        labs = babylon_data.get("labagator", {}).get("labs", [])
        if not isinstance(labs, list):
            labs = list(babylon_data.get("labagator", {}).get("labs_by_code", {}).values())
        pools = babylon_data.get("pools", {})
        cluster_states = scan_data if isinstance(scan_data, list) else []
        sessions = []

        result = generate_recommendations(labs, pools, cluster_states, sessions)

        for rec in result.get("recommendations", []):
            if rec.get("urgency") not in ("critical", "high"):
                continue
            key = f"{rec['type']}:{rec.get('lab_code', rec.get('cluster', rec.get('pool_name', '')))}"
            if key in _notified_keys:
                continue
            _notified_keys.add(key)
            notifications.append({
                "type": rec["type"],
                "urgency": rec["urgency"],
                "target": rec.get("lab_code") or rec.get("cluster") or rec.get("pool_name", ""),
                "message": rec.get("recommendation", ""),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        logger.debug(f"Notification check failed: {e}")
        return {"notifications_sent": 0, "error": str(e)}

    sent = 0
    for notif in notifications[:5]:
        try:
            _send_webhook(notif)
            sent += 1
        except Exception as e:
            logger.warning(f"Webhook failed: {e}")

    if sent > 0:
        logger.info(f"Sent {sent} notification(s)")

    return {"notifications_sent": sent, "total_critical": len(notifications)}


def _send_webhook(payload: Dict):
    """Send a webhook notification."""
    body = json.dumps({
        "text": f"[StarGate {payload['urgency'].upper()}] {payload['type']}: {payload['message']}",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{payload['urgency'].upper()}*: {payload['type']}\n{payload['message']}\nTarget: `{payload['target']}`",
                },
            },
        ],
    }).encode()

    req = urllib.request.Request(
        WEBHOOK_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=10)
