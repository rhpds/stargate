"""Runtime data contract validation + freshness tracking.

Validates API responses against contracts defined in contracts/dashboard_contracts.py.
Adds _contract metadata (warnings, sources) and _freshness (per-source age).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


_source_timestamps: Dict[str, float] = {}


def record_source_fetch(source: str):
    """Record when a data source was last fetched."""
    _source_timestamps[source] = time.time()


def get_freshness() -> Dict[str, Dict]:
    """Get freshness status for all tracked data sources."""
    now = time.time()
    result = {}
    for source in ["labagator", "babylon", "scanner", "demolition", "agnosticv", "stargate_db", "llm", "aap", "sandbox_api", "zerotouch"]:
        ts = _source_timestamps.get(source)
        if ts:
            age = int(now - ts)
            status = "fresh" if age < 300 else "stale" if age > 900 else "aging"
            result[source] = {
                "age_seconds": age,
                "last_fetched": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                "status": status,
            }
        else:
            result[source] = {"age_seconds": None, "last_fetched": None, "status": "unknown"}
    return result


def validate_response(endpoint: str, data: Any) -> Any:
    """Validate an API response against its contract. Adds _contract metadata."""
    from contracts.dashboard_contracts import CONTRACTS

    contract = CONTRACTS.get(endpoint)
    if not contract:
        if isinstance(data, dict):
            data["_contract"] = {"valid": True, "warnings": [], "sources": [], "validated_at": datetime.now(timezone.utc).isoformat()}
        return data

    warnings = []
    sources = set()

    items = []
    if contract.list_field and isinstance(data, dict):
        items = data.get(contract.list_field, [])
        if isinstance(items, list):
            items = items[:5]
    elif isinstance(data, dict):
        items = [data]

    for item in items:
        if not isinstance(item, dict):
            continue
        for field in contract.fields:
            sources.add(field.source)
            value = item.get(field.name)
            if field.required and value is None:
                warnings.append(f"{field.name}: required but null (source: {field.source})")
            if value is not None and field.type != "any":
                expected_types = {
                    "string": str, "int": (int, float), "float": (int, float),
                    "bool": bool, "list": list, "dict": dict,
                }
                expected = expected_types.get(field.type)
                if expected and not isinstance(value, expected):
                    warnings.append(f"{field.name}: expected {field.type}, got {type(value).__name__}")

    for check in contract.cross_checks:
        if check.check_fn == "stage_totals" and contract.list_field:
            all_items = data.get(contract.list_field, []) if isinstance(data, dict) else []
            for item in all_items:
                if not isinstance(item, dict):
                    continue
                p = item.get("pass", 0)
                w = item.get("warn", 0)
                f = item.get("fail", 0)
                t = item.get("total", 0)
                if t > 0 and p + w + f != t:
                    warnings.append(f"cross-check '{check.description}' failed for {item.get('stage_id', '?')}: {p}+{w}+{f}={p+w+f} != {t}")

    if isinstance(data, dict):
        data["_contract"] = {
            "valid": len(warnings) == 0,
            "warnings": warnings[:10],
            "sources": sorted(sources),
            "validated_at": datetime.now(timezone.utc).isoformat(),
        }

    return data
