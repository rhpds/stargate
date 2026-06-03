"""Scanner tasks — cluster health scanning via Celery."""

import logging

from celery import shared_task

logger = logging.getLogger("stargate.tasks.scanner")


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def scanner_tick(self):
    """Run one scan tick across all configured clusters."""
    try:
        from cli.scan import load_clusters, scan_cluster
        clusters = load_clusters()
        results = {}
        for name, kc in clusters.items():
            result = scan_cluster(name, kc)
            if result:
                results[name] = {"status": result.get("status", "unknown")}
        logger.info("Scanner tick: %d clusters scanned", len(results))
        return results
    except Exception as e:
        logger.warning("Scanner tick failed: %s", e)
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=1)
def write_scan_history(self):
    """Write scan results to scan-history files and DB."""
    try:
        from api.routers._shared import _load_latest_scan
        scans = _load_latest_scan()
        if scans:
            import json
            from datetime import datetime, timezone
            from pathlib import Path
            scan_dir = Path(__file__).parent.parent / "scan-history"
            scan_dir.mkdir(exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            with open(scan_dir / f"scan-{ts}.json", "w") as f:
                json.dump(scans, f)
            logger.info("Scan history written: %d clusters", len(scans))
        return {"written": len(scans) if scans else 0}
    except Exception as e:
        logger.warning("Scan history write failed: %s", e)
        raise self.retry(exc=e)
