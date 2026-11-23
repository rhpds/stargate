"""DB-derived tier-3 sweep freshness.

The ``scanners`` component of ``/health`` is derived from the cluster-scan
snapshot the scheduler writes every five minutes. That snapshot answers "is
tier 1 alive", which is a different question from "has every lab been looked
at recently": on Nov 23 2026 the fleet was inside a two-hour tier-3 sweep and
``/health`` could not have told you the difference between that and tier 3
being wedged for five hours (docs/cluster-fleet.md).

A tier-3 run is the expensive one — it collects full evidence from one
namespace — so the honest freshness signal is per namespace, not per tick:

    sweep_age(cluster) = now - (last tier-3 run of the stalest live namespace)

"Live" is the scanner's own view of the cluster, published in every scan
snapshot as ``all_sandbox_namespaces``. Using that list instead of "every
namespace we happen to find in ``runs``" is what keeps teardown churn from
looking like scanner lag: a namespace that has been destroyed stops counting
the moment the next snapshot lands, whereas a minimum over raw ``runs`` ages
out old labs for a whole lookback window.

The API only *reads*. The scanner owns the rotation; this module measures it,
publishes ``stargate_tier3_*`` gauges, and warns when a sweep falls behind.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("stargate.tier3_freshness")

#: Tier 3 is scheduled every 300 s over a 25-namespace batch. The production
#: fleet sweeps in ~1.0-1.7 h; two hours is the "inside the window" line the
#: fleet doc uses, and it is the warning threshold unless overridden.
DEFAULT_TARGET_SECONDS = 7200

#: How far back to look for a namespace's last run. Anything older than this
#: is indistinguishable from "never scanned", which the ``never_scanned``
#: gauge reports separately.
LOOKBACK_HOURS = 24

#: Re-warn about the same cluster at most once an hour, but warn immediately
#: on a state change (fresh -> stale, stale -> fresh).
WARN_INTERVAL_SECONDS = 3600

_cache: Dict = {"clusters": [], "target": float(DEFAULT_TARGET_SECONDS), "computed_at": None}
_state: Dict[str, str] = {}
_last_warn: Dict[str, float] = {}
_lock = threading.Lock()


def target_seconds() -> float:
    """Sweep-age warning threshold, `STARGATE_TIER3_FRESHNESS_TARGET_SECONDS`."""
    raw = os.environ.get("STARGATE_TIER3_FRESHNESS_TARGET_SECONDS", "")
    if not raw:
        return float(DEFAULT_TARGET_SECONDS)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "STARGATE_TIER3_FRESHNESS_TARGET_SECONDS=%r is not a number; using %ss",
            raw, DEFAULT_TARGET_SECONDS,
        )
        return float(DEFAULT_TARGET_SECONDS)
    return value if value > 0 else float(DEFAULT_TARGET_SECONDS)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands back naive datetimes; everything here is UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def live_namespaces(scan_data) -> Dict[str, List[str]]:
    """The scanner's live namespace set per cluster, from a scan snapshot."""
    live: Dict[str, List[str]] = {}
    for entry in scan_data or []:
        if not isinstance(entry, dict):
            continue
        cluster = entry.get("cluster")
        if not cluster:
            continue
        names = {ns for ns in entry.get("all_sandbox_namespaces") or [] if ns}
        if names:
            live[cluster] = sorted(names)
    return live


