"""Shared state, caches, and helper functions used by all routers."""

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from slowapi import Limiter
from slowapi.util import get_remote_address

from db.database import get_db
from db import repository
from engine.models import Rubric

limiter = Limiter(key_func=get_remote_address)

# --- Event / operations config ---

EVENT_DATE = os.environ.get("STARGATE_EVENT_DATE", "")  # ISO date, e.g. "2026-05-11". Empty = continuous ops.
EVENT_NAME = os.environ.get("STARGATE_EVENT_NAME", "Platform Operations")
EVENT_PREFIX = os.environ.get("STARGATE_EVENT_PREFIX", "")  # e.g. "summit-2026". Empty = all pools.

# --- Execution target ---

EXECUTION_TARGET = os.environ.get("STARGATE_EXECUTION_TARGET", "mock")
EXECUTOR_KUBECONFIG = os.environ.get("STARGATE_EXECUTOR_KUBECONFIG", "")
TEST_NAMESPACE = os.environ.get("STARGATE_TEST_NAMESPACE", "stargate-test")

# --- Evidence source + dry-run + confidence ---

_evidence_source: str = os.environ.get("STARGATE_EVIDENCE_SOURCE", "real")
_synthetic_scenario: Optional[str] = None
_dry_run_enabled: bool = os.environ.get("STARGATE_DRY_RUN", "false").lower() == "true"
CONFIDENCE_THRESHOLD: float = float(os.environ.get("STARGATE_CONFIDENCE_THRESHOLD", "0.8"))

# --- Auth ---

ADMIN_API_KEY = os.environ.get("STARGATE_ADMIN_API_KEY", "")
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

if not ADMIN_API_KEY:
    logging.getLogger("stargate").warning(
        "STARGATE_ADMIN_API_KEY is not set — admin endpoints will reject all requests"
    )

CORS_ORIGINS = os.environ.get("STARGATE_CORS_ORIGINS", "http://localhost:3000,http://localhost:8090")
TRUST_PROXY_AUTH = os.environ.get("STARGATE_TRUST_PROXY_AUTH", "false").lower() == "true"


def _origin_from_url(url: str) -> str:
    """Extract origin (scheme://host[:port]) from a full URL."""
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.hostname:
            return ""
        origin = f"{parsed.scheme}://{parsed.hostname}"
        if parsed.port and not (
            (parsed.scheme == "http" and parsed.port == 80) or
            (parsed.scheme == "https" and parsed.port == 443)
        ):
            origin += f":{parsed.port}"
        return origin
    except ValueError:
        return ""


def require_admin(request: Request = None, api_key: str = Security(_api_key_header)):
    if api_key and ADMIN_API_KEY and api_key == ADMIN_API_KEY:
        return
    if request:
        if TRUST_PROXY_AUTH:
            oauth_user = request.headers.get("x-forwarded-user", "")
            if oauth_user:
                return
        fetch_site = request.headers.get("sec-fetch-site", "")
        if fetch_site == "same-origin":
            return
        origin = request.headers.get("origin", "")
        referer = request.headers.get("referer", "")
        allowed = [o.strip() for o in CORS_ORIGINS.split(",") if o.strip()]
        if origin and any(origin == a for a in allowed):
            return
        if referer:
            referer_origin = _origin_from_url(referer)
            if referer_origin and any(referer_origin == a for a in allowed):
                return
    if not ADMIN_API_KEY:
        raise HTTPException(status_code=503, detail="Admin API key not configured")
    raise HTTPException(status_code=403, detail="Invalid or missing API key")


# --- Module-level state ---

RUBRIC_DIR = Path(__file__).parent.parent.parent / "rubrics" / "platform"

PIPELINE_STAGES = [
    "cluster-health", "run-created", "provision-complete", "namespace-ready",
    "deployment-ready", "storage-clone-ready", "route-ready", "vm-runtime-ready",
    "smoke-test-ready", "showroom-healthy", "model-endpoint-ready",
]

# Event bus — singleton
from events.bus import EventBus
from events.nanoagents import create_default_pipeline
from events.consumers import LogConsumer

_event_bus = EventBus()
for _agent in create_default_pipeline():
    _event_bus.register_nanoagent(_agent)
_event_bus.register_consumer(LogConsumer())

# Scheduler
_scheduler = None
_scheduler_lock = __import__("threading").Lock()

# Shutdown
_shutdown_event = __import__("threading").Event()

# --- Caches ---

