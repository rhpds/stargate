"""Health and metrics endpoints."""

import os
import subprocess
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


def _check_llm_status() -> str:
    from api.llm import LLM_URL, LLM_API_KEY, _circuit
    if not LLM_URL:
        return "not_configured"
    if not LLM_API_KEY:
        return "no_api_key"
    if not _circuit.check():
        return "circuit_open"
    return "ok"


def _check_executor_kubeconfig() -> str:
    kc = os.environ.get("STARGATE_EXECUTOR_KUBECONFIG", "")
    if not kc:
        return "not_configured"
    if not os.path.exists(kc):
        return "file_missing"
    try:
        r = subprocess.run(
            ["oc", "whoami"], capture_output=True, text=True, timeout=5,
            env={**os.environ, "KUBECONFIG": kc},
        )
        return "ok" if r.returncode == 0 else "unauthorized"
    except Exception:
        return "unreachable"


def _check_sandbox_api() -> str:
    from collectors.sandbox_api.collect_sandbox_api import SANDBOX_API_METRICS_URL
    if not SANDBOX_API_METRICS_URL:
        return "not_configured"
    if ".svc:" in SANDBOX_API_METRICS_URL or ".svc/" in SANDBOX_API_METRICS_URL:
        import urllib.request
        try:
            urllib.request.urlopen(SANDBOX_API_METRICS_URL, timeout=3)
            return "ok"
        except Exception:
            return "unreachable_svc"
    return "ok"


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
                components["scanner_age_minutes"] = round(scan_age / 60, 1)
            except Exception:
                components["scanners"] = "unknown"

    components["llm"] = _check_llm_status()
    components["executor_kubeconfig"] = _check_executor_kubeconfig()
    components["sandbox_api"] = _check_sandbox_api()

    critical = ("api", "database")
    has_critical_error = any(components.get(k) == "error" for k in critical)
    all_ok = all(v == "ok" for k, v in components.items() if k != "scanner_age_minutes")
    overall = "error" if has_critical_error else "ok" if all_ok else "degraded"
    return {"status": overall, "service": "stargate", "components": components}
