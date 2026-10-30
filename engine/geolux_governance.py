"""GeoLux governance integration: pre-approval constraint checks.

GeoLux is the constraint authority of the governed-inference platform.
Before a human approves an investigation-sourced remediation, StarGate asks
GeoLux's classification engine (POST /classify) whether the proposed action
satisfies the active constraints.

The check is advisory with a deliberate human override: GeoLux advises,
the human decides, StarGate's gated executor acts. An "unsafe" verdict
blocks execution until the human reviews the check and re-approves with
force; "safe" and "unknown" (including GeoLux unreachable) proceed. This
module never executes anything.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger("stargate.geolux")


def geolux_precheck(
    action_type: str,
    target: str,
    parameters: Optional[Dict] = None,
    cluster: str = "",
) -> Dict:
    """Ask GeoLux to classify a proposed remediation against its constraints.

    Returns {"verdict": "safe"|"unsafe"|"unknown", "constraint_results": [...],
    "reasons": [...], "checked_at": iso8601}. Fail-open ("unknown") on any
    error: GeoLux being unreachable never blocks human authority.
    """
    parameters = parameters or {}
    url = os.environ.get("STARGATE_GEOLUX_URL", "")
    if not url:
        return _unknown(["STARGATE_GEOLUX_URL not set"])

    api_key = os.environ.get("STARGATE_GEOLUX_API_KEY", os.environ.get("STARGATE_ADMIN_API_KEY", ""))
    evidence = {
        "action_type": action_type,
        "target_namespace": target,
        "failure_class": str(parameters.get("failure_class", "")),
        "cluster": cluster or str(parameters.get("cluster", "")),
        "remediation_id": action_type,
        "remediation_suggestion": str(parameters.get("remediation_suggestion", ""))[:500],
        "source": "stargate_approval_precheck",
    }
    payload = {"evidence": evidence, "stage": "remediation"}

    try:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        req = urllib.request.Request(
            f"{url.rstrip('/')}/classify",
            data=json.dumps(payload).encode(),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
    except Exception as error:
        logger.info("GeoLux precheck unreachable: %s", str(error)[:150])
        return _unknown([f"geolux unreachable: {str(error)[:150]}"])

    constraint_results = result.get("results") or []
    fails, passes, reasons = [], 0, []
    for entry in constraint_results:
        outcome = str(entry.get("result", "")).lower()
        constraint_id = entry.get("constraint_id", "unknown")
        if outcome == "fail":
            fails.append(constraint_id)
            reasons.append(f"constraint {constraint_id} failed")
        elif outcome == "pass":
            passes += 1

    if fails:
        verdict = "unsafe"
    elif passes:
        verdict = "safe"
        reasons = [f"{passes} constraint(s) passed"]
    else:
        return _unknown(["no constraint produced a decisive result"], constraint_results)

    return {
        "verdict": verdict,
        "constraint_results": [
            {
                "constraint_id": entry.get("constraint_id"),
                "result": entry.get("result"),
                "confidence": entry.get("confidence_score"),
            }
            for entry in constraint_results
        ],
        "reasons": reasons,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _unknown(reasons, constraint_results=None) -> Dict:
    return {
        "verdict": "unknown",
        "reasons": reasons,
        "constraint_results": constraint_results or [],
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
