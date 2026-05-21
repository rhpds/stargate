"""Health and metrics endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db.database import get_db
from api.routers._shared import _load_latest_scan

router = APIRouter()


@router.get("/metrics")
def metrics():
    from api.metrics import generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/health")
def health(db: Session = Depends(get_db)):
    components = {"api": "ok", "database": "unknown", "scanners": "unknown"}
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        components["database"] = "ok"
    except Exception:
        components["database"] = "error"

    scan_data = _load_latest_scan()
    if scan_data:
        ts = scan_data[0].get("timestamp", "")
        if ts:
            try:
                scan_age = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds()
                components["scanners"] = "ok" if scan_age < 600 else "stale"
            except Exception:
                components["scanners"] = "unknown"

    overall = "ok" if all(v == "ok" for v in components.values()) else "degraded"
    return {"status": overall, "service": "stargate", "components": components}
