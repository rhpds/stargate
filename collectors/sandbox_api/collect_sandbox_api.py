"""Sandbox-API collector — observe Babylon Sandbox API health and sandbox counts.

Scrapes Prometheus metrics from sandbox-api service (read-only HTTP GET).
Aggregates sandbox namespace counts from existing scanner data.
"""

from __future__ import annotations

import json
import logging
import os
import re
import ssl
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("stargate.sandbox_api")

_cache: Dict[str, Any] = {"data": None, "ts": 0}
_CACHE_TTL = 300

SANDBOX_API_METRICS_URL = os.environ.get(
    "STARGATE_SANDBOX_API_METRICS_URL",
    "http://sandbox-api.babylon-sandbox-api.svc:8080/metrics",
)


def _parse_prometheus_metrics(text: str) -> Dict[str, Any]:
    """Parse Prometheus text format into structured data."""
    metrics: Dict[str, Any] = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        match = re.match(r'^(\w+)(\{(.+)\})?\s+(.+)$', line)
        if not match:
            continue
        name, _, labels_str, value = match.groups()
        try:
            val = float(value)
        except ValueError:
            continue

        if labels_str:
            labels = dict(re.findall(r'(\w+)="([^"]*)"', labels_str))
            metrics.setdefault(name, []).append({"labels": labels, "value": val})
        else:
            metrics[name] = val
    return metrics


def collect_sandbox_api_health() -> Dict[str, Any]:
    """Check sandbox-api health by scraping its Prometheus metrics endpoint."""
    result: Dict[str, Any] = {
        "api_healthy": False,
        "replicas_desired": 0,
        "replicas_ready": 0,
        "pod_statuses": [],
        "api_version": None,
        "ratelimit_by_cluster": {},
        "queue_depth": 0,
        "db_connections_active": 0,
        "db_connections_idle": 0,
    }

    try:
        ctx = ssl.create_default_context()
        if os.environ.get("STARGATE_SSL_VERIFY", "true").lower() == "false":
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(SANDBOX_API_METRICS_URL)
        resp = urllib.request.urlopen(req, timeout=10, context=ctx)
        raw = resp.read().decode()
        metrics = _parse_prometheus_metrics(raw)

        result["api_healthy"] = True

        if isinstance(metrics.get("sandbox_pg_connections_active"), (int, float)):
            result["db_connections_active"] = int(metrics["sandbox_pg_connections_active"])
        if isinstance(metrics.get("sandbox_pg_connections_idle"), (int, float)):
            result["db_connections_idle"] = int(metrics["sandbox_pg_connections_idle"])
        if isinstance(metrics.get("sandbox_queued_placements_total"), (int, float)):
            result["queue_depth"] = int(metrics["sandbox_queued_placements_total"])

        ratelimit_avail = metrics.get("sandbox_ratelimit_available_slots", [])
        ratelimit_max = metrics.get("sandbox_ratelimit_max", [])
        if isinstance(ratelimit_avail, list):
            max_by_cluster = {}
            if isinstance(ratelimit_max, list):
                max_by_cluster = {e["labels"]["cluster"]: int(e["value"]) for e in ratelimit_max}
            for entry in ratelimit_avail:
                cluster = entry["labels"].get("cluster", "")
                if cluster:
                    result["ratelimit_by_cluster"][cluster] = {
                        "available": int(entry["value"]),
                        "max": max_by_cluster.get(cluster, 0),
                    }

    except Exception as e:
        logger.debug(f"Sandbox-API metrics scrape failed: {e}")

    return result


def collect_sandbox_counts(scanner_data: List[Dict]) -> Dict[str, Any]:
    """Aggregate sandbox namespace counts from existing scanner data."""
    total_active = 0
    total_failing = 0
    total_crashloop = 0
    by_cluster: Dict[str, Dict] = {}

    for scan in scanner_data:
        cluster = scan.get("cluster", "unknown")
        active = scan.get("sandbox_active", 0) or 0
        failing = scan.get("sandbox_failing", 0) or 0
        crashloop = scan.get("sandbox_crashloop", 0) or 0
        total_active += active
        total_failing += failing
        total_crashloop += crashloop
        by_cluster[cluster] = {
            "active": active,
            "failing": failing,
            "crashloop": crashloop,
        }

    return {
        "total_sandboxes": total_active + total_failing,
        "active": total_active,
        "failing": total_failing,
        "crashloop": total_crashloop,
        "by_cluster": by_cluster,
    }


def summarize_sandbox_api(kubeconfig: str = "", scanner_data: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """Full sandbox-api summary — health + sandbox counts."""
    now = time.time()
    if _cache["data"] and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["data"]

    health = collect_sandbox_api_health()
    counts = collect_sandbox_counts(scanner_data or [])

    summary = {
        **health,
        **counts,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        from api.contracts import record_source_fetch
        record_source_fetch("sandbox_api")
    except Exception:
        pass

    _cache["data"] = summary
    _cache["ts"] = now
    return summary
