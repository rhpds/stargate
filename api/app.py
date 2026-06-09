"""StarGate API — FastAPI service for evidence submission, evaluation, and reporting.

Thin shell that configures middleware, lifecycle hooks, and includes domain routers.
All endpoint implementations live in api/routers/*.py.
"""

import logging
import os
import time as _time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from db.database import get_db, init_db
from db import repository

from api.routers._shared import _event_bus, _shutdown_event, limiter

app = FastAPI(
    title="StarGate",
    description="Centralized validation layer for RHDP — evidence collection, rubric evaluation, failure classification, and event processing",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# --- Rate limiting + Middleware ---

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(GZipMiddleware, minimum_size=1000)

_cors_origins = os.environ.get("STARGATE_CORS_ORIGINS", "http://localhost:3000,http://localhost:8090").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    import uuid
    from api.metrics import http_requests_total, http_request_duration
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
    request.state.request_id = request_id
    start = _time.time()
    response = await call_next(request)
    duration = _time.time() - start
    duration_ms = int(duration * 1000)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "0"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    path = request.url.path
    if path not in ("/health", "/docs", "/redoc", "/openapi.json", "/metrics"):
        logging.getLogger("stargate.http").info(
            f"{request.method} {path} → {response.status_code} ({duration_ms}ms) [{request_id}]"
        )
        http_requests_total.labels(method=request.method, path=path, status=response.status_code).inc()
        http_request_duration.labels(method=request.method, path=path).observe(duration)
    return response


# --- Lifecycle ---

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
logging.getLogger("stargate").setLevel(logging.INFO)


def _clone_agnosticv():
    """Clone or update the AgnosticV repo if token is configured."""
    token = os.environ.get("STARGATE_AGNOSTICV_TOKEN", "")
    repo = os.environ.get("STARGATE_AGNOSTICV_REPO", "https://github.com/rhpds/agnosticv.git")
    target = os.environ.get("STARGATE_AGNOSTICV_DIR", "")
    if not token:
        return
    if not target:
        target = "/opt/app-root/src/agnosticv"
        os.environ["STARGATE_AGNOSTICV_DIR"] = target
    logger = logging.getLogger("stargate")
    import subprocess
    from pathlib import Path
    target_path = Path(target)
    import tempfile
    cred_file = None
    try:
        cred_fd, cred_path = tempfile.mkstemp(prefix="stargate-git-cred-")
        os.write(cred_fd, f"https://{token}:x-oauth-basic@github.com\n".encode())
        os.close(cred_fd)
        os.chmod(cred_path, 0o600)
        cred_file = cred_path

        env = {**os.environ, "GIT_ASKPASS": "/bin/echo"}
        clone_env = {
            **env,
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "credential.helper",
            "GIT_CONFIG_VALUE_0": f"store --file={cred_path}",
        }
        if target_path.exists() and (target_path / ".git").exists():
            subprocess.run(["git", "-C", str(target_path), "pull", "--ff-only"], capture_output=True, timeout=60, env=clone_env)
            logger.info(f"AgnosticV repo updated at {target}")
        else:
            target_path.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "clone", "--depth", "1", repo, str(target_path)], capture_output=True, timeout=120, env=clone_env)
            logger.info(f"AgnosticV repo cloned to {target}")
    except Exception as e:
        logger.warning(f"AgnosticV clone failed: {e}")
    finally:
        if cred_file and os.path.exists(cred_file):
            os.unlink(cred_file)


def _register_event_consumers():
    """Register cross-product event consumers on the event bus."""
    logger = logging.getLogger("stargate")
    try:
        from api.routers._shared import _event_bus
        from events.consumers import DeepFieldConsumer, GeoLuxConsumer
        consumer = DeepFieldConsumer()
        if consumer.url:
            _event_bus.register_consumer(consumer)
            logger.info("DeepField event consumer registered → %s", consumer.url)
        else:
            logger.info("DeepField consumer skipped — STARGATE_DEEPFIELD_URL not set")
        geolux = GeoLuxConsumer()
        if geolux.url:
            _event_bus.register_consumer(geolux)
            logger.info("GeoLux event consumer registered → %s", geolux.url)
        else:
            logger.info("GeoLux consumer skipped — STARGATE_GEOLUX_URL not set")
    except Exception as e:
        logger.warning("Failed to register event consumers: %s", e)