_scan_cache: Dict = {"data": [], "ts": 0.0}
_babylon_cache: Dict = {"data": {}, "ts": 0.0}
_labagator_cache: Dict = {"labs": None, "sessions": None, "ts": 0.0}
_demolition_cache: Dict = {"data": None, "ts": 0.0}
_deployments_cache: Dict = {"data": None, "ts": 0.0}
_constraints_cache: Dict[str, Dict] = {}
_constraints_cache_ts: float = 0
_rubric_cache: Dict[str, Rubric] = {}
_rubric_cache_ts: float = 0

_FILE_CACHE_TTL = 120
_EXTERNAL_CACHE_TTL = 120
_CONSTRAINTS_CACHE_TTL = 600
_RUBRIC_CACHE_TTL = 300


# --- File readers (TTL cached) ---

def _load_latest_scan() -> List[Dict]:
    """Load the most recent scan. Cached 30s. Tries live scheduler → files → DB."""
    if time.time() - _scan_cache["ts"] < _FILE_CACHE_TTL:
        return _scan_cache["data"]

    data: List[Dict] = []

    # Priority 1: live scheduler data
    if _scheduler and hasattr(_scheduler, 'workers'):
        for wt in _scheduler.workers:
            if wt.tick_count == 0 or not wt.last_result:
                continue
            r = wt.last_result
            nodes = r.get("nodes", {})
            # Pod data may not be in last_result if it was a Tier 1-only tick.
            # Check last_result first, then fall back to the most recent tier 2 result.
            pods = r.get("pods", {})
            if not pods.get("total_vms") and hasattr(wt, '_last_pod_result') and wt._last_pod_result:
                pods = wt._last_pod_result
            compute_nodes = nodes.get("compute_nodes", 1) or 1
            total_vms = pods.get("total_vms", 0)
            sandbox_active = pods.get("sandbox_active", 0)
            sandbox_failing = pods.get("sandbox_failing", 0)
            crashloops = pods.get("crashloops", 0)
            avg_cpu = nodes.get("avg_cpu", 0)
            hot_nodes = nodes.get("hot_nodes", 0)
            vms_per_node = round(total_vms / compute_nodes, 1) if compute_nodes else 0
            health_rate = round((sandbox_active - sandbox_failing) / max(sandbox_active, 1) * 100, 1) if sandbox_active > 0 else 0
            status = "critical" if avg_cpu and avg_cpu > 80 else "warning" if (avg_cpu and avg_cpu > 70) or hot_nodes > 0 else "healthy"
            data.append({
                "cluster": wt.worker.state.name,
                "timestamp": r.get("timestamp", ""),
                "nodes": nodes.get("total_nodes", 0),
                "compute_nodes": compute_nodes,
                "avg_cpu_pct": avg_cpu,
                "hot_nodes": hot_nodes,
                "sandbox_active": sandbox_active,
                "sandbox_failing": sandbox_failing,
                "sandbox_crashloop": crashloops,
                "total_vms": total_vms,
                "ocp4_cluster_labs": pods.get("ocp4_labs", 0),
                "vms_per_node": vms_per_node,
                "health_rate": health_rate,
                "status": status,
                "issues": [],
                "new_failures": pods.get("new_failures", [])[:10],
                "recovered": pods.get("recovered", [])[:10],
                "all_sandbox_namespaces": list(getattr(wt.worker.state, 'all_sandbox_namespaces', [])),
            })

    # Priority 2: scan-history files
    if not data:
        scan_dir = Path(__file__).parent.parent.parent / "scan-history"
        scan_files = sorted(scan_dir.glob("scan-*.json"), reverse=True)
        for scan_file in scan_files:
            with open(scan_file) as f:
                data = json.load(f)
            if len(data) > 1:
                break
        if not data and scan_files:
            with open(scan_files[0]) as f:
                data = json.load(f)

    # Priority 3: database
    if not data:
        try:
            db = next(get_db())
            db_data = repository.get_latest_scan_snapshot(db, "cluster_scan")
            db.close()
            if db_data:
                data = db_data if isinstance(db_data, list) else [db_data]
        except Exception:
            pass

    _scan_cache["data"] = data
    _scan_cache["ts"] = time.time()
    from api.contracts import record_source_fetch
    record_source_fetch("scanner")
    return data


