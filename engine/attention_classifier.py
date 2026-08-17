"""Attention classification for StarGate namespaces.

Classifies failing namespaces as stuck/anomalous/provisioning/expected
based on 7-day evaluation baselines and resolution history.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

logger = logging.getLogger("stargate.attention")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_catalog_item(lab_code: str) -> str:
    """Extract catalog item slug from a sandbox namespace name.

    E.g. 'sandbox-ab12c-ocp4-cluster' -> 'ocp4-cluster'
    Returns lab_code unchanged if the pattern doesn't match.
    """
    m = re.match(r"^sandbox-[a-z0-9]{5}-(.+)$", lab_code)
    return m.group(1) if m else lab_code


# ---------------------------------------------------------------------------
# Catalog item baselines
# ---------------------------------------------------------------------------

def build_catalog_baselines(db, hours: int = 168) -> Dict:
    """Build per-catalog-item baseline failure profiles from evaluation history.

    Returns {catalog_item: {failure_class: {rate, p95_ttr_minutes, count}}}
    Used to distinguish 'expected noise' from 'needs attention'.
    """
    from db.models import EvaluationRecord
    from sqlalchemy import func

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    rows = db.query(
        EvaluationRecord.lab_code,
        EvaluationRecord.outcome,
        EvaluationRecord.failure_class,
        func.count().label("cnt"),
    ).filter(
        EvaluationRecord.evaluated_at >= cutoff,
        EvaluationRecord.lab_code.isnot(None),
    ).group_by(
        EvaluationRecord.lab_code,
        EvaluationRecord.outcome,
        EvaluationRecord.failure_class,
    ).all()

    # Group by catalog item
    cat_data: Dict[str, Dict] = {}
    for lab_code, outcome, fc, cnt in rows:
        cat = extract_catalog_item(lab_code)
        if cat not in cat_data:
            cat_data[cat] = {"total_evals": 0, "namespaces": set(), "failures": {}}
        cat_data[cat]["total_evals"] += cnt
        cat_data[cat]["namespaces"].add(lab_code)
        if outcome == "fail" and fc:
            cat_data[cat]["failures"].setdefault(fc, 0)
            cat_data[cat]["failures"][fc] += cnt

    # Build TTR baselines from resolution records
    ttr_by_cat: Dict[str, Dict[str, list]] = {}
    try:
        from db.models import ResolutionRecord
        res_rows = db.query(
            ResolutionRecord.lab_code,
            ResolutionRecord.failure_class,
            ResolutionRecord.ttr_seconds,
        ).filter(
            ResolutionRecord.resolved_at >= cutoff,
            ResolutionRecord.ttr_seconds.isnot(None),
            ResolutionRecord.ttr_seconds > 0,
        ).all()
        for lab_code, fc, ttr in res_rows:
            cat = extract_catalog_item(lab_code)
            ttr_by_cat.setdefault(cat, {}).setdefault(fc, []).append(ttr / 60.0)
    except Exception:
        pass

    baselines: Dict[str, Dict] = {}
    for cat, d in cat_data.items():
        total = d["total_evals"]
        ns_count = len(d["namespaces"])
        fc_profiles = {}
        for fc, fail_cnt in d["failures"].items():
            rate = round(fail_cnt / max(total, 1), 3)
            ttr_list = sorted(ttr_by_cat.get(cat, {}).get(fc, []))
            p95 = ttr_list[int(len(ttr_list) * 0.95)] if len(ttr_list) > 1 else (ttr_list[0] if ttr_list else None)
            fc_profiles[fc] = {
                "rate": rate,
                "count": fail_cnt,
                "p95_ttr_minutes": round(p95, 1) if p95 else None,
            }
        baselines[cat] = {
            "namespace_count": ns_count,
            "total_evals": total,
            "failure_profiles": fc_profiles,
        }
    return baselines


# ---------------------------------------------------------------------------
# Namespace classification
# ---------------------------------------------------------------------------

def classify_namespace(
    ns: str, catalog_item: str, failure_classes: Dict[str, int],
    first_eval_at: Optional[datetime], baselines: Dict,
) -> Dict:
    """Classify a failing namespace as: stuck, anomalous, provisioning, or expected.

    - provisioning: namespace < 20 min old, failures are common for this catalog item
    - stuck: failure duration exceeds P95 TTR for this catalog item + failure class
    - anomalous: failure class is unusual for this catalog item (< 5% baseline rate)
    - expected: normal churn — this failure class and rate are typical
    """
    now = datetime.now(timezone.utc)
    age_minutes = None
    if first_eval_at:
        first = first_eval_at.replace(tzinfo=timezone.utc) if first_eval_at.tzinfo is None else first_eval_at
        age_minutes = (now - first).total_seconds() / 60.0

    baseline = baselines.get(catalog_item, {})
    fc_profiles = baseline.get("failure_profiles", {})

    # Young namespace — likely still provisioning
    if age_minutes is not None and age_minutes < 20:
        return {"attention": "provisioning", "reason": f"namespace is {int(age_minutes)}m old"}

    top_fc = max(failure_classes, key=failure_classes.get) if failure_classes else None
    if not top_fc:
        return {"attention": "expected", "reason": "no classified failures"}

    profile = fc_profiles.get(top_fc, {})
    baseline_rate = profile.get("rate", 0)
    p95_ttr = profile.get("p95_ttr_minutes")

    # Stuck: failing longer than P95 TTR (with a floor of 30 min)
    if age_minutes is not None and p95_ttr:
        threshold = max(p95_ttr, 30)
        if age_minutes > threshold:
            return {
                "attention": "stuck",
                "reason": f"{top_fc} for {int(age_minutes)}m (P95 is {int(p95_ttr)}m)",
            }

    # Anomalous: failure class is rare for this catalog item
    if baseline_rate < 0.05 and baseline.get("total_evals", 0) > 50:
        return {
            "attention": "anomalous",
            "reason": f"{top_fc} is unusual for {catalog_item} ({baseline_rate*100:.0f}% baseline)",
        }

    # Stuck fallback: no TTR data but failing for > 60 min
    if age_minutes is not None and age_minutes > 60 and not p95_ttr:
        return {
            "attention": "stuck",
            "reason": f"{top_fc} for {int(age_minutes)}m (no baseline TTR)",
        }

    return {"attention": "expected", "reason": f"{top_fc} is normal for {catalog_item}"}


# ---------------------------------------------------------------------------
# Baseline cache (module-level, 1-hour TTL)
# ---------------------------------------------------------------------------

_baseline_cache = None
_baseline_cache_at = None


def get_cached_baselines(db, max_age_seconds=3600):
    """Return cached catalog baselines, rebuilding if older than *max_age_seconds*."""
    global _baseline_cache, _baseline_cache_at
    now = datetime.now(timezone.utc)
    if _baseline_cache is not None and _baseline_cache_at and (now - _baseline_cache_at).total_seconds() < max_age_seconds:
        return _baseline_cache
    _baseline_cache = build_catalog_baselines(db)
    _baseline_cache_at = now
    return _baseline_cache


# ---------------------------------------------------------------------------
# Auto-investigation gate
# ---------------------------------------------------------------------------

def should_auto_investigate(
    db, lab_code: str, failure_class: str, cluster: str,
) -> Tuple[bool, str, Optional[str]]:
    """Decide whether a failing namespace should be auto-investigated.

    Returns (proceed: bool, reason: str, attention: str | None).
    attention is 'stuck' or 'anomalous' when proceed is True.
    """
    from db.repository import (
        get_recent_investigation,
        count_investigations_for_catalog_item,
        count_investigations_today,
    )

    # 0. Only investigate RHDP sandbox/showroom namespaces
    if not (lab_code.startswith("sandbox-") or lab_code.startswith("showroom-")):
        return False, f"not an RHDP namespace: {lab_code}", None

    # --- env-var knobs ---
    dedup_hours = int(os.environ.get("STARGATE_INVESTIGATE_DEDUP_HOURS", "4"))
    max_per_catalog_hour = int(os.environ.get("STARGATE_INVESTIGATE_MAX_PER_CATALOG_HOUR", "3"))
    max_stuck_per_day = int(os.environ.get("STARGATE_INVESTIGATE_MAX_STUCK_PER_DAY", "100"))
    max_anomalous_per_day = int(os.environ.get("STARGATE_INVESTIGATE_MAX_ANOMALOUS_PER_DAY", "50"))
    skip_self_resolve_pct = int(os.environ.get("STARGATE_INVESTIGATE_SKIP_SELF_RESOLVE_PCT", "50"))

    catalog_item = extract_catalog_item(lab_code)

    # 1. Build baselines + classify attention
    baselines = get_cached_baselines(db)

    # We need first_eval_at for classification — query it
    first_eval_at = None
    try:
        from db.models import EvaluationRecord
        from sqlalchemy import func as sa_func
        row = db.query(
            sa_func.min(EvaluationRecord.evaluated_at),
        ).filter(
            EvaluationRecord.lab_code == lab_code,
        ).scalar()
        first_eval_at = row
    except Exception:
        pass

    classification = classify_namespace(
        lab_code, catalog_item,
        {failure_class: 1} if failure_class else {},
        first_eval_at, baselines,
    )
    attention = classification.get("attention", "expected")

    # 2. Only proceed for stuck or anomalous
    if attention not in ("stuck", "anomalous"):
        return False, f"attention={attention}: {classification.get('reason', '')}", None

    # 3. Dedup: skip if this namespace was investigated recently (any failure class)
    recent = get_recent_investigation(db, lab_code, None, hours=dedup_hours)
    if recent:
        return False, f"already investigated within {dedup_hours}h", None

    # 4. Rate limit per catalog item per hour
    cat_count = count_investigations_for_catalog_item(db, catalog_item, hours=1)
    if cat_count >= max_per_catalog_hour:
        return False, f"rate limit: {cat_count}/{max_per_catalog_hour} for {catalog_item} this hour", None

    # 5. Daily budget — separate limits for stuck vs anomalous
    from db.models import InvestigationRecord
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if attention == "stuck":
        stuck_today = db.query(InvestigationRecord).filter(
            InvestigationRecord.created_at >= today_start,
            InvestigationRecord.trigger_type == "auto_stuck",
        ).count()
        if stuck_today >= max_stuck_per_day:
            return False, f"daily stuck budget: {stuck_today}/{max_stuck_per_day}", None
    else:
        anomalous_today = db.query(InvestigationRecord).filter(
            InvestigationRecord.created_at >= today_start,
            InvestigationRecord.trigger_type == "auto_anomalous",
        ).count()
        if anomalous_today >= max_anomalous_per_day:
            return False, f"daily anomalous budget: {anomalous_today}/{max_anomalous_per_day}", None

    # 6. Resolution profile — skip watch_and_wait with high self-resolve rate
    try:
        from engine.resolution_classifier import build_resolution_profiles
        profiles = build_resolution_profiles()
        key = f"{catalog_item}:{failure_class}" if failure_class else None
        if key and profiles.get("status") == "ok":
            profile = profiles.get("profiles", {}).get(key, {})
            recommendation = profile.get("recommendation")
            self_resolve_rate = profile.get("self_resolve_pct", 0)
            if recommendation == "watch_and_wait" and self_resolve_rate >= skip_self_resolve_pct:
                return False, (
                    f"watch_and_wait: {failure_class} self-resolves "
                    f"{self_resolve_rate}% of the time for {catalog_item}"
                ), None
    except Exception as exc:
        logger.debug("resolution profile check skipped: %s", exc)

    # 7. Learned suppression — skip if past investigations consistently say TRANSIENT
    try:
        from db.models import InvestigationRecord
        past = db.query(InvestigationRecord).filter(
            InvestigationRecord.status == "complete",
            InvestigationRecord.failure_class.contains(failure_class) if failure_class else False,
            InvestigationRecord.lab_code.contains(catalog_item) if catalog_item else False,
            InvestigationRecord.trust_dimensions.isnot(None),
        ).order_by(InvestigationRecord.id.desc()).limit(5).all()
        if len(past) >= 3:
            verdicts = [(p.trust_dimensions or {}).get("verdict") for p in past]
            transient_count = sum(1 for v in verdicts if v == "TRANSIENT")
            if transient_count >= 3:
                return False, (
                    f"learned: {failure_class} on {catalog_item} was TRANSIENT "
                    f"in {transient_count}/{len(past)} past investigations"
                ), None
    except Exception as exc:
        logger.debug("learned suppression check skipped: %s", exc)

    return True, f"attention={attention}: {classification.get('reason', '')}", attention