@app.on_event("startup")
def on_startup():
    init_db()
    _clone_agnosticv()
    _register_event_consumers()
    import threading
    t = threading.Thread(target=_mv_refresh_loop, daemon=True)
    t.start()
    tw = threading.Thread(target=_warm_caches, daemon=True)
    tw.start()
    if os.environ.get("STARGATE_INLINE_SCANNER", "false").lower() == "true":
        ts = threading.Thread(target=_auto_start_scanner, daemon=True)
        ts.start()
    tc = threading.Thread(target=_corpus_mining_loop, daemon=True)
    tc.start()
    tb = threading.Thread(target=_babylon_collection_loop, daemon=True)
    tb.start()


def _babylon_collection_loop():
    """Collect Babylon control plane data every 3 minutes."""
    import time as _tb
    import concurrent.futures
    _tb.sleep(30)
    logger = logging.getLogger("stargate")
    while not _shutdown_event.is_set():
        try:
            from cli.babylon_worker import run_collection
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_collection)
                results = future.result(timeout=150)
            prov = results.get("provisioning", {})
            pools = results.get("pools", {})
            logger.info(
                "Babylon collect: %d subjects, %d pools, %d lab mappings",
                prov.get("total", 0), pools.get("total_pools", 0),
                len(results.get("summit_mapping", results.get("lab_mapping", {})))
            )
        except concurrent.futures.TimeoutError:
            logger.warning("Babylon collection timed out after 150s")
        except Exception as e:
            logger.warning("Babylon collection failed: %s", e)
        _shutdown_event.wait(180)


def _corpus_mining_loop():
    """Run corpus miners every 30 minutes to build the failure knowledge base."""
    import time as _tc
    _tc.sleep(60)
    logger = logging.getLogger("stargate")
    while not _shutdown_event.is_set():
        try:
            from engine.corpus_runner import run_all_miners
            from db.database import get_db
            db = next(get_db())
            result = run_all_miners(db=db)
            logger.info(
                "Corpus mining: %d findings from %d sources, %d total classes",
                result["total_findings"], len(result["by_source"]), result["total_failure_classes"],
            )
            db.close()
        except Exception as e:
            logger.warning("Corpus mining failed: %s", e)
        _shutdown_event.wait(1800)


def _auto_start_scanner():
    """Auto-start scanner after a short delay so the API is ready."""
    import time as _ts
    _ts.sleep(10)
    logger = logging.getLogger("stargate")
    try:
        from api.routers._shared import _scheduler_lock
        import api.routers._shared as _shared
        with _scheduler_lock:
            if _shared._scheduler is not None:
                return
            from cli.scheduler import Scheduler
            from cli.scan import load_clusters
            clusters = load_clusters()
            if not clusters:
                logger.info("Scanner auto-start: no clusters configured")
                return
            _shared._scheduler = Scheduler(clusters=clusters, api_url="http://localhost:8090")
            available, unavailable = _shared._scheduler.start()
            logger.info(f"Scanner auto-started: {len(available)} clusters available, {len(unavailable)} unavailable")
    except Exception as e:
        logger.warning(f"Scanner auto-start failed: {e}")


def _warm_caches():
    """Pre-fetch external API caches so first page load is fast."""
    logger = logging.getLogger("stargate")
    try:
        from api.routers._shared import _fetch_labagator_labs, _fetch_labagator_sessions, _fetch_demolition_sessions
        _fetch_labagator_labs()
        _fetch_labagator_sessions()
        _fetch_demolition_sessions()
        logger.info("Cache warm: labagator + demolition")
    except Exception as e:
        logger.debug(f"Cache warm failed: {e}")
    try:
        from collectors.aap.collect_aap import collect_aap_jobs
        import api.routers._shared as _shared
        import time as _tc
        if not hasattr(_shared, '_aap_cache'):
            _shared._aap_cache = {"data": {}, "ts": 0.0}
        _shared._aap_cache["data"] = collect_aap_jobs()
        _shared._aap_cache["ts"] = _tc.time()
        logger.info("Cache warm: AAP")
    except Exception as e:
        logger.debug(f"Cache warm AAP failed: {e}")
    try:
        from db.database import get_db
        from api.routers.dashboard import dashboard_summit
        db = next(get_db())
        dashboard_summit(db=db, include_all=False)
        db.close()
        logger.info("Cache warm: summit dashboard pre-built")
    except Exception as e:
        logger.debug(f"Cache warm summit failed: {e}")


