"""Cluster saturation correlation — detect capacity exhaustion from evaluation patterns.

The problem this solves (RHDP ops documentation, Confluence 501907733, issue 4):

    "A cluster gets busy. Provisions start failing in different ways depending
    on what was mid-flight when the pressure hit. Some fail with VMI creation
    timeouts (DataVolume clones slow down massively under concurrent load).
    Some fail because the assisted installer hangs silently. Some get killed
    mid-run by an AAP SIGTERM. This is painful for ops because we end up
    chasing five different symptom tickets when the fix is 'the cluster was
    full.'"

Single-message pattern matching cannot detect this: the signature is
correlation-level. Three signals, each validated against a documented
incident (see docs/incident-validation-2026-10.md):

1. **rate_spike** — the cluster's failure rate in the window is elevated
   versus its own baseline. Validated: ocpv06/ocpv08, Oct 13-14 2026
   (RHDPOPS-24544).
2. **symptom_diversity** — failures scattered across many DISTINCT failure
   classes on one cluster. Diverse symptoms, one cause. Validated: ocpv08
   Oct 13-14 showed vmi_not_running, datavolume_failed, pods_not_ready,
   showroom_not_ready, service_has_no_endpoints simultaneously.
3. **lab_differential** — the same labs pass on other clusters while failing
   on this one. Validated: Summit Retest row 11 (Confluence 491356483) —
   "labs fail specifically when a claim lands on ocpv08; succeeding on
   ocpv01/ocpv02."

The inverse patterns are deliberately NOT saturation:
- One lab failing on every cluster → content bug (no differential).
- One failure class spiking cluster-wide → component bug (no diversity).

Verdict rule: saturated = rate_spike AND (symptom_diversity OR lab_differential).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

logger = logging.getLogger("stargate.cluster_saturation")

# --- Tunables (documented, conservative defaults) -------------------------

MIN_WINDOW_FAILS = 20        # a cluster must fail at least this much in-window to matter
MIN_WINDOW_TOTAL = 50        # and see at least this much traffic
RATE_MULTIPLIER = 2.0        # window failure rate must exceed baseline x this
MIN_BASELINE_TOTAL = 100     # baseline volume below this = insufficient history
MIN_DISTINCT_CLASSES = 5     # "five different symptom tickets"
MIN_DIVERGENT_LABS = 2       # labs failing here while passing elsewhere
MAX_DIVERGENT_LAB_SAMPLES = 10


def _parse_ts(value: Optional[str], default: datetime) -> datetime:
    if not value:
        return default
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except ValueError:
        return default


def _query_cluster_outcomes(db: Session, start: datetime, end: datetime) -> Dict[str, Dict[str, int]]:
    """Per-cluster outcome counts in [start, end)."""
    rows = db.execute(
        text(
            "SELECT cluster_name, outcome, COUNT(*) AS n "
            "FROM evaluations "
            "WHERE evaluated_at >= :start AND evaluated_at < :end "
            "AND cluster_name IS NOT NULL AND cluster_name != '' "
            "GROUP BY cluster_name, outcome"
        ),
        {"start": start, "end": end},
    ).fetchall()
    out: Dict[str, Dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0, "warn": 0, "total": 0})
    for cluster, outcome, n in rows:
        if outcome in ("pass", "fail", "warn"):
            out[cluster][outcome] = n
        out[cluster]["total"] += n
    return dict(out)


def _query_cluster_failure_classes(db: Session, start: datetime, end: datetime) -> Dict[str, Dict[str, int]]:
    """Per-cluster failure-class counts in [start, end)."""
    rows = db.execute(
        text(
            "SELECT cluster_name, COALESCE(failure_class, 'unclassified') AS fc, COUNT(*) AS n "
            "FROM evaluations "
            "WHERE evaluated_at >= :start AND evaluated_at < :end "
            "AND cluster_name IS NOT NULL AND cluster_name != '' "
            "AND outcome = 'fail' "
            "GROUP BY cluster_name, fc"
        ),
        {"start": start, "end": end},
    ).fetchall()
    out: Dict[str, Dict[str, int]] = defaultdict(dict)
    for cluster, fc, n in rows:
        out[cluster][fc] = n
    return dict(out)


def _query_failing_labs(
    db: Session, start: datetime, end: datetime, clusters: List[str]
) -> List[str]:
    """Labs that failed on any of `clusters` in [start, end)."""
    sql = (
        "SELECT DISTINCT lab_code FROM evaluations "
        "WHERE evaluated_at >= :start AND evaluated_at < :end "
        "AND outcome = 'fail' AND lab_code IS NOT NULL AND lab_code != '' "
        "AND cluster_name IN :names"
    )
    rows = db.execute(
        text(sql).bindparams(bindparam("names", expanding=True)),
        {"start": start, "end": end, "names": list(clusters)},
    ).fetchall()
    return [r[0] for r in rows]


def _query_lab_cluster_outcomes(
    db: Session, start: datetime, end: datetime, labs: Optional[List[str]] = None
) -> Dict[str, Dict[str, Dict[str, int]]]:
    """Lab x cluster outcome counts in [start, end).

    Restricted to `labs` when provided — the differential needs those labs'
    outcomes on ALL clusters (including healthy ones), so the restriction is
    by lab, never by cluster.
    """
    sql = (
        "SELECT lab_code, cluster_name, outcome, COUNT(*) AS n "
        "FROM evaluations "
        "WHERE evaluated_at >= :start AND evaluated_at < :end "
        "AND lab_code IS NOT NULL AND lab_code != '' "
        "AND cluster_name IS NOT NULL AND cluster_name != '' "
    )
    params: Dict[str, Any] = {"start": start, "end": end}
    bindparams = []
    if labs:
        params["labs"] = list(labs)
        sql += "AND lab_code IN :labs "
        bindparams.append(bindparam("labs", expanding=True))
    sql += "GROUP BY lab_code, cluster_name, outcome"
    rows = db.execute(text(sql).bindparams(*bindparams), params).fetchall()
    out: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: {"pass": 0, "fail": 0}))
    for lab, cluster, outcome, n in rows:
        if outcome in ("pass", "fail"):
            out[lab][cluster][outcome] = n
    return {lab: dict(c) for lab, c in out.items()}


def _rate(stats: Dict[str, int]) -> float:
    total = stats.get("total", 0)
    return stats.get("fail", 0) / total if total > 0 else 0.0


def _compute_differential(
    lab_outcomes: Dict[str, Dict[str, Dict[str, int]]], cluster: str
) -> List[Dict[str, Any]]:
    """Labs failing on `cluster` while passing on other clusters in-window."""
    divergent = []
    for lab, per_cluster in lab_outcomes.items():
        here = per_cluster.get(cluster, {"pass": 0, "fail": 0})
        if here["fail"] == 0:
            continue
        passes_elsewhere = sum(c["pass"] for name, c in per_cluster.items() if name != cluster)
        fails_elsewhere = sum(c["fail"] for name, c in per_cluster.items() if name != cluster)
        # Divergent: failing here AND demonstrably healthy somewhere else.
        # Labs failing everywhere are content bugs — explicitly excluded.
        if passes_elsewhere > 0 and here["fail"] >= fails_elsewhere:
            divergent.append(
                {
                    "lab": lab,
                    "fails_here": here["fail"],
                    "passes_here": here["pass"],
                    "passes_elsewhere": passes_elsewhere,
                    "fails_elsewhere": fails_elsewhere,
                }
            )
    divergent.sort(key=lambda d: (-d["passes_elsewhere"], -d["fails_here"]))
    return divergent


def detect_cluster_saturation(
    db: Session,
    window_start: Optional[datetime] = None,
    window_end: Optional[datetime] = None,
    window_hours: int = 6,
    baseline_days: int = 7,
    min_window_fails: int = MIN_WINDOW_FAILS,
    min_window_total: int = MIN_WINDOW_TOTAL,
    rate_multiplier: float = RATE_MULTIPLIER,
    min_baseline_total: int = MIN_BASELINE_TOTAL,
    min_distinct_classes: int = MIN_DISTINCT_CLASSES,
    min_divergent_labs: int = MIN_DIVERGENT_LABS,
) -> Dict[str, Any]:
    """Correlation-level saturation detection across all clusters.

    Args:
        window_start/window_end: retrospective window (both required for
            historical analysis). Defaults to the last `window_hours`.
        baseline_days: baseline window is [window_end - baseline_days, window_start).

    Returns a report: per-cluster signals, verdict, and fleet summary.
    Non-destructive: evaluations are never modified.
    """
    now = datetime.now(timezone.utc)
    window_end = _parse_ts(None if window_end is None else window_end.isoformat(), now)
    if window_start is None:
        window_start = window_end - timedelta(hours=window_hours)
    else:
        window_start = _parse_ts(window_start.isoformat(), window_end - timedelta(hours=window_hours))
    baseline_start = window_start - timedelta(days=baseline_days)

    win_stats = _query_cluster_outcomes(db, window_start, window_end)
    win_classes = _query_cluster_failure_classes(db, window_start, window_end)
    base_stats = _query_cluster_outcomes(db, baseline_start, window_start)

    # Pre-filter to clusters with enough window volume to be meaningful.
    candidates = [
        c for c, s in win_stats.items()
        if s["fail"] >= min_window_fails and s["total"] >= min_window_total
    ]

    # Lab x cluster matrix for labs failing on candidates, across ALL clusters
    # (the differential needs their passes on healthy clusters too).
    lab_outcomes: Dict[str, Dict[str, Dict[str, int]]] = {}
    if candidates:
        failing_labs = _query_failing_labs(db, window_start, window_end, candidates)
        if failing_labs:
            lab_outcomes = _query_lab_cluster_outcomes(db, window_start, window_end, labs=failing_labs)

    report_clusters: List[Dict[str, Any]] = []
    for cluster in sorted(win_stats):
        w = win_stats[cluster]
        b = base_stats.get(cluster, {"pass": 0, "fail": 0, "warn": 0, "total": 0})
        w_rate = _rate(w)
        b_rate = _rate(b)
        classes = win_classes.get(cluster, {})
        distinct = len(classes)
        top_classes = sorted(classes.items(), key=lambda kv: -kv[1])[:8]

        # --- Signal 1: rate spike vs own baseline -------------------------
        baseline_sufficient = b["total"] >= min_baseline_total
        rate_spike = (
            w["fail"] >= min_window_fails
            and w["total"] >= min_window_total
            and baseline_sufficient
            and w_rate >= max(b_rate * rate_multiplier, b_rate + 0.05)
        )

        # --- Signal 2: symptom diversity -----------------------------------
        diversity = distinct >= min_distinct_classes and w["fail"] >= min_window_fails

        # --- Signal 3: lab differential -------------------------------------
        divergent = _compute_differential(lab_outcomes, cluster) if lab_outcomes else []
        differential = len(divergent) >= min_divergent_labs

        signals = [rate_spike, diversity, differential]
        n_signals = sum(signals)
        saturated = rate_spike and (diversity or differential)
        if saturated and n_signals == 3:
            severity = "critical"
        elif saturated:
            severity = "high"
        elif diversity and differential:
            severity = "watch"  # scattered + selective but rate not (yet) spiked
        elif rate_spike:
            severity = "watch"
        else:
            severity = "none"

        # Confidence: signal count + magnitudes.
        conf = 0.0
        if saturated:
            conf = 0.4 * min(rate_multiplier and (w_rate / max(b_rate, 1e-6)) / rate_multiplier, 1.0)
            conf += 0.3 * min(distinct / (min_distinct_classes * 2), 1.0)
            conf += 0.3 * min(len(divergent) / (min_divergent_labs * 3), 1.0)
            conf = round(min(0.55 + conf, 0.99), 2)  # correlation evidence alone floors below 1.0
        elif severity == "watch":
            conf = round(0.3 + 0.15 * n_signals, 2)
        else:
            conf = round(0.1 * n_signals, 2)

        entry: Dict[str, Any] = {
            "cluster": cluster,
            "saturated": saturated,
            "severity": severity,
            "confidence": conf,
            "signals": {
                "rate_spike": {
                    "present": rate_spike,
                    "window_rate": round(w_rate, 4),
                    "baseline_rate": round(b_rate, 4),
                    "rate_multiplier_observed": round(w_rate / b_rate, 2) if b_rate > 0 else None,
                    "window_fails": w["fail"],
                    "window_total": w["total"],
                    "baseline_fails": b["fail"],
                    "baseline_total": b["total"],
                    "baseline_sufficient": baseline_sufficient,
                },
                "symptom_diversity": {
                    "present": diversity,
                    "distinct_failure_classes": distinct,
                    "top_classes": [{"class": c, "count": n} for c, n in top_classes],
                },
                "lab_differential": {
                    "present": differential,
                    "divergent_lab_count": len(divergent),
                    "divergent_labs": divergent[:MAX_DIVERGENT_LAB_SAMPLES],
                },
            },
        }
        if saturated:
            entry["interpretation"] = (
                f"Failure rate {w_rate:.1%} vs {b_rate:.1%} baseline across "
                f"{distinct} distinct failure classes; "
                f"{len(divergent)} labs failing here while passing elsewhere. "
                "Diverse symptoms with one cluster in common is the capacity-"
                "saturation signature — do not chase individual symptom classes."
            )
        report_clusters.append(entry)

    saturated_clusters = [c["cluster"] for c in report_clusters if c["saturated"]]
    return {
        "window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
            "hours": round((window_end - window_start).total_seconds() / 3600, 1),
        },
        "baseline_days": baseline_days,
        "thresholds": {
            "min_window_fails": min_window_fails,
            "rate_multiplier": rate_multiplier,
            "min_distinct_classes": min_distinct_classes,
            "min_divergent_labs": min_divergent_labs,
        },
        "clusters_analyzed": len(report_clusters),
        "saturated_clusters": saturated_clusters,
        "clusters": sorted(
            report_clusters,
            key=lambda c: (not c["saturated"], -c["signals"]["rate_spike"]["window_fails"]),
        ),
        "generated_at": now.isoformat(),
    }