def _load_latest_babylon() -> Dict:
    """Load the most recent babylon scan. Cached 30s. Tries files first, falls back to DB."""
    if time.time() - _babylon_cache["ts"] < _FILE_CACHE_TTL:
        return _babylon_cache["data"]

    data: Dict = {}

    # Try scan-history files first
    scan_dir = Path(__file__).parent.parent.parent / "scan-history"
    babylon_files = sorted(scan_dir.glob("babylon-*.json"), reverse=True)
    if babylon_files:
        with open(babylon_files[0]) as f:
            data = json.load(f)

    # Fall back to database
    if not data:
        try:
            db = next(get_db())
            db_data = repository.get_latest_scan_snapshot(db, "babylon_scan")
            db.close()
            if db_data and isinstance(db_data, dict):
                data = db_data
        except Exception:
            pass

    _babylon_cache["data"] = data
    _babylon_cache["ts"] = time.time()
    from api.contracts import record_source_fetch
    record_source_fetch("babylon")
    return data


# --- External API call helpers (TTL cached) ---

def _make_ssl_context():
    import ssl
    ctx = ssl.create_default_context()
    if os.environ.get("STARGATE_SSL_VERIFY", "true").lower() == "false":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _fetch_launchpad_catalog() -> List[Dict]:
    """Fetch catalog items from Launchpad API. Cached 60s. Used when Labagator unavailable."""
    cache_key = "_launchpad_catalog"
    if hasattr(_fetch_launchpad_catalog, cache_key):
        cached = getattr(_fetch_launchpad_catalog, cache_key)
        if cached["data"] is not None and time.time() - cached["ts"] < _EXTERNAL_CACHE_TTL:
            return cached["data"]

    launchpad_url = os.environ.get("STARGATE_LAUNCHPAD_URL", "")
    launchpad_key = os.environ.get("STARGATE_LAUNCHPAD_API_KEY", "")
    if not launchpad_url:
        return []
    import urllib.request as urllib_req
    import urllib.error
    try:
        req = urllib_req.Request(launchpad_url + "/catalog")
        if launchpad_key:
            req.add_header("X-API-Key", launchpad_key)
        resp = urllib_req.urlopen(req, timeout=15, context=_make_ssl_context())
        data = json.loads(resp.read())
        items = data if isinstance(data, list) else data.get("items", [])
        # Map to Labagator-compatible shape so frontend works
        labs = []
        for item in items:
            labs.append({
                "lab_code": item.get("catalog_item_id", ""),
                "title": item.get("display_name", item.get("catalog_item_id", "")),
                "status": item.get("status", "active"),
                "cloud": "openshift",
                "deploy_mode": item.get("provision_method", "direct"),
                "ci_name": item.get("catalog_item_id", ""),
            })
        setattr(_fetch_launchpad_catalog, cache_key, {"data": labs, "ts": time.time()})
        return labs
    except Exception as e:
        logging.getLogger("stargate").warning(f"Launchpad catalog fetch failed: {e}")
        return []


def _fetch_launchpad_sessions() -> List[Dict]:
    """Fetch active sessions from Launchpad API. Cached 60s."""
    cache_key = "_launchpad_sessions"
    if hasattr(_fetch_launchpad_sessions, cache_key):
        cached = getattr(_fetch_launchpad_sessions, cache_key)
        if cached["data"] is not None and time.time() - cached["ts"] < _EXTERNAL_CACHE_TTL:
            return cached["data"]

    launchpad_url = os.environ.get("STARGATE_LAUNCHPAD_URL", "")
    launchpad_key = os.environ.get("STARGATE_LAUNCHPAD_API_KEY", "")
    if not launchpad_url:
        return []
    import urllib.request as urllib_req
    import urllib.error
    try:
        req = urllib_req.Request(launchpad_url + "/lab-sessions")
        if launchpad_key:
            req.add_header("X-API-Key", launchpad_key)
        resp = urllib_req.urlopen(req, timeout=15, context=_make_ssl_context())
        data = json.loads(resp.read())
        sessions = data if isinstance(data, list) else data.get("sessions", [])
        # Map to Labagator-compatible session shape
        mapped = []
        for s in sessions:
            mapped.append({
                "lab_code": s.get("catalog_item_id", ""),
                "session_date": s.get("created_at", "")[:10] if s.get("created_at") else "",
                "status": s.get("state", "active"),
                "attendees": 1,
                "namespace": s.get("namespace", ""),
                "session_id": s.get("session_id", ""),
            })
        setattr(_fetch_launchpad_sessions, cache_key, {"data": mapped, "ts": time.time()})
        return mapped
    except Exception as e:
        logging.getLogger("stargate").warning(f"Launchpad sessions fetch failed: {e}")
        return []