@app.on_event("shutdown")
def on_shutdown():
    _shutdown_event.set()
    logging.getLogger("stargate").info("Shutting down — stopping MV refresh, closing DB pool")


def _mv_refresh_loop():
    """Background thread to refresh materialized views and check scanner health every 60 seconds."""
    from api.routers._shared import _load_latest_scan
    from datetime import datetime, timezone
    logger = logging.getLogger("stargate")
    logger.info("MV refresh thread starting")
    _time.sleep(5)
    while not _shutdown_event.is_set():
        try:
            from db.database import get_session_factory
            factory = get_session_factory()
            db = factory()
            repository.refresh_cluster_summary(db)
            repository.refresh_pipeline_stages(db)
            repository.refresh_lab_eval_summary(db)
            try:
                from api.contracts import record_source_fetch
                record_source_fetch("stargate_db")
            except Exception:
                pass
            try:
                from engine.learner import apply_feedback
                apply_feedback(db)
            except Exception as e:
                logger.debug(f"Calibration refresh skipped: {e}")
            try:
                from engine.auto_llm import run_auto_analysis
                result = run_auto_analysis(db)
                if result.get("classified", 0) > 0:
                    logger.info(f"Auto-LLM: classified {result['classified']} failures")
            except Exception as e:
                logger.debug(f"Auto-LLM skipped: {e}")
            try:
                from engine.lab_mapper import refresh_lab_mappings
                refresh_lab_mappings(db)
            except Exception as e:
                logger.debug(f"Lab mapping refresh skipped: {e}")
            try:
                from engine.notifications import check_and_notify
                check_and_notify(db)
            except Exception as e:
                logger.debug(f"Notifications skipped: {e}")
            db.close()
            logger.info("MV refresh complete")
        except Exception as e:
            logger.warning(f"MV refresh failed: {e}")
            try:
                db.rollback()
                db.close()
            except Exception:
                pass

        try:
            scans = _load_latest_scan()
            if scans:
                ts = scans[0].get("timestamp", "")
                if ts:
                    age_min = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 60
                    if age_min > 15:
                        logger.warning(f"Scanner data is {age_min:.0f} minutes old — scanners may be stalled")
                    from api.metrics import scanner_clusters_healthy
                    healthy = sum(1 for s in scans if s.get("status") == "healthy")
                    scanner_clusters_healthy.set(healthy)
        except Exception as e:
            logger.debug(f"Scanner health check failed: {e}")

        _cleanup_scan_history()
        _shutdown_event.wait(60)


def _cleanup_scan_history(max_files: int = 500):
    """Remove old scan-history files, keeping the most recent."""
    from pathlib import Path as _P
    scan_dir = _P(__file__).parent.parent / "scan-history"
    if not scan_dir.exists():
        return
    files = sorted(scan_dir.glob("*.json"))
    if len(files) > max_files:
        for f in files[:-max_files]:
            try:
                f.unlink()
            except Exception:
                pass


# --- Include routers ---

from api.routers.health import router as health_router
from api.routers.admin import router as admin_router
from api.routers.runs import router as runs_router
from api.routers.dashboard import router as dashboard_router
from api.routers.integration import router as integration_router
from api.routers.capacity import router as capacity_router

app.include_router(health_router)
app.include_router(admin_router)
app.include_router(runs_router)
app.include_router(dashboard_router)
app.include_router(integration_router)
app.include_router(capacity_router)

# Serve frontend static files if dist/ exists (combined deployment)
from pathlib import Path as _Path
_frontend_dist = _Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    # Mount /assets FIRST so static files bypass the catch-all and get gzip from middleware
    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        file_path = (_frontend_dist / full_path).resolve()
        if file_path.is_file() and str(file_path).startswith(str(_frontend_dist.resolve())):
            return FileResponse(file_path)
        return FileResponse(_frontend_dist / "index.html")