def compute(db, scan_data, now: Optional[datetime] = None) -> List[Dict]:
    """Per-cluster sweep age for the live namespace set in ``scan_data``.

    ``scan_data`` is the list ``_load_latest_scan()`` returns: one dict per
    cluster, each carrying ``all_sandbox_namespaces``. Returns one dict per
    cluster that reports at least one live namespace.
    """
    from db.models import RunRecord
    from sqlalchemy import func

    now = _as_utc(now) or datetime.now(timezone.utc)
    live = live_namespaces(scan_data)
    if not live:
        return []

    every = sorted({ns for names in live.values() for ns in names})
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)
    rows = db.query(RunRecord.namespace, func.max(RunRecord.started_at)).filter(
        RunRecord.namespace.in_(every),
        RunRecord.started_at.isnot(None),
        RunRecord.started_at >= cutoff,
    ).group_by(RunRecord.namespace).all()

    last_at: Dict[str, datetime] = {}
    for namespace, started_at in rows:
        stamp = _as_utc(started_at)
        if stamp is not None:
            last_at[namespace] = stamp

    clusters: List[Dict] = []
    for cluster in sorted(live):
        names = live[cluster]
        ages = sorted(
            ((now - last_at[ns]).total_seconds(), ns)
            for ns in names
            if ns in last_at
        )
        unseen = [ns for ns in names if ns not in last_at]
        clusters.append({
            "cluster": cluster,
            "live": len(names),
            "scanned": len(names) - len(unseen),
            "never_scanned": len(unseen),
            "sweep_age_seconds": round(ages[-1][0]) if ages else None,
            "last_scan_age_seconds": round(ages[0][0]) if ages else None,
            # The names an operator needs in order to look at the laggards.
            "stalest": [ns for _, ns in reversed(ages[-3:])],
            "unseen_sample": unseen[:3],
        })
    return clusters


def _publish(clusters: List[Dict]) -> None:
    from api.metrics import (
        tier3_live_namespaces,
        tier3_never_scanned,
        tier3_sweep_age_seconds,
    )

    for c in clusters:
        cluster = c["cluster"]
        tier3_live_namespaces.labels(cluster=cluster).set(c["live"])
        tier3_never_scanned.labels(cluster=cluster).set(c["never_scanned"])
        # A cluster with live namespaces but no run in the lookback window is
        # infinitely stale; report the window itself so the series exists and
        # the number is obvious rather than missing.
        age = c["sweep_age_seconds"]
        tier3_sweep_age_seconds.labels(cluster=cluster).set(
            age if age is not None else LOOKBACK_HOURS * 3600
        )


def _warn(clusters: List[Dict], target: float, now_epoch: float) -> None:
    for c in clusters:
        cluster = c["cluster"]
        age = c["sweep_age_seconds"]
        stale = age is None or age > target
        previous = _state.get(cluster)
        _state[cluster] = "stale" if stale else "ok"
        if not stale:
            if previous == "stale":
                logger.info(
                    "Tier-3 sweep for %s is back inside %ds (sweep age %.1f min)",
                    cluster, target, (age or 0) / 60,
                )
                _last_warn.pop(cluster, None)
            continue

        if previous != "stale" or now_epoch - _last_warn.get(cluster, 0.0) >= WARN_INTERVAL_SECONDS:
            _last_warn[cluster] = now_epoch
            laggards = ", ".join(c["stalest"]) or "none scanned"
            logger.warning(
                "Tier-3 sweep for %s is %.1f h old (target %.1f h) — "
                "%d/%d live namespaces scanned; stalest: %s",
                cluster,
                (age if age is not None else LOOKBACK_HOURS * 3600) / 3600,
                target / 3600,
                c["scanned"], c["live"], laggards,
            )

        if c["never_scanned"]:
            # Newly created labs land here until their first sweep; a lab that
            # stays here is a coverage hole the sweep age cannot show.
            logger.info(
                "Tier-3 coverage %s: %d live namespace(s) never scanned in %dh: %s",
                cluster, c["never_scanned"], LOOKBACK_HOURS,
                ", ".join(c["unseen_sample"]),
            )


def refresh(scan_data=None) -> List[Dict]:
    """Measure, publish, warn, and cache. Opens its own short session."""
    if scan_data is None:
        from api.routers._shared import _load_latest_scan
        scan_data = _load_latest_scan()

    db = None
    try:
        from db.database import get_session_factory
        db = get_session_factory()()
        clusters = compute(db, scan_data)
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass

    target = target_seconds()
    _publish(clusters)
    _warn(clusters, target, datetime.now(timezone.utc).timestamp())

    with _lock:
        _cache["clusters"] = clusters
        _cache["target"] = target
        _cache["computed_at"] = datetime.now(timezone.utc).isoformat()
    return clusters


def cached() -> Dict:
    """Whatever the last ``refresh`` measured — for /health, which must stay cheap."""
    with _lock:
        return {
            "clusters": list(_cache["clusters"]),
            "target_seconds": _cache["target"],
            "computed_at": _cache["computed_at"],
            "lookback_hours": LOOKBACK_HOURS,
        }
