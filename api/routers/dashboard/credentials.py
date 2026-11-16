"""Credential health views — the live answer to "is this credential working?".

Reads the latest `credential-health` evaluation per credential. Results are
produced by collectors/credential_health.py on a background loop, so a page
load never blocks on eleven `oc whoami` calls.

The 2026 Turkey Vulture rotation (GPTEINFRA-18544) is why this exists: a
reachability probe calls a 401 a pass, nothing tracks expiry, and a credential
rotated in one place can stay dead in another with no signal.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from db.database import get_db

logger = logging.getLogger("stargate.dashboard.credentials")

router = APIRouter()

STAGE = "credential-health"


def _days_left(expires_at: Any) -> Any:
    if not expires_at:
        return None
    try:
        parsed = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, (parsed - datetime.now(timezone.utc)).days)


def latest_credentials(db: Session) -> List[Dict[str, Any]]:
    """Most recent evaluation per credential, newest first."""
    from db.models import EvaluationRecord

    rows = (
        db.query(EvaluationRecord)
        .filter(EvaluationRecord.stage_id == STAGE)
        .order_by(EvaluationRecord.id.desc())
        .limit(2000)
        .all()
    )

    seen = {}
    for row in rows:
        name = row.cluster_name or "unknown"
        if name in seen:
            continue
        detail = (row.criteria_results or [{}])[0] if row.criteria_results else {}
        seen[name] = {
            "credential": name,
            "kind": detail.get("kind"),
            "source": detail.get("source"),
            "outcome": row.outcome,
            "failure_class": row.failure_class,
            "message": row.message or "",
            "status": detail.get("status"),
            "expires_at": detail.get("expires_at"),
            "days_left": _days_left(detail.get("expires_at")),
            "checked_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
        }
    return sorted(seen.values(), key=lambda c: (c["outcome"] != "fail", c["credential"]))


def _summary(credentials: List[Dict[str, Any]]) -> Dict[str, int]:
    return {
        "total": len(credentials),
        "verified": sum(1 for c in credentials if c["outcome"] == "pass"),
        "degraded": sum(1 for c in credentials if c["outcome"] == "warn"),
        "rejected": sum(1 for c in credentials if c["outcome"] == "fail"),
        "expiring": sum(
            1 for c in credentials
            if c.get("days_left") is not None and c["days_left"] <= 90
        ),
    }


@router.get("/dashboard/credentials")
def dashboard_credentials(
    refresh: bool = Query(False, description="Probe now instead of using the loop's last result"),
    db: Session = Depends(get_db),
):
    """Credential liveness, expiry and last verification for every credential."""
    if refresh:
        try:
            from collectors.credential_health import run_credential_check
            run_credential_check(db=db, force=True)
        except Exception as exc:  # noqa: BLE001 — serve the last known state
            logger.warning("On-demand credential probe failed: %s", exc)

    credentials = latest_credentials(db)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": _summary(credentials),
        "credentials": credentials,
    }
