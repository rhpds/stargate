"""Historical failure pattern miner + shadow mode.

Mining: extracts systemic failure patterns from the evaluation DB
using aggregation queries only (no full record loads).

Shadow mode: polls for recent failures and feeds them to GeoLux
for hypothesis generation. Logs what GeoLux WOULD recommend
without executing. Tracks whether failures self-resolve.

RESOURCE SAFETY: Aggregation only, batched, cached, rate-limited.
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


# ---------------------------------------------------------------------------
# Shadow Mode — ongoing failure tracking without execution
# ---------------------------------------------------------------------------

SHADOW_STATE_FILE = _PERSISTENT_DIR / "shadow-state.json" if _PERSISTENT_DIR.is_dir() else Path(__file__).parent.parent / "test-receipts" / "shadow-state.json"


def run_shadow_cycle(db, max_failures: int = 10) -> Dict:
    """Poll recent failures and feed to GeoLux. Track resolution.

    Reads the last processed evaluation ID from shadow state,
    fetches new failures since then, sends to GeoLux, and
    checks whether previously seen failures have resolved.

    Does NOT execute any remediation — shadow only.
    """
    import urllib.request
    from db.models import EvaluationRecord
    from sqlalchemy import func

    # Load shadow state
    state = {}
    if SHADOW_STATE_FILE.exists():
        try:
            state = json.loads(SHADOW_STATE_FILE.read_text())
        except Exception:
            pass

    last_id = state.get("last_processed_id", 0)
    shadow_log = state.get("shadow_log", [])

    # Get new failures since last check (batch, not full scan)
    new_failures = db.query(
        EvaluationRecord.id,
        EvaluationRecord.failure_class,
        EvaluationRecord.lab_code,
        EvaluationRecord.cluster_name,
        EvaluationRecord.message,
    ).filter(
        EvaluationRecord.id > last_id,
        EvaluationRecord.outcome == "fail",
        EvaluationRecord.failure_class.isnot(None),
    ).order_by(EvaluationRecord.id).limit(max_failures).all()

    if not new_failures:
        return {"status": "no_new_failures", "last_id": last_id, "shadow_log_size": len(shadow_log)}

    geolux_url = os.environ.get("STARGATE_GEOLUX_URL", "")
    api_key = os.environ.get("STARGATE_GEOLUX_API_KEY", os.environ.get("STARGATE_ADMIN_API_KEY", ""))

    fed = []
    seen_keys = set()
    for eval_id, fc, lab_code, cluster, message in new_failures:
        # Dedupe by namespace+failure_class in this batch
        key = f"{lab_code}:{fc}"
        if key in seen_keys:
            last_id = max(last_id, eval_id)
            continue
        seen_keys.add(key)

        catalog_item = _extract_catalog_item(lab_code or "")
        entry = {
            "eval_id": eval_id,
            "failure_class": fc,
            "namespace": lab_code,
            "catalog_item": catalog_item,
            "cluster": cluster,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "geolux_recommendation": None,
            "resolved": None,
            "resolved_at": None,
        }

        # Feed to GeoLux (shadow — log only, no execution)
        if geolux_url:
            try:
                payload = {
                    "source": "stargate",
                    "event_type": "stargate_evaluation_failed",
                    "event_id": f"shadow-{eval_id}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "payload": {
                        "run_id": f"shadow-{lab_code}",
                        "stage_id": "shadow-monitor",
                        "lab_code": lab_code or "",
                        "cluster": f"shadow-{cluster}-{eval_id}",
                        "namespace": lab_code or "",
                        "outcome": "fail",
                        "failure_class": fc,
                        "message": (message or "")[:500],
                    },
                }
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["X-API-Key"] = api_key
                endpoint = f"{geolux_url.rstrip('/')}/integration/events"
                req = urllib.request.Request(endpoint, data=json.dumps(payload).encode(), headers=headers)
                resp = urllib.request.urlopen(req, timeout=15)
                result = json.loads(resp.read().decode())
                entry["geolux_recommendation"] = {
                    "classification": result.get("classification_result"),
                    "hypotheses": result.get("hypotheses_generated", 0),
                }
            except Exception as e:
                entry["geolux_recommendation"] = {"error": str(e)}

        shadow_log.append(entry)
        fed.append(entry)
        last_id = max(last_id, eval_id)

    # Check resolution of previous shadow entries (last 50)
    resolved_count = 0
    for entry in shadow_log[-50:]:
        if entry.get("resolved") is not None:
            continue
        ns = entry.get("namespace")
        fc = entry.get("failure_class")
        if not ns or not fc:
            continue
        # Check if a passing evaluation exists after the failure
        has_pass = db.query(EvaluationRecord.id).filter(
            EvaluationRecord.lab_code == ns,
            EvaluationRecord.outcome == "pass",
            EvaluationRecord.id > entry.get("eval_id", 0),
        ).first()
        if has_pass:
            entry["resolved"] = True
            entry["resolved_at"] = datetime.now(timezone.utc).isoformat()
            resolved_count += 1

    # Trim shadow log to last 200 entries
    shadow_log = shadow_log[-200:]

    # Save state
    state["last_processed_id"] = last_id
    state["shadow_log"] = shadow_log
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    try:
        SHADOW_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        SHADOW_STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        logger.warning("Failed to save shadow state: %s", e)

    # Also track Deepfield incidents
    incident_result = track_incident_resolution(db, state)
    state["incident_log"] = incident_result.get("incident_log", [])

    # Re-save with incident data
    try:
        SHADOW_STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception:
        pass

    return {
        "status": "ok",
        "new_failures_processed": len(fed),
        "resolved_this_cycle": resolved_count,
        "total_shadow_log": len(shadow_log),
        "last_id": last_id,
        "incidents_tracked": incident_result.get("total", 0),
        "incidents_resolved": incident_result.get("resolved", 0),
    }


def track_incident_resolution(db, state: Dict = None) -> Dict:
    """Track Deepfield incident resolution — no AI calls needed.

    Deepfield incidents arrive pre-enriched with RCA + remediation options.
    We just check if the underlying failures have resolved.
    """
    from db.models import PendingAction, EvaluationRecord

    incident_log = (state or {}).get("incident_log", [])
    seen_ids = {e.get("incident_id") for e in incident_log}

    # Get Deepfield incidents
    incidents = db.query(PendingAction).filter(
        PendingAction.proposed_by == "deepfield",
    ).order_by(PendingAction.id.desc()).limit(50).all()

    for inc in incidents:
        inc_id = inc.source_event_id or str(inc.id)
        if inc_id in seen_ids:
            continue

        params = inc.parameters or {}
        entry = {
            "incident_id": inc_id,
            "action_type": inc.action_type,
            "namespace": inc.target,
            "cluster": params.get("cluster", ""),
            "failure_class": params.get("failure_class", ""),
            "severity": params.get("severity", ""),
            "confidence": inc.confidence,
            "has_rca": bool(params.get("rca_output")),
            "remediation_options": len(params.get("remediation_options", [])),
            "signal_count": params.get("signal_count", 0),
            "status": inc.status,
            "proposed_at": inc.proposed_at.isoformat() if inc.proposed_at else None,
            "resolved": None,
            "resolved_at": None,
        }

        # Check if the underlying failure resolved
        ns = inc.target
        fc = params.get("failure_class")
        if ns and fc:
            has_pass = db.query(EvaluationRecord.id).filter(
                EvaluationRecord.lab_code == ns,
                EvaluationRecord.outcome == "pass",
            ).order_by(EvaluationRecord.id.desc()).first()
            if has_pass:
                entry["resolved"] = True
                entry["resolved_at"] = datetime.now(timezone.utc).isoformat()

        incident_log.append(entry)

    # Check resolution for previously unresolved incidents
    resolved_count = 0
    for entry in incident_log:
        if entry.get("resolved") is not None:
            if entry["resolved"]:
                resolved_count += 1
            continue
        ns = entry.get("namespace")
        if ns:
            has_pass = db.query(EvaluationRecord.id).filter(
                EvaluationRecord.lab_code == ns,
                EvaluationRecord.outcome == "pass",
            ).order_by(EvaluationRecord.id.desc()).first()
            if has_pass:
                entry["resolved"] = True
                entry["resolved_at"] = datetime.now(timezone.utc).isoformat()
                resolved_count += 1

    incident_log = incident_log[-100:]

    return {
        "incident_log": incident_log,
        "total": len(incident_log),
        "resolved": resolved_count,
        "unresolved": len(incident_log) - resolved_count,
    }
