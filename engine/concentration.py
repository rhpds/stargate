"""Concentration — the largest offenders, ranked with cumulative share.

Two views over data StarGate already holds:

- FAILURE concentration: failed evaluations by lab_code, ranked, with
  share and cumulative percentage — and the lab vs platform-namespace
  split, because the top failure 'labs' are platform components
  (openshift-storage et al., found live Nov 13 2026: the top 10
  namespace-codes carry 16.7 percent of 3.76M failures, led by infra
  namespaces, not labs).
- PROVISION concentration: AAP source events by catalog item with
  channel normalization (RHPDS x / x.prod / x.dev / x.event are one
  item) — the fleet's provisioning load is extremely concentrated
  (top 5 items = 49.7 percent of 432k jobs, Nov 13 2026).

Both are time-windowed; neither runs unbounded.
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List

_CHANNEL_RE = re.compile(r"\.(prod|dev|event)$")
_RHPDS_RE = re.compile(r"^RHPDS ")


def classify_lab_code(lab_code: str) -> str:
    """sandbox-* namespaces are labs; everything else is a platform
    namespace the scanner also evaluates (operators, infra components)."""
    code = str(lab_code or "")
    if code.startswith("sandbox-") or code.startswith("user-"):
        return "lab"
    return "platform"


def _normalize_catalog_item(item: str) -> str:
    text = str(item or "")
    text = _RHPDS_RE.sub("", text)
    return _CHANNEL_RE.sub("", text)


def failure_concentration(db, days: int = 30, limit: int = 20) -> Dict:
    """Failed evaluations by lab_code, ranked with cumulative share."""
    from db.models import EvaluationRecord

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(EvaluationRecord.lab_code)
        .filter(
            EvaluationRecord.outcome == "fail",
            EvaluationRecord.evaluated_at >= cutoff,
        )
        .all()
    )
    counts: Dict[str, int] = {}
    for (lab_code,) in rows:
        key = lab_code or "(none)"
        counts[key] = counts.get(key, 0) + 1

    total = sum(counts.values())
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    entries: List[Dict] = []
    cumulative = 0
    for lab_code, fails in ranked:
        cumulative += fails
        entries.append({
            "lab_code": lab_code,
            "kind": classify_lab_code(lab_code),
            "failures": fails,
            "share_pct": round(100.0 * fails / total, 2) if total else 0.0,
            "cumulative_pct": round(100.0 * cumulative / total, 2) if total else 0.0,
        })

    platform_fails = sum(f for lab, f in counts.items() if classify_lab_code(lab) == "platform")
    lab_fails = total - platform_fails
    labs_only = [e for e in entries if e["kind"] == "lab"]

    return {
        "window_days": days,
        "total_failures": total,
        "distinct_lab_codes": len(counts),
        "entries": entries,
        "labs_only": labs_only,
        "split": {
            "platform_pct": round(100.0 * platform_fails / total, 2) if total else 0.0,
            "lab_pct": round(100.0 * lab_fails / total, 2) if total else 0.0,
        },
    }


def provision_concentration(db, days: int = 90, limit: int = 20) -> Dict:
    """AAP provisions by normalized catalog item, ranked with cumulative
    share."""
    from db.models import SourceEvent

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        db.query(SourceEvent.catalog_item)
        .filter(SourceEvent.occurred_at >= cutoff)
        .all()
    )
    counts: Dict[str, int] = {}
    for (item,) in rows:
        key = _normalize_catalog_item(item) if item else "(none)"
        counts[key] = counts.get(key, 0) + 1

    total = sum(counts.values())
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    entries: List[Dict] = []
    cumulative = 0
    for item, jobs in ranked:
        cumulative += jobs
        entries.append({
            "catalog_item": item,
            "jobs": jobs,
            "share_pct": round(100.0 * jobs / total, 2) if total else 0.0,
            "cumulative_pct": round(100.0 * cumulative / total, 2) if total else 0.0,
        })

    return {
        "window_days": days,
        "total_provisions": total,
        "distinct_items": len(counts),
        "entries": entries,
    }
