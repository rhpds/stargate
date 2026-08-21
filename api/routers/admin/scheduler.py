"""Admin scheduler management and scan history endpoints."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from api.routers._shared import (
    limiter,
    _scheduler,
    _scheduler_lock,
    require_admin,
    require_admin_read,
)

router = APIRouter()

logger = logging.getLogger("stargate.admin.scheduler")


# ---------------------------------------------------------------------------
# Scheduler management
# ---------------------------------------------------------------------------

@router.post("/admin/scheduler/start", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
def admin_scheduler_start(
    request: Request,
    tier1: int = 300,
    tier2: int = 900,
    tier3: int = 3600,
    batch: int = 5,

):
    """Start the scanner scheduler."""
    from api.routers._shared import _scheduler as _sched
    import api.routers._shared as _shared

    with _scheduler_lock:
        if _shared._scheduler is not None:
            return {"status": "already_running", "workers": len(_shared._scheduler.workers)}

        from cli.scheduler import Scheduler
        from cli.scan import CLUSTERS

        _shared._scheduler = Scheduler(
            clusters=CLUSTERS,
            api_url="http://localhost:8090",
            tier1=tier1,
            tier2=tier2,
            tier3=tier3,
            tier3_batch=batch,
        )
        available, unavailable = _shared._scheduler.start()
        _shared._scheduler._start_result = {"available": available, "unavailable": unavailable}
        return {
            "status": "started",
            "available": available,
            "unavailable": unavailable,
        }


@router.post("/admin/scheduler/stop", dependencies=[Depends(require_admin)])
def admin_scheduler_stop():
    """Stop the scanner scheduler."""
    import api.routers._shared as _shared

    with _scheduler_lock:
        if _shared._scheduler is None:
            return {"status": "not_running"}
        _shared._scheduler.stop()
        _shared._scheduler = None
        return {"status": "stopped"}


@router.get("/admin/scheduler/status", dependencies=[Depends(require_admin_read)])
def admin_scheduler_status():
    """Get scheduler worker status."""
    import api.routers._shared as _shared

    if _shared._scheduler is None:
        scan_dir = Path(__file__).parent.parent.parent.parent / "scan-history"
        scan_files = sorted(scan_dir.glob("scan-*.json"), reverse=True)
        last_scan = None
        if scan_files:
            try:
                fname = scan_files[0].stem
                last_scan = __import__("datetime").datetime.strptime(
                    fname, "scan-%Y%m%d-%H%M%S"
                ).replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                pass

        # Load latest scan per cluster even when stopped
        latest_scans: Dict[str, Dict] = {}
        for scan_file in sorted(scan_dir.glob("scan-*.json"), reverse=True):
            try:
                fname = scan_file.stem
                file_ts = datetime.strptime(fname, "scan-%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
                with open(scan_file) as f:
                    scans_data = json.load(f)
                for s in scans_data:
                    cname = s.get("cluster", "")
                    if cname and cname not in latest_scans:
                        latest_scans[cname] = {
                            "scan_time": file_ts.isoformat(),
                            "status": s.get("status"),
                            "avg_cpu_pct": s.get("avg_cpu_pct"),
                            "total_vms": s.get("total_vms"),
                            "vms_per_node": s.get("vms_per_node"),
                            "health_rate": s.get("health_rate"),
                            "sandbox_active": s.get("sandbox_active"),
                            "sandbox_failing": s.get("sandbox_failing"),
                            "sandbox_crashloop": s.get("sandbox_crashloop"),
                            "hot_nodes": s.get("hot_nodes"),
                            "issues": s.get("issues", []),
                        }
            except (ValueError, json.JSONDecodeError):
                continue

        return {
            "running": False,
            "workers": [],
            "last_scan": last_scan,
            "scan_files": len(list(scan_dir.glob("scan-*.json"))),
            "latest_scans": latest_scans,
        }

    workers = []
    for wt in _shared._scheduler.workers:
        w = {
            "cluster": wt.worker.state.name,
            "running": wt.running,
            "ticks": wt.tick_count,
            "errors": wt.error_count,
            "offset": wt.offset,
            "tier1_interval": wt.worker.TIER1_INTERVAL,
            "tier2_interval": wt.worker.TIER2_INTERVAL,
            "tier3_interval": wt.worker.TIER3_INTERVAL,
        }

        state = wt.worker.state
        w["last_node_scan"] = state.last_node_scan if state.last_node_scan else None
        w["last_pod_scan"] = state.last_pod_scan if state.last_pod_scan else None
        w["last_ns_scan"] = state.last_ns_scan if state.last_ns_scan else None
        w["active_sandboxes"] = len(state.known_sandboxes) if hasattr(state, "known_sandboxes") else 0
        w["failing_sandboxes"] = len(state.failing_sandboxes) if hasattr(state, "failing_sandboxes") else 0

        if wt.last_result:
            r = wt.last_result
            nodes = r.get("nodes", {})
            pods = r.get("pods", {})
            ns_data = r.get("namespaces", {})
            w["avg_cpu"] = nodes.get("avg_cpu", 0)
            w["hot_nodes"] = nodes.get("hot_nodes", 0)
            w["node_status"] = nodes.get("status", "unknown")
            w["total_vms"] = pods.get("total_vms", 0)
            w["vms_per_node"] = pods.get("vms_per_node", 0)
            w["crashloops"] = pods.get("crashloops", 0)
            w["new_failures"] = len(pods.get("new_failures", []))
            w["recovered"] = len(pods.get("recovered", []))
            w["ns_scanned"] = ns_data.get("total_scanned", 0)
            w["ns_available"] = ns_data.get("total_available", 0)
            if pods.get("new_failures"):
                w["recent_failures"] = pods["new_failures"][:5]
        else:
            w["node_status"] = "pending"

        workers.append(w)

    babylon = None
    if hasattr(_shared._scheduler, "_babylon_result") and _shared._scheduler._babylon_result:
        br = _shared._scheduler._babylon_result
        if "error" not in br:
            pools = br.get("pools", {})
            prov = br.get("provisioning", {})
            babylon = {
                "total_pools": pools.get("total_pools", 0),
                "exhausted": len(pools.get("exhausted", [])),
                "low": len(pools.get("low", [])),
                "total_subjects": prov.get("total", 0),
                "started": prov.get("started", 0),
                "failed": prov.get("failed", 0),
            }

    # Include latest scan snapshot per cluster (from scan-history files)
    scan_dir = Path(__file__).parent.parent.parent.parent / "scan-history"
    latest_scans: Dict[str, Dict] = {}
    for scan_file in sorted(scan_dir.glob("scan-*.json"), reverse=True):
        try:
            fname = scan_file.stem
            file_ts = datetime.strptime(fname, "scan-%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
            with open(scan_file) as f:
                scans = json.load(f)
            for s in scans:
                cname = s.get("cluster", "")
                if cname and cname not in latest_scans:
                    latest_scans[cname] = {
                        "scan_time": file_ts.isoformat(),
                        "status": s.get("status"),
                        "avg_cpu_pct": s.get("avg_cpu_pct"),
                        "total_vms": s.get("total_vms"),
                        "vms_per_node": s.get("vms_per_node"),
                        "health_rate": s.get("health_rate"),
                        "sandbox_active": s.get("sandbox_active"),
                        "sandbox_failing": s.get("sandbox_failing"),
                        "sandbox_crashloop": s.get("sandbox_crashloop"),
                        "hot_nodes": s.get("hot_nodes"),
                        "issues": s.get("issues", []),
                    }
        except (ValueError, json.JSONDecodeError):
            continue

    # Overlay live worker data onto latest_scans when fresher
    for wt in _shared._scheduler.workers:
        if wt.tick_count == 0 or not wt.last_result:
            continue
        cname = wt.worker.state.name
        r = wt.last_result
        nodes = r.get("nodes", {})
        pods = r.get("pods", {})
        latest_scans[cname] = {
            "scan_time": datetime.now(timezone.utc).isoformat(),
            "status": nodes.get("status", "unknown"),
            "avg_cpu_pct": nodes.get("avg_cpu"),
            "total_vms": pods.get("total_vms", 0),
            "vms_per_node": pods.get("vms_per_node", 0),
            "health_rate": pods.get("health_rate", 0),
            "sandbox_active": pods.get("sandbox_active", 0),
            "sandbox_failing": pods.get("sandbox_failing", 0),
            "sandbox_crashloop": pods.get("crashloops", 0),
            "hot_nodes": nodes.get("hot_nodes", 0),
            "issues": nodes.get("issues", []),
            "source": "live",
        }

    start_result = getattr(_shared._scheduler, "_start_result", {})

    return {
        "running": True,
        "workers": workers,
        "babylon": babylon,
        "worker_count": len(workers),
        "available_clusters": start_result.get("available", []),
        "unavailable_clusters": start_result.get("unavailable", []),
        "latest_scans": latest_scans,
    }


# ---------------------------------------------------------------------------
# Scan history
# ---------------------------------------------------------------------------

@router.get("/admin/scan-history", dependencies=[Depends(require_admin_read)])
def admin_scan_history(limit: int = 50):
    """Return scan history timeline from scan-history files."""
    scan_dir = Path(__file__).parent.parent.parent.parent / "scan-history"
    scan_files = sorted(scan_dir.glob("scan-*.json"), reverse=True)[:limit]

    timeline = []
    for scan_file in reversed(scan_files):
        try:
            fname = scan_file.stem
            file_ts = datetime.strptime(fname, "scan-%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
            with open(scan_file) as f:
                scans = json.load(f)
            entry = {
                "timestamp": file_ts.isoformat(),
                "clusters": {},
            }
            for s in scans:
                cname = s.get("cluster", "")
                if cname:
                    entry["clusters"][cname] = {
                        "status": s.get("status"),
                        "avg_cpu_pct": s.get("avg_cpu_pct"),
                        "total_vms": s.get("total_vms", 0),
                        "vms_per_node": s.get("vms_per_node", 0),
                        "health_rate": s.get("health_rate", 0),
                        "sandbox_active": s.get("sandbox_active", 0),
                        "sandbox_failing": s.get("sandbox_failing", 0),
                    }
            timeline.append(entry)
        except (ValueError, json.JSONDecodeError):
            continue

    return {"timeline": timeline, "total_files": len(list(scan_dir.glob("scan-*.json")))}
