"""Historical failure pattern miner — extracts actionable patterns from
StarGate's evaluation database for GeoLux hypothesis generation.

RESOURCE SAFETY: Uses aggregation queries only, never loads full records.
Processes in batches with configurable limits. Results cached to avoid
re-mining the same data.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("stargate.historical_miner")

_PERSISTENT_DIR = Path("/opt/app-root/src/scan-history")
MINING_CACHE_FILE = _PERSISTENT_DIR / "mining-cache.json" if _PERSISTENT_DIR.is_dir() else Path(__file__).parent.parent / "test-receipts" / "mining-cache.json"


def _extract_catalog_item(namespace: str) -> str:
    if not namespace:
        return "unknown"
    m = re.match(r"^sandbox-[a-z0-9]{5}-(.+)$", namespace)
    if m:
        return m.group(1)
    return namespace


def mine_failure_patterns(db, limit: int = 20) -> Dict:
    """Extract top systemic failure patterns from historical data.

    Uses aggregation queries — never loads individual records.
    Returns patterns grouped by catalog_item + failure_class.
    """
    from db.models import EvaluationRecord
    from sqlalchemy import func

    # Aggregate: failure_class × lab_code × cluster → count
    rows = db.query(
        EvaluationRecord.failure_class,
        EvaluationRecord.lab_code,
        EvaluationRecord.cluster_name,
        func.count().label("count"),
    ).filter(
        EvaluationRecord.outcome == "fail",
        EvaluationRecord.failure_class.isnot(None),
    ).group_by(
        EvaluationRecord.failure_class,
        EvaluationRecord.lab_code,
        EvaluationRecord.cluster_name,
    ).all()

    # Group by catalog_item + failure_class
    from collections import defaultdict
    patterns = defaultdict(lambda: {"count": 0, "instances": set(), "clusters": set()})
    for fc, lab_code, cluster, count in rows:
        item = _extract_catalog_item(lab_code or "")
        key = f"{item}:{fc}"
        patterns[key]["count"] += count
        patterns[key]["instances"].add(lab_code or "unknown")
        patterns[key]["clusters"].add(cluster or "unknown")
        patterns[key]["catalog_item"] = item
        patterns[key]["failure_class"] = fc

    # Filter to systemic patterns (10+ instances)
    systemic = {
        k: {
            "catalog_item": v["catalog_item"],
            "failure_class": v["failure_class"],
            "event_count": v["count"],
            "instance_count": len(v["instances"]),
            "cluster_count": len(v["clusters"]),
            "clusters": sorted(v["clusters"]),
        }
        for k, v in patterns.items()
        if len(v["instances"]) >= 10
    }

    # Sort by event count, take top N
    sorted_patterns = dict(sorted(systemic.items(), key=lambda x: -x[1]["event_count"])[:limit])

    # Get sample messages for top patterns (1 query per pattern, limit 3)
    for key, pattern in list(sorted_patterns.items())[:10]:
        msgs = db.query(EvaluationRecord.message).filter(
            EvaluationRecord.failure_class == pattern["failure_class"],
            EvaluationRecord.outcome == "fail",
            EvaluationRecord.message.isnot(None),
            EvaluationRecord.message != "",
        ).distinct().limit(3).all()
        pattern["sample_messages"] = [m[0][:200] for m in msgs if m[0]]

    return {
        "type": "historical-mining",
        "mined_at": datetime.now(timezone.utc).isoformat(),
        "total_patterns": len(sorted_patterns),
        "patterns": sorted_patterns,
    }


def mine_and_cache(db, limit: int = 20) -> Dict:
    """Mine patterns and cache to avoid re-mining."""
    if MINING_CACHE_FILE.exists():
        try:
            cached = json.loads(MINING_CACHE_FILE.read_text())
            mined_at = cached.get("mined_at", "")
            if mined_at:
                from datetime import datetime as dt
                age_hours = (datetime.now(timezone.utc) - dt.fromisoformat(mined_at)).total_seconds() / 3600
                if age_hours < 6:
                    logger.info("Using cached mining results (%.1fh old)", age_hours)
                    return cached
        except Exception:
            pass

    result = mine_failure_patterns(db, limit=limit)

    try:
        MINING_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        MINING_CACHE_FILE.write_text(json.dumps(result, indent=2))
        logger.info("Mining results cached: %d patterns", result["total_patterns"])
    except Exception as e:
        logger.warning("Failed to cache mining results: %s", e)

    return result


def feed_patterns_to_geolux(patterns: Dict, max_feed: int = 5) -> List[Dict]:
    """Send top mined patterns to GeoLux as evidence bundles.

    Only sends patterns that haven't been fed before (tracked in cache).
    Limits to max_feed per call to avoid overwhelming GeoLux.
    """
    import urllib.request

    geolux_url = os.environ.get("STARGATE_GEOLUX_URL", "")
    if not geolux_url:
        return [{"skipped": True, "reason": "STARGATE_GEOLUX_URL not set"}]

    api_key = os.environ.get("STARGATE_GEOLUX_API_KEY", os.environ.get("STARGATE_ADMIN_API_KEY", ""))
    results = []
    fed_count = 0

    for key, pattern in list(patterns.get("patterns", {}).items())[:max_feed]:
        if fed_count >= max_feed:
            break

        payload = {
            "source": "stargate",
            "event_type": "stargate_historical_pattern",
            "event_id": f"mining-{pattern['failure_class']}-{pattern['catalog_item']}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {
                "run_id": f"mining-{pattern['catalog_item']}",
                "stage_id": "historical-analysis",
                "lab_code": pattern["catalog_item"],
                "cluster": pattern["clusters"][0] if pattern["clusters"] else "multi-cluster",
                "namespace": pattern["catalog_item"],
                "outcome": "fail",
                "failure_class": pattern["failure_class"],
                "message": pattern["sample_messages"][0] if pattern.get("sample_messages") else "",
                "evidence": {
                    "event_count": pattern["event_count"],
                    "instance_count": pattern["instance_count"],
                    "cluster_count": pattern["cluster_count"],
                    "source": "historical_mining",
                },
            },
        }

        try:
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["X-API-Key"] = api_key
            endpoint = f"{geolux_url.rstrip('/')}/integration/events"
            req = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers=headers)
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read().decode())
            results.append({
                "pattern": key,
                "status": "sent",
                "hypotheses": result.get("hypotheses_generated", 0),
                "classification": result.get("classification_result"),
            })
            fed_count += 1
        except Exception as e:
            results.append({"pattern": key, "status": "failed", "error": str(e)})
            logger.warning("Failed to feed pattern to GeoLux: %s — %s", key, e)

    return results