def _fetch_labagator_labs() -> List[Dict]:
    """Fetch labs from Labagator API. Cached 60s. Falls back to Launchpad."""
    if _labagator_cache["labs"] is not None and time.time() - _labagator_cache["ts"] < _EXTERNAL_CACHE_TTL:
        return _labagator_cache["labs"]
    labagator_url = os.environ.get("STARGATE_LABAGATOR_URL", "")
    if not labagator_url:
        labs = _fetch_launchpad_catalog()
        _labagator_cache["labs"] = labs
        _labagator_cache["ts"] = time.time()
        return labs
    import urllib.request as urllib_req
    import urllib.error
    try:
        req = urllib_req.Request(
            labagator_url + "/labs/?limit=200"
        )
        resp = urllib_req.urlopen(req, timeout=15, context=_make_ssl_context())
        data = json.loads(resp.read())
        if isinstance(data, list):
            labs = data
        elif isinstance(data, dict):
            labs = data.get("results", data.get("labs", []))
        else:
            labs = []
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logging.getLogger("stargate").warning(f"Labagator labs fetch failed: {e}")
        labs = []
    from api.contracts import record_source_fetch
    record_source_fetch("labagator")
    _labagator_cache["labs"] = labs
    _labagator_cache["ts"] = time.time()
    return labs


def _fetch_labagator_sessions() -> List[Dict]:
    """Fetch sessions from Labagator API. Cached 60s. Falls back to Launchpad."""
    if _labagator_cache["sessions"] is not None and time.time() - _labagator_cache["ts"] < _EXTERNAL_CACHE_TTL:
        return _labagator_cache["sessions"]
    labagator_url = os.environ.get("STARGATE_LABAGATOR_URL", "")
    if not labagator_url:
        sessions = _fetch_launchpad_sessions()
        _labagator_cache["sessions"] = sessions
        return sessions
    import urllib.request as urllib_req
    import urllib.error
    try:
        req = urllib_req.Request(
            labagator_url + "/room-sessions/?limit=500"
        )
        resp = urllib_req.urlopen(req, timeout=15, context=_make_ssl_context())
        data = json.loads(resp.read())
        if isinstance(data, list):
            sessions = data
        elif isinstance(data, dict):
            sessions = data.get("results", data.get("sessions", []))
        else:
            sessions = []
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logging.getLogger("stargate").warning(f"Labagator sessions fetch failed: {e}")
        sessions = []
    _labagator_cache["sessions"] = sessions
    return sessions


def _fetch_demolition_sessions() -> List[Dict]:
    """Fetch sessions from Demolition API. Cached 60s."""
    if _demolition_cache["data"] is not None and time.time() - _demolition_cache["ts"] < _EXTERNAL_CACHE_TTL:
        return _demolition_cache["data"]
    demolition_url = os.environ.get("STARGATE_DEMOLITION_URL", "")
    if not demolition_url:
        _demolition_cache["data"] = []
        _demolition_cache["ts"] = time.time()
        return []
    import urllib.request as urllib_req
    import urllib.error
    try:
        req = urllib_req.Request(
            demolition_url + "/integration/sessions"
        )
        resp = urllib_req.urlopen(req, timeout=15, context=_make_ssl_context())
        data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logging.getLogger("stargate").warning(f"Demolition fetch failed: {e}")
        data = []
    _demolition_cache["data"] = data
    _demolition_cache["ts"] = time.time()
    from api.contracts import record_source_fetch
    record_source_fetch("demolition")
    return data


# --- Converters ---

def _scan_to_worker_format(s: Dict) -> Dict:
    """Convert a scan-history JSON entry to the same shape as wt.last_result."""
    return {
        "cluster": s.get("cluster", ""),
        "nodes": {
            "total_nodes": s.get("nodes", 0),
            "compute_nodes": s.get("compute_nodes", 0),
            "avg_cpu": s.get("avg_cpu_pct", 0),
            "hot_nodes": s.get("hot_nodes", 0),
            "status": s.get("status", "unknown"),
        },
        "pods": {
            "total_vms": s.get("total_vms", 0),
            "sandbox_active": s.get("sandbox_active", 0),
            "sandbox_failing": s.get("sandbox_failing", 0),
            "crashloops": s.get("sandbox_crashloop", 0),
            "ocp4_labs": s.get("ocp4_cluster_labs", 0),
            "vms_per_node": s.get("vms_per_node", 0),
            "new_failures": s.get("new_failures", []),
            "recovered": s.get("recovered", []),
        },
        "all_sandbox_namespaces": s.get("all_sandbox_namespaces", []),
    }


