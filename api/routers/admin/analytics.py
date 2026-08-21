"""Admin analytics — Deepfield/GeoLux proxy endpoints."""

import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends

from api.routers._shared import require_admin_read

logger = logging.getLogger("stargate.admin.analytics")

router = APIRouter()


# ---------------------------------------------------------------------------
# Deepfield / GeoLux proxy endpoints
# ---------------------------------------------------------------------------

def _proxy_get(url: str, headers: Optional[dict] = None, timeout: int = 15) -> dict:
    """Fetch JSON from an internal service URL."""
    import urllib.request
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)[:200]}


def _proxy_parallel(calls: List[tuple]) -> dict:
    """Fetch multiple URLs in parallel. calls = [(key, url, headers), ...]"""
    from concurrent.futures import ThreadPoolExecutor
    results = {}

    def _fetch(key, url, headers):
        results[key] = _proxy_get(url, headers)

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        for key, url, headers in calls:
            pool.submit(_fetch, key, url, headers)

    return results


@router.get("/admin/deepfield/overview")
def deepfield_overview(_auth=Depends(require_admin_read)):
    """Proxy Deepfield metrics + incidents for the StarGate dashboard."""
    import os
    base = os.environ.get("STARGATE_DEEPFIELD_INTERNAL_URL", "http://deepfield-backend.deepfield.svc:8099")

    r = _proxy_parallel([
        ("metrics", f"{base}/api/v1/metrics?window=1h", None),
        ("incidents", f"{base}/api/v1/incidents?limit=50", None),
        ("clusters", f"{base}/api/v1/observatory/clusters", None),
    ])

    incidents = r.get("incidents", {})
    clusters = r.get("clusters", {})
    return {
        "metrics": r.get("metrics", {}),
        "incidents": incidents.get("incidents", []) if isinstance(incidents, dict) else [],
        "incident_count": incidents.get("count", 0) if isinstance(incidents, dict) else 0,
        "clusters": clusters.get("clusters", {}) if isinstance(clusters, dict) else {},
    }


@router.get("/admin/geolux/overview")
def geolux_overview(_auth=Depends(require_admin_read)):
    """Proxy GeoLux governance pipeline + stability for the StarGate dashboard."""
    import os
    base = os.environ.get("STARGATE_GEOLUX_URL", "http://geolux-geolux.geolux.svc:8091")
    api_key = os.environ.get("STARGATE_GEOLUX_API_KEY", "")
    headers = {"X-API-Key": api_key} if api_key else {}

    r = _proxy_parallel([
        ("stability", f"{base}/stability/scores?limit=20", headers),
        ("thresholds", f"{base}/stability/thresholds", headers),
        ("hyp_stats", f"{base}/hypotheses/stats", headers),
        ("mpc_stats", f"{base}/mpc/stats", headers),
        ("constraints", f"{base}/classify/constraints", headers),
        ("classifications", f"{base}/classify/recent?limit=50", headers),
        ("routing", f"{base}/deepfield/routing-history?limit=10", headers),
        ("queue", f"{base}/hypotheses/queue?limit=10", headers),
    ])

    stability = r.get("stability", {})
    thresholds = r.get("thresholds", {})
    hyp_stats = r.get("hyp_stats", {})
    mpc_stats = r.get("mpc_stats", {})
    constraints = r.get("constraints", [])
    classifications = r.get("classifications", [])
    queue = r.get("queue", {})
    routing = r.get("routing", [])

    cls_pass = sum(1 for c in classifications if isinstance(c, dict) and c.get("result") == "pass") if isinstance(classifications, list) else 0
    cls_fail = sum(1 for c in classifications if isinstance(c, dict) and c.get("result") == "fail") if isinstance(classifications, list) else 0
    cls_inc = sum(1 for c in classifications if isinstance(c, dict) and c.get("result") == "inconclusive") if isinstance(classifications, list) else 0

    pipeline = {
        "classifications": {"total": len(classifications) if isinstance(classifications, list) else 0, "pass": cls_pass, "fail": cls_fail, "inconclusive": cls_inc},
        "hypotheses": {"total": hyp_stats.get("total", 0), "pending": hyp_stats.get("pending", 0), "validated": hyp_stats.get("validated", 0), "falsified": hyp_stats.get("falsified", 0)},
        "actions": {"mpc_cycles": mpc_stats.get("total", 0), "mpc_suspended": mpc_stats.get("suspended", 0)},
        "top_failure_classes": hyp_stats.get("failure_classes", []),
        "clusters": hyp_stats.get("clusters", []) if not isinstance(mpc_stats.get("clusters"), list) else mpc_stats["clusters"],
    }

    # Learned patterns (non-blocking — may not exist yet)
    learning = _proxy_get(f"{base}/learning/patterns", headers)

    return {
        "pipeline": pipeline,
        "stability_scores": stability if isinstance(stability, list) else [],
        "stability_threshold": thresholds.get("stability_threshold", 0.7) if isinstance(thresholds, dict) else 0.7,
        "hypothesis_stats": hyp_stats,
        "mpc_stats": mpc_stats,
        "constraints_count": len(constraints) if isinstance(constraints, list) else 0,
        "recent_hypotheses": queue.get("hypotheses", [])[:10] if isinstance(queue, dict) else [],
        "recent_routing": routing if isinstance(routing, list) else [],
        "learned_patterns": learning.get("patterns", []) if isinstance(learning, dict) else [],
    }