# --- Constraint + Rubric loaders ---

def _get_lab_namespaces(lab_code: str) -> List[str]:
    """Find sandbox namespaces for a lab from babylon data."""
    babylon = _load_latest_babylon()
    mapping = babylon.get("summit_mapping", {})
    instances = mapping.get(lab_code, [])
    return [i.get("namespace", "") for i in instances if i.get("namespace")]


AGNOSTICV_DIR = os.environ.get("STARGATE_AGNOSTICV_DIR", "")
_AGNOSTICV_SCAN_DIRS = [
    "summit-2026", "zt_rhel", "ansiblebu", "agd_v2", "ai-quickstarts",
    "openshift_cnv", "published", "rhdp", "sandboxes-gpte",
]


def _load_agnosticv_constraints(lab_code: Optional[str], ci_name: Optional[str] = None) -> Optional[Dict]:
    """Load AgnosticV constraints for a lab. Uses ci_name slug for exact match, falls back to prefix.  Cached 10 min."""
    global _constraints_cache_ts
    if not lab_code:
        return None
    if lab_code in _constraints_cache and time.time() - _constraints_cache_ts < _CONSTRAINTS_CACHE_TTL:
        return _constraints_cache[lab_code]

    from pathlib import Path
    agnosticv_dir = Path(AGNOSTICV_DIR) if AGNOSTICV_DIR else None
    if not agnosticv_dir or not agnosticv_dir.is_dir():
        for candidate in [
            Path(__file__).parent.parent.parent.parent / "agnosticv",
            Path.home() / "Documents" / "github review" / "agnosticv",
            Path.home() / "agnosticv",
        ]:
            if candidate.is_dir():
                agnosticv_dir = candidate
                break
    if not agnosticv_dir or not agnosticv_dir.is_dir():
        return None

    ci_slug = ""
    ci_event = ""
    if ci_name and "." in ci_name:
        parts = ci_name.split(".", 1)
        ci_event = parts[0]
        ci_slug = parts[1]

    lab_prefix = lab_code.lower().replace(" ", "")
    try:
        from constraints.agnosticv_loader import load_lab_constraints

        if ci_slug and ci_event:
            exact_path = agnosticv_dir / ci_event / ci_slug / "common.yaml"
            if exact_path.exists():
                constraints = load_lab_constraints(exact_path)
                _constraints_cache[lab_code] = constraints
                _constraints_cache_ts = time.time()
                return constraints

        for scan_dir_name in _AGNOSTICV_SCAN_DIRS:
            scan_dir = agnosticv_dir / scan_dir_name
            if not scan_dir.is_dir():
                continue
            if ci_slug:
                exact = scan_dir / ci_slug
                if exact.is_dir() and (exact / "common.yaml").exists():
                    constraints = load_lab_constraints(exact / "common.yaml")
                    _constraints_cache[lab_code] = constraints
                    _constraints_cache_ts = time.time()
                    return constraints
            for lab_dir in scan_dir.iterdir():
                if lab_dir.is_dir() and lab_dir.name.startswith(lab_prefix):
                    common = lab_dir / "common.yaml"
                    if common.exists():
                        constraints = load_lab_constraints(common)
                        _constraints_cache[lab_code] = constraints
                        _constraints_cache_ts = time.time()
                        return constraints
    except Exception:
        pass
    return None


def _load_rubric_for_stage(stage_id: str) -> Optional[Rubric]:
    """Load a rubric for a stage. Cached 5 min."""
    global _rubric_cache_ts
    if stage_id in _rubric_cache and time.time() - _rubric_cache_ts < _RUBRIC_CACHE_TTL:
        return _rubric_cache[stage_id]
    _load_all_rubrics()
    return _rubric_cache.get(stage_id)


def _load_all_rubrics():
    """Load all rubrics from disk."""
    global _rubric_cache_ts
    from engine.rubric_loader import load_rubrics_from_directory
    try:
        rubrics = load_rubrics_from_directory(RUBRIC_DIR)
        for r in rubrics:
            _rubric_cache[r.id] = r
        _rubric_cache_ts = time.time()
    except Exception as e:
        logging.getLogger("stargate").warning(f"Failed to load rubrics: {e}")
