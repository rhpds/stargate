"""Admin monitoring sub-router — KPIs/SLOs, remediation strategies, cost analysis,
agent trust evaluation, and lifecycle matrix."""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from db.database import get_db
from db import repository
from engine.attention_classifier import build_catalog_baselines, classify_namespace
from engine.namespace import extract_guid, strip_sandbox_prefix, extract_sandbox_parts
from api.routers._shared import (
    limiter,
    _load_latest_scan,
    _load_latest_babylon,
    require_admin,
    require_admin_read,
)

router = APIRouter()
logger = logging.getLogger("stargate.admin.monitoring")


# ---------------------------------------------------------------------------
# Failure class correlation (shared helper)
# ---------------------------------------------------------------------------

def _build_failure_class_view(
    by_namespace: list, baselines: Dict, ns_data: Dict, db,
) -> list:
    """Build a per-failure-class correlation view.

    For each failure class currently active, computes:
    - affected_namespaces: count and list of namespaces hit
    - affected_catalog_items: which lab types are affected
    - affected_clusters: which clusters are affected
    - stuck_count: how many of those namespaces are classified as stuck
    - baseline_rate: 7-day average rate across all catalog items
    - current_rate: current-hour rate (affected / total monitored)
    - attention: spiking (> 2x baseline), spreading (hitting unusual catalog items),
      concentrated (isolated to one catalog item), or normal
    """
    import re as _re

    from api.constants import INFORMATIONAL_CLASSES

    fc_agg: Dict[str, Dict] = {}
    for entry in by_namespace:
        ns = entry["namespace"]
        cat = entry.get("catalog_item", "unknown")
        cluster = entry.get("cluster", "")
        d = ns_data.get(ns, {})
        att = entry.get("attention", "expected")

        for fc, cnt in d.get("failure_classes", {}).items():
            if fc in INFORMATIONAL_CLASSES:
                continue
            if fc not in fc_agg:
                fc_agg[fc] = {
                    "namespaces": [], "catalog_items": {}, "clusters": {},
                    "total_hits": 0, "stuck": 0, "anomalous": 0,
                }
            agg = fc_agg[fc]
            agg["namespaces"].append(ns)
            agg["total_hits"] += cnt
            agg["catalog_items"][cat] = agg["catalog_items"].get(cat, 0) + 1
            agg["clusters"][cluster] = agg["clusters"].get(cluster, 0) + 1
            if att == "stuck":
                agg["stuck"] += 1
            elif att == "anomalous":
                agg["anomalous"] += 1

    fc_baseline_rates: Dict[str, float] = {}
    total_baseline_evals = sum(b.get("total_evals", 0) for b in baselines.values())
    for cat, bl in baselines.items():
        for fc, profile in bl.get("failure_profiles", {}).items():
            fc_baseline_rates[fc] = fc_baseline_rates.get(fc, 0) + profile.get("count", 0)
    for fc in fc_baseline_rates:
        fc_baseline_rates[fc] = fc_baseline_rates[fc] / max(total_baseline_evals, 1)

    fc_baseline_cats: Dict[str, set] = {}
    for cat, bl in baselines.items():
        for fc, profile in bl.get("failure_profiles", {}).items():
            if profile.get("rate", 0) >= 0.05:
                fc_baseline_cats.setdefault(fc, set()).add(cat)

    fc_resolutions: Dict[str, Dict] = {}
    try:
        from db.models import ResolutionRecord
        from sqlalchemy import func
        twenty_four_h_ago = datetime.now(timezone.utc) - timedelta(hours=24)
        res_rows = db.query(
            ResolutionRecord.failure_class,
            ResolutionRecord.resolution_type,
            func.count().label("cnt"),
        ).filter(
            ResolutionRecord.resolved_at >= twenty_four_h_ago,
        ).group_by(
            ResolutionRecord.failure_class,
            ResolutionRecord.resolution_type,
        ).all()
        for fc, res_type, cnt in res_rows:
            fc_resolutions.setdefault(fc, {})
            fc_resolutions[fc][res_type] = cnt
    except Exception:
        pass

    total_monitored = len(ns_data)
    result = []

    for fc, agg in sorted(fc_agg.items(), key=lambda x: x[1]["stuck"] + x[1]["anomalous"], reverse=True):
        ns_count = len(agg["namespaces"])
        current_rate = ns_count / max(total_monitored, 1)
        baseline_rate = fc_baseline_rates.get(fc, 0)
        cats_affected = agg["catalog_items"]
        cats_baseline = fc_baseline_cats.get(fc, set())

        new_cats = set(cats_affected.keys()) - cats_baseline
        if baseline_rate > 0 and current_rate > baseline_rate * 2 and ns_count >= 3:
            attention = "spiking"
            reason = f"{current_rate*100:.0f}% of namespaces vs {baseline_rate*100:.1f}% baseline ({current_rate/baseline_rate:.1f}x)"
        elif new_cats and len(cats_baseline) > 0:
            attention = "spreading"
            reason = f"now hitting {', '.join(sorted(new_cats))} (not in baseline)"
        elif len(cats_affected) == 1 and ns_count >= 3:
            attention = "concentrated"
            cat_name = list(cats_affected.keys())[0]
            reason = f"isolated to {cat_name} ({ns_count} namespaces)"
        elif agg["stuck"] > 0:
            attention = "stuck"
            reason = f"{agg['stuck']} namespace{'s' if agg['stuck'] != 1 else ''} stuck"
        else:
            attention = "normal"
            reason = f"within baseline ({current_rate*100:.0f}% vs {baseline_rate*100:.1f}%)"

        resolutions = fc_resolutions.get(fc, {})
        total_resolved = sum(resolutions.values())
        self_resolve_pct = round(resolutions.get("self_resolved", 0) / max(total_resolved, 1) * 100) if total_resolved else None

        result.append({
            "failure_class": fc,
            "affected_namespaces": ns_count,
            "affected_catalog_items": sorted([
                {"catalog_item": cat, "count": cnt}
                for cat, cnt in cats_affected.items()
            ], key=lambda x: -x["count"]),
            "affected_clusters": sorted([
                {"cluster": c, "count": cnt}
                for c, cnt in agg["clusters"].items()
            ], key=lambda x: -x["count"]),
            "total_hits": agg["total_hits"],
            "stuck_count": agg["stuck"],
            "anomalous_count": agg["anomalous"],
            "current_rate": round(current_rate, 4),
            "baseline_rate": round(baseline_rate, 4),
            "attention": attention,
            "attention_reason": reason,
            "resolutions_24h": resolutions if resolutions else None,
            "self_resolve_pct": self_resolve_pct,
        })

    result.sort(key=lambda x: (
        0 if x["attention"] == "spiking" else 1 if x["attention"] == "spreading" else
        2 if x["attention"] == "stuck" else 3 if x["attention"] == "concentrated" else 4,
        -x["affected_namespaces"],
    ))

    return result


# ---------------------------------------------------------------------------
# Platform KPIs / SLOs
# ---------------------------------------------------------------------------

def _slo_status(current: float, target: float) -> str:
    if current >= target:
        return "met"
    if current >= target * 0.95:
        return "at_risk"
    return "breached"


def _compute_platform_kpis(db: Session) -> dict:
    """Compute platform KPIs, SLOs, and 7-day rolling trends."""
    from db.models import EvaluationRecord, LabMapping
    from sqlalchemy import func, or_
    from api.constants import INFORMATIONAL_CLASSES, WARNING_CLASSES
    import re as _re

    now = datetime.now(timezone.utc)
    one_hour = now - timedelta(hours=1)
    one_day = now - timedelta(hours=24)
    seven_days = now - timedelta(days=7)

    LAB_PREFIXES = ("sandbox-", "showroom-", "user-", "ocp4-cluster-")
    _lf = or_(*[EvaluationRecord.lab_code.like(f"{p}%") for p in LAB_PREFIXES])

    all_ns_rows = db.query(EvaluationRecord.lab_code).filter(
        EvaluationRecord.evaluated_at > one_hour, EvaluationRecord.lab_code.isnot(None), _lf,
    ).distinct().all()
    all_ns = {r[0] for r in all_ns_rows}
    total_monitored = len(all_ns)

    failing_rows = db.query(EvaluationRecord.lab_code).filter(
        EvaluationRecord.evaluated_at > one_hour, EvaluationRecord.outcome == "fail",
        EvaluationRecord.failure_class.isnot(None),
        EvaluationRecord.failure_class.notin_(INFORMATIONAL_CLASSES),
        ~EvaluationRecord.failure_class.in_(WARNING_CLASSES),
        EvaluationRecord.lab_code.isnot(None), _lf,
    ).distinct().all()
    failing_ns = {r[0] for r in failing_rows}
    total_prov_for_readiness = db.query(func.count(LabMapping.lab_code)).filter(
        LabMapping.lab_code.like("guid:%"),
    ).scalar() or 0
    denominator = max(total_prov_for_readiness, total_monitored, 1)
    readiness = round((denominator - len(failing_ns)) / denominator * 100, 1)

    babylon = _load_latest_babylon()
    prov = babylon.get("provisioning", {}) if babylon else {}
    prov_fail_rate = prov.get("failure_rate", 0) or 0
    prov_success = round(100.0 - prov_fail_rate, 1)

    fe = {r[0]: r[1] for r in db.query(
        EvaluationRecord.lab_code, func.min(EvaluationRecord.evaluated_at),
    ).filter(
        EvaluationRecord.evaluated_at >= one_day, EvaluationRecord.lab_code.isnot(None), _lf,
    ).group_by(EvaluationRecord.lab_code).all()}

    fp = {r[0]: r[1] for r in db.query(
        EvaluationRecord.lab_code, func.min(EvaluationRecord.evaluated_at),
    ).filter(
        EvaluationRecord.evaluated_at >= one_day, EvaluationRecord.outcome == "pass",
        EvaluationRecord.lab_code.isnot(None), _lf,
    ).group_by(EvaluationRecord.lab_code).all()}

    ttr_vals = [
        (fp[ns] - fe[ns]).total_seconds() / 60.0
        for ns in fe if ns in fp and fp[ns] > fe[ns]
        and 0 < (fp[ns] - fe[ns]).total_seconds() / 60.0 < 1440
    ]
    mean_ttr = round(sum(ttr_vals) / len(ttr_vals), 1) if ttr_vals else None

    total_prov = db.query(func.count(LabMapping.lab_code)).filter(
        LabMapping.lab_code.like("guid:%"),
    ).scalar() or 0
    utilization = round(total_monitored / max(total_prov, 1) * 100, 1) if total_prov else None
    try:
        mttr = repository.compute_mttr(db, hours=24)
    except Exception:
        mttr = {"overall_mttr_minutes": None, "by_class": []}

    guids = set()
    for ns in failing_ns:
        _g = extract_guid(ns)
        if _g:
            guids.add(f"guid:{_g}")
    dev_impact = 0
    if guids:
        dev_impact = db.query(func.count(func.distinct(LabMapping.owner))).filter(
            LabMapping.lab_code.in_(list(guids)), LabMapping.owner.isnot(None),
        ).scalar() or 0

    kpis = {
        "lab_readiness_rate": readiness,
        "provisioning_success_rate": prov_success,
        "mean_time_to_ready_minutes": mean_ttr,
        "active_sandboxes": total_monitored,
        "platform_utilization_pct": utilization,
        "mttr_minutes": mttr.get("overall_mttr_minutes"),
        "developer_impact": dev_impact,
    }

    ready_pct = round(
        sum(1 for t in ttr_vals if t <= 20) / max(len(ttr_vals), 1) * 100, 1,
    ) if ttr_vals else 100.0
    by_class = mttr.get("by_class", [])
    mttr_entries = [e for e in by_class if e.get("avg_minutes") is not None]
    fast = sum(1 for e in mttr_entries if e["avg_minutes"] <= 15)
    slo_mttr = round(fast / max(len(mttr_entries), 1) * 100, 1) if mttr_entries else 100.0

    slos = [
        {"name": "Sandbox Ready < 20min", "target": 95.0, "current": ready_pct,
         "unit": "%", "status": _slo_status(ready_pct, 95.0)},
        {"name": "Session Uptime", "target": 98.0, "current": readiness,
         "unit": "%", "status": _slo_status(readiness, 98.0)},
        {"name": "MTTR Critical < 15min", "target": 85.0, "current": slo_mttr,
         "unit": "%", "status": _slo_status(slo_mttr, 85.0)},
        {"name": "Provisioning Success", "target": 99.0, "current": prov_success,
         "unit": "%", "status": _slo_status(prov_success, 99.0)},
    ]

    three_days = now - timedelta(days=3)
    try:
        daily_f = db.query(
            func.date(EvaluationRecord.evaluated_at).label("day"),
            func.count(func.distinct(EvaluationRecord.lab_code)),
        ).filter(
            EvaluationRecord.evaluated_at >= three_days, EvaluationRecord.outcome == "fail",
            EvaluationRecord.failure_class.isnot(None),
            EvaluationRecord.failure_class.notin_(INFORMATIONAL_CLASSES),
            EvaluationRecord.lab_code.isnot(None), _lf,
        ).group_by(func.date(EvaluationRecord.evaluated_at)).all()
        f_map = {str(d): c for d, c in daily_f}
        daily_trend = [
            {"date": day, "failing_ns": cnt, "fail_rate": round(cnt / max(total_monitored, 1), 4)}
            for day, cnt in sorted(f_map.items())
        ]
    except Exception:
        daily_trend = []

    return {"kpis": kpis, "slos": slos, "daily_trend": daily_trend}


@router.get("/admin/platform-kpis", dependencies=[Depends(require_admin_read)])
def platform_kpis(db: Session = Depends(get_db)):
    """Platform KPIs, SLO compliance, and 7-day trends."""
    return _compute_platform_kpis(db)


# ---------------------------------------------------------------------------
# Remediation Strategies
# ---------------------------------------------------------------------------

def _build_remediation_strategies(db: Session) -> list:
    """Build tiered remediation strategies sorted by blast radius."""
    from db.models import EvaluationRecord, LabMapping
    from sqlalchemy import func, or_
    from api.constants import INFORMATIONAL_CLASSES
    import re as _re

    now = datetime.now(timezone.utc)
    one_hour = now - timedelta(hours=1)
    two_hours = now - timedelta(hours=2)
    strategies: list = []

    LAB_PREFIXES = ("sandbox-", "showroom-", "user-", "ocp4-cluster-")
    _lf = or_(*[EvaluationRecord.lab_code.like(f"{p}%") for p in LAB_PREFIXES])

    rows = db.query(
        EvaluationRecord.lab_code, EvaluationRecord.cluster_name,
        EvaluationRecord.outcome, EvaluationRecord.failure_class,
        func.count().label("cnt"),
    ).filter(
        EvaluationRecord.evaluated_at > one_hour,
        EvaluationRecord.lab_code.isnot(None), _lf,
    ).group_by(
        EvaluationRecord.lab_code, EvaluationRecord.cluster_name,
        EvaluationRecord.outcome, EvaluationRecord.failure_class,
    ).all()

    ns_data: Dict[str, Dict] = {}
    for lab_code, cluster, outcome, fc, cnt in rows:
        if lab_code not in ns_data:
            ns_data[lab_code] = {"cluster": cluster or "", "failure_classes": {}}
        if outcome == "fail" and fc and fc not in INFORMATIONAL_CLASSES:
            ns_data[lab_code]["failure_classes"][fc] = (
                ns_data[lab_code]["failure_classes"].get(fc, 0) + cnt
            )

    baselines = build_catalog_baselines(db)
    first_eval_map: Dict[str, datetime] = {}
    try:
        for lc, fa in db.query(
            EvaluationRecord.lab_code, func.min(EvaluationRecord.evaluated_at),
        ).filter(
            EvaluationRecord.lab_code.in_(list(ns_data.keys())),
        ).group_by(EvaluationRecord.lab_code).all():
            first_eval_map[lc] = fa
    except Exception:
        pass

    by_namespace = []
    for ns, d in ns_data.items():
        if not d["failure_classes"]:
            continue
        cat = strip_sandbox_prefix(ns)
        cl = classify_namespace(ns, cat, d["failure_classes"], first_eval_map.get(ns), baselines)
        by_namespace.append({
            "namespace": ns, "cluster": d["cluster"],
            "catalog_item": cat, "attention": cl["attention"],
        })

    fc_view = _build_failure_class_view(by_namespace, baselines, ns_data, db)
    for fce in fc_view:
        if fce["attention"] not in ("spiking", "spreading"):
            continue
        clusters = [c["cluster"] for c in fce["affected_clusters"][:3]]
        ratio = fce["current_rate"] / max(fce["baseline_rate"], 0.001)
        strategies.append({
            "level": "platform",
            "title": f"{fce['failure_class']} {fce['attention']} at {ratio:.1f}x baseline",
            "blast_radius": fce["affected_namespaces"],
            "severity": "critical" if fce["affected_namespaces"] >= 10 else "high",
            "recommendation": f"Investigate {fce['failure_class']} on {', '.join(clusters)}",
            "action_type": "investigate",
            "target": clusters[0] if clusters else "",
            "evidence": (
                f"{fce['affected_namespaces']} namespaces across "
                f"{len(fce['affected_clusters'])} clusters, "
                f"{fce['stuck_count']} stuck > P95 TTR"
            ),
            "expected_impact": f"Would resolve ~{fce['affected_namespaces']} namespace failures",
        })

    guid_info: Dict[str, Dict] = {}
    for lm in db.query(LabMapping).filter(LabMapping.lab_code.like("guid:%")).all():
        g = lm.lab_code.replace("guid:", "")
        guid_info[g] = {
            "name": lm.ci_name or lm.ci_base or g,
            "cat": lm.ci_base or "",
            "agv": lm.agnosticv_path or "",
        }

    cat_stats: Dict[str, Dict] = {}
    for ns, d in ns_data.items():
        parts = extract_sandbox_parts(ns)
        if not parts:
            continue
        info = guid_info.get(parts[0], {})
        cat = info.get("cat") or parts[1]
        cs = cat_stats.setdefault(cat, {
            "ns": set(), "failing": set(),
            "agv": info.get("agv", ""), "name": info.get("name", cat),
        })
        cs["ns"].add(ns)
        if d["failure_classes"]:
            cs["failing"].add(ns)

    for cat, cs in cat_stats.items():
        t, f = len(cs["ns"]), len(cs["failing"])
        if t < 5 or f / max(t, 1) <= 0.5:
            continue
        pct = round(f / t * 100, 1)
        agv = f"https://github.com/rhpds/agnosticv/tree/main/{cs['agv']}" if cs["agv"] else None
        strategies.append({
            "level": "lab", "title": f"{cs['name']} fail rate {pct}%",
            "blast_radius": f, "severity": "high" if pct >= 75 else "medium",
            "recommendation": f"Review AgnosticV config for {cat}",
            "action_type": "fix_config", "target": cat, "agnosticv_url": agv,
            "evidence": f"{f}/{t} namespaces failing",
            "expected_impact": f"Would stabilize ~{f} namespaces",
        })

    cluster_counts: Dict[str, Dict] = {}
    for ns, d in ns_data.items():
        c = d["cluster"] or "unknown"
        cluster_counts.setdefault(c, {"total": 0, "failing": 0})
        cluster_counts[c]["total"] += 1
        if d["failure_classes"]:
            cluster_counts[c]["failing"] += 1
    if cluster_counts:
        avg = sum(v["failing"] for v in cluster_counts.values()) / len(cluster_counts)
        for c, v in cluster_counts.items():
            if v["failing"] <= avg * 2 or v["failing"] < 3:
                continue
            strategies.append({
                "level": "cluster",
                "title": f"{c} has {v['failing']} failures ({v['failing']/max(avg,1):.1f}x avg)",
                "blast_radius": v["failing"],
                "severity": "high" if v["failing"] >= 10 else "medium",
                "recommendation": f"Investigate infrastructure health on {c}",
                "action_type": "investigate", "target": c,
                "evidence": f"{v['failing']}/{v['total']} namespaces failing vs avg {avg:.0f}",
                "expected_impact": f"Would resolve ~{v['failing']} namespace failures on {c}",
            })

    stuck = db.query(
        EvaluationRecord.lab_code, EvaluationRecord.cluster_name,
        EvaluationRecord.failure_class, func.count().label("n"),
    ).filter(
        EvaluationRecord.evaluated_at > two_hours, EvaluationRecord.outcome == "fail",
        EvaluationRecord.failure_class.isnot(None),
        EvaluationRecord.failure_class.notin_(INFORMATIONAL_CLASSES),
        EvaluationRecord.lab_code.isnot(None), _lf,
    ).group_by(
        EvaluationRecord.lab_code, EvaluationRecord.cluster_name,
        EvaluationRecord.failure_class,
    ).having(func.count() > 20).all()

    passed = {r[0] for r in db.query(EvaluationRecord.lab_code).filter(
        EvaluationRecord.evaluated_at > two_hours, EvaluationRecord.outcome == "pass",
        EvaluationRecord.lab_code.isnot(None), _lf,
    ).distinct().all()}

    for lc, cl, fc, n in stuck:
        if lc in passed:
            continue
        strategies.append({
            "level": "namespace", "title": f"{lc} stuck with {fc}",
            "blast_radius": 1, "severity": "high" if n >= 50 else "medium",
            "recommendation": f"Recycle namespace {lc} on {cl}",
            "action_type": "recycle", "target": lc,
            "evidence": f"{n} consecutive failures of {fc} with no recovery in 2h",
            "expected_impact": "Would recover 1 stuck namespace",
        })

    strategies.sort(key=lambda s: s["blast_radius"], reverse=True)
    return strategies


@router.get("/admin/remediation-strategies", dependencies=[Depends(require_admin_read)])
def remediation_strategies(db: Session = Depends(get_db)):
    """Tiered remediation strategies sorted by blast radius (highest impact first)."""
    strats = _build_remediation_strategies(db)
    return {
        "strategies": strats,
        "total": len(strats),
        "by_level": {
            level: sum(1 for s in strats if s["level"] == level)
            for level in ("platform", "lab", "cluster", "namespace")
        },
    }


# ---------------------------------------------------------------------------
# Cost Analysis
# ---------------------------------------------------------------------------

RESOURCE_PROFILES = {
    "ocp4-cluster": {"vcpu": 24, "memory_gi": 96, "storage_gi": 14000, "type": "dedicated"},
    "ocp-virt": {"vcpu": 24, "memory_gi": 96, "storage_gi": 14000, "type": "dedicated"},
    "zt-ansiblebu": {"vcpu": 4, "memory_gi": 16, "storage_gi": 200, "type": "shared"},
    "zt-rhelbu": {"vcpu": 2, "memory_gi": 8, "storage_gi": 100, "type": "shared"},
    "_default": {"vcpu": 8, "memory_gi": 32, "storage_gi": 500, "type": "shared"},
}

_CATALOG_DISPLAY_NAMES = {
    "ocp4-cluster": "OpenShift 4 Cluster",
    "ocp-virt": "OpenShift Virtualization",
    "zt-ansiblebu": "Zero Touch Ansible",
    "zt-rhelbu": "Zero Touch RHEL",
}

COST_VCPU_HOUR = float(os.environ.get("STARGATE_COST_VCPU_HOUR", "0.05"))
COST_MEMORY_GI_HOUR = float(os.environ.get("STARGATE_COST_MEMORY_GI_HOUR", "0.01"))
COST_STORAGE_GI_HOUR = float(os.environ.get("STARGATE_COST_STORAGE_GI_HOUR", "0.0001"))


def _sandbox_hourly_cost(profile: dict) -> float:
    return (
        profile["vcpu"] * COST_VCPU_HOUR
        + profile["memory_gi"] * COST_MEMORY_GI_HOUR
        + profile["storage_gi"] * COST_STORAGE_GI_HOUR
    )


def _profile_for_catalog_item(catalog_item: str) -> dict:
    for key in RESOURCE_PROFILES:
        if key == "_default":
            continue
        if catalog_item.startswith(key):
            return RESOURCE_PROFILES[key]
    return RESOURCE_PROFILES["_default"]


@router.get("/admin/cost-analysis", dependencies=[Depends(require_admin_read)])
def admin_cost_analysis(db: Session = Depends(get_db)):
    """Resource footprint and cost estimates from evaluation and provisioning data."""
    from db.models import EvaluationRecord, LabMapping
    from sqlalchemy import func, or_
    from api.constants import WARNING_CLASSES, INFORMATIONAL_CLASSES
    import re as _re

    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    two_hours_ago = now - timedelta(hours=2)

    LAB_PREFIXES = ("sandbox-", "showroom-", "user-", "ocp4-cluster-")
    _lf = or_(*[EvaluationRecord.lab_code.like(f"{p}%") for p in LAB_PREFIXES])

    EXCLUDED_CLASSES = WARNING_CLASSES | INFORMATIONAL_CLASSES

    all_ns_rows = db.query(
        EvaluationRecord.lab_code,
        EvaluationRecord.cluster_name,
    ).filter(
        EvaluationRecord.evaluated_at > one_hour_ago,
        EvaluationRecord.lab_code.isnot(None),
        _lf,
    ).distinct().all()

    failing_ns_rows = db.query(
        EvaluationRecord.lab_code,
        EvaluationRecord.cluster_name,
        EvaluationRecord.failure_class,
    ).filter(
        EvaluationRecord.evaluated_at > one_hour_ago,
        EvaluationRecord.outcome == "fail",
        EvaluationRecord.failure_class.isnot(None),
        EvaluationRecord.failure_class.notin_(EXCLUDED_CLASSES),
        EvaluationRecord.lab_code.isnot(None),
        _lf,
    ).distinct().all()

    failing_ns_set = {r[0] for r in failing_ns_rows}

    fail_counts = db.query(
        EvaluationRecord.lab_code,
        func.count(EvaluationRecord.id).label("fail_cnt"),
    ).filter(
        EvaluationRecord.evaluated_at > two_hours_ago,
        EvaluationRecord.outcome == "fail",
        EvaluationRecord.failure_class.isnot(None),
        EvaluationRecord.failure_class.notin_(EXCLUDED_CLASSES),
        EvaluationRecord.lab_code.isnot(None),
        _lf,
    ).group_by(EvaluationRecord.lab_code).having(
        func.count(EvaluationRecord.id) > 10,
    ).all()

    pass_ns_2h = {
        r[0]
        for r in db.query(EvaluationRecord.lab_code).filter(
            EvaluationRecord.evaluated_at > two_hours_ago,
            EvaluationRecord.outcome == "pass",
            EvaluationRecord.lab_code.isnot(None),
            _lf,
        ).distinct().all()
    }

    stuck_ns_set = {r[0] for r in fail_counts if r[0] not in pass_ns_2h}

    def _extract_catalog_item(ns: str) -> str:
        return strip_sandbox_prefix(ns)

    ns_catalog: Dict[str, str] = {}
    ns_cluster: Dict[str, str] = {}
    for lab_code, cluster_name in all_ns_rows:
        ns_catalog[lab_code] = _extract_catalog_item(lab_code)
        if cluster_name:
            ns_cluster[lab_code] = cluster_name

    cat_active: Dict[str, int] = {}
    cat_failing: Dict[str, int] = {}
    for ns, cat in ns_catalog.items():
        cat_active[cat] = cat_active.get(cat, 0) + 1
        if ns in failing_ns_set:
            cat_failing[cat] = cat_failing.get(cat, 0) + 1

    cluster_active: Dict[str, int] = {}
    cluster_failing: Dict[str, int] = {}
    for ns, cluster_name in ns_cluster.items():
        cluster_active[cluster_name] = cluster_active.get(cluster_name, 0) + 1
        if ns in failing_ns_set:
            cluster_failing[cluster_name] = cluster_failing.get(cluster_name, 0) + 1

    babylon = _load_latest_babylon()
    prov = babylon.get("provisioning", {}) if babylon else {}
    prov_failed_count = prov.get("failed", 0) or 0

    total_provisioned = db.query(func.count(LabMapping.lab_code)).filter(
        LabMapping.lab_code.like("guid:%"),
    ).scalar() or 0

    guid_display: Dict[str, str] = {}
    for m in db.query(LabMapping).filter(LabMapping.lab_code.like("guid:%")).all():
        guid = m.lab_code.replace("guid:", "")
        if m.ci_base:
            guid_display[m.ci_base] = m.ci_name or m.ci_base

    total_active = len(ns_catalog)

    by_catalog_item = []
    total_hourly = 0.0
    failure_hourly = 0.0

    for cat in sorted(cat_active.keys()):
        profile = _profile_for_catalog_item(cat)
        cost_per_hour = _sandbox_hourly_cost(profile)
        active = cat_active[cat]
        failing = cat_failing.get(cat, 0)
        cat_total_hourly = cost_per_hour * active
        cat_failure_hourly = cost_per_hour * failing
        healthy = active - failing

        total_hourly += cat_total_hourly
        failure_hourly += cat_failure_hourly

        display_name = (
            guid_display.get(cat)
            or _CATALOG_DISPLAY_NAMES.get(cat)
            or cat.replace("-", " ").title()
        )

        by_catalog_item.append({
            "catalog_item": cat,
            "display_name": display_name,
            "resource_type": profile["type"],
            "active_count": active,
            "failing_count": failing,
            "resource_profile": {
                "vcpu": profile["vcpu"],
                "memory_gi": profile["memory_gi"],
                "storage_gi": profile["storage_gi"],
            },
            "cost_per_sandbox_hour": round(cost_per_hour, 4),
            "total_hourly_cost": round(cat_total_hourly, 4),
            "failure_hourly_cost": round(cat_failure_hourly, 4),
            "cost_per_successful_session": round(cat_total_hourly / max(healthy, 1), 4),
        })

    by_cluster = []
    for cluster_name in sorted(cluster_active.keys()):
        c_active = cluster_active[cluster_name]
        c_failing = cluster_failing.get(cluster_name, 0)
        c_hourly = 0.0
        c_fail_hourly = 0.0
        for ns, cname in ns_cluster.items():
            if cname != cluster_name:
                continue
            cat = ns_catalog.get(ns, "")
            profile = _profile_for_catalog_item(cat)
            cost = _sandbox_hourly_cost(profile)
            c_hourly += cost
            if ns in failing_ns_set:
                c_fail_hourly += cost

        by_cluster.append({
            "cluster": cluster_name,
            "sandbox_count": c_active,
            "failing_count": c_failing,
            "estimated_hourly_cost": round(c_hourly, 4),
            "failure_cost_hourly": round(c_fail_hourly, 4),
        })

    stuck_count = len(stuck_ns_set)
    stuck_hourly = 0.0
    for ns in stuck_ns_set:
        cat = ns_catalog.get(ns, _extract_catalog_item(ns))
        profile = _profile_for_catalog_item(cat)
        stuck_hourly += _sandbox_hourly_cost(profile)

    prov_waste_hourly = 0.0
    if prov_failed_count > 0:
        avg_wasted_minutes = 15
        default_cost = _sandbox_hourly_cost(RESOURCE_PROFILES["_default"])
        prov_waste_hourly = prov_failed_count * default_cost * (avg_wasted_minutes / 60.0)

    total_waste_hourly = stuck_hourly + prov_waste_hourly

    optimization_opportunities = []
    if stuck_count > 0:
        optimization_opportunities.append({
            "description": f"{stuck_count} stuck sandboxes are consuming shared cluster capacity with no user value",
            "action": "Recycle these sandboxes to free cluster capacity",
            "sandboxes": stuck_count,
            "type": "capacity_recovery",
        })

    failing_dedicated = [c for c in by_catalog_item if c["resource_type"] == "dedicated" and c["failing_count"] > 0]
    if failing_dedicated:
        top = max(failing_dedicated, key=lambda c: c["failing_count"])
        optimization_opportunities.append({
            "description": f"{top['failing_count']} failing {top['catalog_item']} sandboxes — each uses ~24 vCPU, 96Gi RAM, 14TB storage on shared cluster",
            "action": "Investigate root cause to reduce failure rate",
            "sandboxes": top["failing_count"],
            "type": "failure_reduction",
        })

    waste_pct = round(failure_hourly / max(total_hourly, 0.001) * 100, 1)

    return {
        "summary": {
            "total_sandboxes_active": total_active,
            "total_provisioned": total_provisioned,
            "estimated_hourly_cost": round(total_hourly, 4),
            "estimated_monthly_cost": round(total_hourly * 730, 2),
            "failure_cost_hourly": round(failure_hourly, 4),
            "failure_cost_monthly": round(failure_hourly * 730, 2),
            "waste_pct": waste_pct,
        },
        "by_catalog_item": by_catalog_item,
        "by_cluster": by_cluster,
        "failure_costs": {
            "stuck_sandboxes": {
                "count": stuck_count,
                "hourly_cost": round(stuck_hourly, 4),
                "description": "Sandboxes past P95 TTR still consuming resources",
            },
            "provisioning_failures": {
                "count": prov_failed_count,
                "avg_wasted_minutes": 15,
                "hourly_cost": round(prov_waste_hourly, 4),
            },
            "total_waste_hourly": round(total_waste_hourly, 4),
            "total_waste_monthly": round(total_waste_hourly * 730, 2),
            "optimization_opportunities": optimization_opportunities,
        },
        "cost_inputs": {
            "vcpu_hour": COST_VCPU_HOUR,
            "memory_gi_hour": COST_MEMORY_GI_HOUR,
            "storage_gi_hour": COST_STORAGE_GI_HOUR,
            "note": "Estimated unit costs — configure via STARGATE_COST_* env vars. On shared clusters, 'cost' represents resource capacity consumed, not direct spend. Actual infrastructure cost is fixed regardless of sandbox count.",
        },
    }


# ---------------------------------------------------------------------------
# Agent Trust Evaluation
# ---------------------------------------------------------------------------

@router.get("/admin/agent-trust")
def agent_trust_report(db: Session = Depends(get_db), _auth=Depends(require_admin_read)):
    """Run the agent evaluation against historical data and return trust scores."""
    from engine.agent_evaluator import (
        build_test_cases_from_history,
        evaluate_agent,
        get_hardcoded_test_cases,
    )

    cases = build_test_cases_from_history(db, limit=10)
    source = "historical"
    if not cases:
        cases = get_hardcoded_test_cases()
        source = "hardcoded"

    report = evaluate_agent(cases)
    report["source"] = source
    return report


# ---------------------------------------------------------------------------
# Lifecycle Matrix
# ---------------------------------------------------------------------------

@router.get("/admin/catalog-item-history")
def catalog_item_history(
    days: int = 7,
    db: Session = Depends(get_db),
    _auth=Depends(require_admin_read),
):
    """Per-catalog-item failure history with remediation patterns."""
    from db.models import EvaluationRecord, LabMapping, ResolutionRecord
    from sqlalchemy import func
    import re as _re

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    guid_info: Dict[str, Dict] = {}
    for m in db.query(LabMapping).filter(LabMapping.lab_code.like("guid:%")).all():
        guid = m.lab_code.replace("guid:", "")
        guid_info[guid] = {
            "display_name": m.ci_name or m.ci_base or guid,
            "catalog_item": m.ci_base or "",
            "agnosticv_path": m.agnosticv_path or "",
            "governor": m.ci_slug or "",
        }

    all_rows = db.query(
        EvaluationRecord.lab_code,
        EvaluationRecord.failure_class,
        EvaluationRecord.outcome,
        func.count().label("cnt"),
    ).filter(
        EvaluationRecord.evaluated_at >= cutoff,
        EvaluationRecord.lab_code.isnot(None),
    ).group_by(
        EvaluationRecord.lab_code,
        EvaluationRecord.failure_class,
        EvaluationRecord.outcome,
    ).all()

    from api.constants import INFORMATIONAL_CLASSES as _INFO

    cat_data: Dict[str, Dict] = {}

    def _resolve_cat(lab_code):
        parts = extract_sandbox_parts(lab_code or "")
        if not parts:
            return None, None, None, None
        guid, slug = parts
        info = guid_info.get(guid, {})
        cat_key = info.get("catalog_item") or slug
        display = info.get("display_name") or cat_key.replace("-", " ").title()
        agv_path = info.get("agnosticv_path", "")
        return cat_key, display, agv_path, info

    for lab_code, fc, outcome, cnt in all_rows:
        if fc and fc in _INFO:
            continue
        cat_key, display, agv_path, info = _resolve_cat(lab_code)
        if not cat_key:
            continue

        if cat_key not in cat_data:
            cat_data[cat_key] = {
                "display_name": display,
                "agnosticv_path": agv_path,
                "governor": (info or {}).get("governor", ""),
                "total_evals": 0,
                "total_fails": 0,
                "namespaces": set(),
                "failing_namespaces": set(),
                "failure_classes": {},
            }
        d = cat_data[cat_key]
        d["namespaces"].add(lab_code)
        if not d["agnosticv_path"] and agv_path:
            d["agnosticv_path"] = agv_path
        if outcome == "fail" and fc:
            d["total_fails"] += cnt
            d["failing_namespaces"].add(lab_code)
            d["failure_classes"].setdefault(fc, {"count": 0, "namespaces": set()})
            d["failure_classes"][fc]["count"] += cnt
            d["failure_classes"][fc]["namespaces"].add(lab_code)

    res_rows = db.query(
        ResolutionRecord.lab_code,
        ResolutionRecord.failure_class,
        ResolutionRecord.resolution_type,
        ResolutionRecord.ttr_seconds,
    ).filter(
        ResolutionRecord.resolved_at >= cutoff,
    ).all()

    cat_resolutions: Dict[str, Dict[str, Dict]] = {}
    for lab_code, fc, res_type, ttr in res_rows:
        parts = extract_sandbox_parts(lab_code or "")
        if not parts:
            continue
        guid, slug = parts
        info = guid_info.get(guid, {})
        cat_key = info.get("catalog_item") or slug

        cat_resolutions.setdefault(cat_key, {}).setdefault(fc, {
            "total": 0, "by_type": {}, "ttr_values": [],
        })
        r = cat_resolutions[cat_key][fc]
        r["total"] += 1
        r["by_type"][res_type] = r["by_type"].get(res_type, 0) + 1
        if ttr and ttr > 0:
            r["ttr_values"].append(ttr / 60.0)

    items = []
    for cat_key, d in sorted(cat_data.items(), key=lambda x: x[1]["total_fails"], reverse=True):
        if d["total_fails"] == 0:
            continue

        total_provisioned = sum(
            1 for g, info in guid_info.items()
            if info.get("catalog_item") == cat_key
        )
        failing_ns = len(d.get("failing_namespaces", set()))
        total_ns = max(total_provisioned, len(d["namespaces"]))
        fail_rate = round(failing_ns / max(total_ns, 1) * 100, 1)
        fc_list = []
        for fc, fc_data in sorted(d["failure_classes"].items(), key=lambda x: -x[1]["count"]):
            res = cat_resolutions.get(cat_key, {}).get(fc, {})
            ttr_vals = sorted(res.get("ttr_values", []))
            fc_entry = {
                "failure_class": fc,
                "count": fc_data["count"],
                "affected_namespaces": len(fc_data["namespaces"]),
                "pct_of_failures": round(fc_data["count"] / max(d["total_fails"], 1) * 100),
            }
            if res.get("total"):
                fc_entry["resolutions"] = {
                    "total": res["total"],
                    "by_type": res["by_type"],
                    "self_resolve_pct": round(res["by_type"].get("self_resolved", 0) / max(res["total"], 1) * 100),
                    "avg_ttr_minutes": round(sum(ttr_vals) / len(ttr_vals), 1) if ttr_vals else None,
                    "p95_ttr_minutes": round(ttr_vals[int(len(ttr_vals) * 0.95)], 1) if len(ttr_vals) > 1 else None,
                    "recommendation": (
                        "watch_and_wait" if res["by_type"].get("self_resolved", 0) > res["total"] * 0.7
                        else "investigate" if res["by_type"].get("human_remediated", 0) > res["total"] * 0.3
                        else "candidate_for_automation" if res["total"] >= 10
                        else "insufficient_data"
                    ),
                }
            fc_list.append(fc_entry)

        agv_url = ""
        if d["agnosticv_path"]:
            agv_url = f"https://github.com/rhpds/agnosticv/tree/main/{d['agnosticv_path']}"

        items.append({
            "catalog_item": cat_key,
            "display_name": d["display_name"],
            "agnosticv_path": d["agnosticv_path"],
            "agnosticv_url": agv_url,
            "governor": d.get("governor", ""),
            "total_evals": d["total_evals"],
            "total_fails": d["total_fails"],
            "fail_rate_pct": fail_rate,
            "namespace_count": len(d["namespaces"]),
            "failure_classes": fc_list[:10],
        })

    provisioning = None
    babylon = _load_latest_babylon()
    if babylon:
        prov = babylon.get("provisioning", {})
        if prov:
            provisioning = {
                "total": prov.get("total", 0),
                "started": prov.get("started", 0),
                "failed": prov.get("failed", 0),
                "failure_rate": prov.get("failure_rate", 0),
            }

    from sqlalchemy import extract
    hourly_rows = db.query(
        extract('hour', EvaluationRecord.evaluated_at).label('hour'),
        func.count().label('cnt'),
    ).filter(
        EvaluationRecord.evaluated_at >= cutoff,
        EvaluationRecord.outcome == 'fail',
        EvaluationRecord.failure_class.isnot(None),
    ).group_by('hour').all()

    hourly_distribution = {int(h): cnt for h, cnt in hourly_rows}

    return {
        "days": days,
        "total_catalog_items": len(items),
        "items": items[:50],
        "provisioning": provisioning,
        "hourly_distribution": hourly_distribution,
    }


@router.get("/admin/lifecycle-matrix")
def lifecycle_matrix(db: Session = Depends(get_db), _auth=Depends(require_admin_read)):
    """Namespace lifecycle matrix built from scanner evaluation records."""
    from db.models import EvaluationRecord
    from sqlalchemy import func, or_
    import re as _re

    STAGES = ["health", "pods", "storage", "network", "workload", "overall"]

    STAGE_MAP = {
        "pods_crashlooping": "pods", "readiness_probe_failed": "pods",
        "oom_killed": "pods", "pod_pending": "pods", "backoff_limit_exceeded": "pods",
        "image_pull_backoff": "pods", "image_pull_secret_missing": "pods",
        "claim_misbound": "storage", "volume_attach_failed": "storage",
        "volume_mount_failed": "storage", "pvc_binding_failed": "storage",
        "resource_leak_pv": "storage",
        "scheduling_failed": "workload", "quota_exceeded": "workload",
        "invalid_configuration": "workload", "hpa_max_replicas": "workload",
        "resolution_failed": "workload", "sync_failed": "workload",
        "datasource_unrecognized": "workload",
        "dns_resolution_failed": "network", "route_not_admitted": "network",
        "certificate_error": "network",
        "node_pressure": "health", "operator_unhealthy": "health",
        "operator_degraded": "health", "teardown_stuck": "health",
        "health_check_failed": "health", "deprecated_api": "health",
        "vm_migration_backoff": "workload",
        "guest_agent_not_connected": "workload",
    }

    from api.constants import WARNING_CLASSES

    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)

    LAB_PREFIXES = ("sandbox-", "showroom-", "user-", "ocp4-cluster-")
    _lab_filter = or_(*[EvaluationRecord.lab_code.like(f"{p}%") for p in LAB_PREFIXES])
    rows = db.query(
        EvaluationRecord.lab_code,
        EvaluationRecord.cluster_name,
        EvaluationRecord.outcome,
        EvaluationRecord.failure_class,
        func.count().label("cnt"),
    ).filter(
        EvaluationRecord.evaluated_at > one_hour_ago,
        EvaluationRecord.lab_code.isnot(None),
        _lab_filter,
    ).group_by(
        EvaluationRecord.lab_code,
        EvaluationRecord.cluster_name,
        EvaluationRecord.outcome,
        EvaluationRecord.failure_class,
    ).all()

    ns_data: Dict[str, Dict] = {}
    for lab_code, cluster, outcome, fc, cnt in rows:
        if lab_code not in ns_data:
            ns_data[lab_code] = {
                "cluster": cluster or "", "pass": 0, "fail": 0, "real_fail": 0, "total": 0,
                "failure_classes": {}, "stage_failures": {s: 0 for s in STAGES},
            }
        d = ns_data[lab_code]
        d["total"] += cnt
        if outcome == "pass":
            d["pass"] += cnt
        elif outcome == "fail":
            d["fail"] += cnt
            is_warning = fc in WARNING_CLASSES if fc else False
            if not is_warning:
                d["real_fail"] += cnt
            if fc and not is_warning:
                d["failure_classes"][fc] = d["failure_classes"].get(fc, 0) + cnt
                stage = STAGE_MAP.get(fc, "workload")
                d["stage_failures"][stage] = d["stage_failures"].get(stage, 0) + cnt

    baselines = build_catalog_baselines(db)

    _BASE_ENV_NAMES = {
        "zt-ansiblebu": "Ansible Automation Platform Labs",
        "zt-rhelbu": "RHEL Labs",
        "ocp4-cluster": "OpenShift 4 Cluster",
    }
    catalog_display_names: Dict[str, str] = dict(_BASE_ENV_NAMES)

    ns_display_names: Dict[str, str] = {}
    ns_owners: Dict[str, str] = {}
    guid_lab_names: Dict[str, str] = {}
    try:
        from db.models import LabMapping
        lab_mappings_db = db.query(LabMapping).all()
        for m in lab_mappings_db:
            if m.lab_code.startswith("guid:") and m.ci_name:
                guid_lab_names[m.lab_code.replace("guid:", "")] = m.ci_name
            elif m.ci_name:
                ns_display_names[m.lab_code] = m.ci_name
                if m.ci_base and m.ci_base not in catalog_display_names:
                    catalog_display_names[m.ci_base] = m.ci_name
            if m.owner:
                ns_owners[m.lab_code] = m.owner
    except Exception:
        pass

    try:
        import urllib.request as _urlreq
        _lab_url = os.environ.get("STARGATE_LABAGATOR_URL", "")
        if _lab_url:
            with _urlreq.urlopen(f"{_lab_url}/labs?limit=300", timeout=5) as _resp:
                _labs = json.loads(_resp.read())
                for _lab in (_labs if isinstance(_labs, list) else []):
                    _ci = _lab.get("ci_name") or ""
                    _title = _lab.get("title") or ""
                    if _ci and _title:
                        _slug = _ci.split(".", 1)[1] if "." in _ci else _ci
                        if _slug not in catalog_display_names:
                            catalog_display_names[_slug] = _title
    except Exception:
        pass

    for _cat_slug in list(ns_data.keys()):
        _ci_slug = strip_sandbox_prefix(_cat_slug)
        if _ci_slug not in catalog_display_names:
            _base = _re.sub(r"^\d+-", "", _ci_slug)
            if _base in catalog_display_names:
                catalog_display_names[_ci_slug] = catalog_display_names[_base]

    first_eval_map: Dict[str, datetime] = {}
    try:
        from db.models import EvaluationRecord as _ER
        first_evals = db.query(
            _ER.lab_code,
            func.min(_ER.evaluated_at).label("first_at"),
        ).filter(
            _ER.lab_code.in_(list(ns_data.keys())),
        ).group_by(_ER.lab_code).all()
        for lab_code, first_at in first_evals:
            first_eval_map[lab_code] = first_at
    except Exception:
        pass

    by_namespace = []
    all_ns_stages = []
    for ns, d in sorted(ns_data.items(), key=lambda x: x[1]["real_fail"], reverse=True):
        effective_total = d["pass"] + d["real_fail"]
        health_pct = round(d["pass"] / max(effective_total, 1) * 100, 1)
        stages = {}
        for s in STAGES:
            if s == "overall":
                continue
            fc_count = d["stage_failures"].get(s, 0)
            if fc_count == 0:
                stages[s] = {"status": "green", "detail": "no failures"}
            else:
                fcs = [fc for fc, _ in d["failure_classes"].items() if STAGE_MAP.get(fc) == s]
                stages[s] = {"status": "red", "detail": f"{fc_count} ({', '.join(fcs[:2])})"}

        stage_statuses = [v["status"] for k, v in stages.items()]
        red_count = stage_statuses.count("red")
        if red_count == 0:
            stages["overall"] = {"status": "green", "detail": "all clear"}
        elif red_count == 1:
            stages["overall"] = {"status": "yellow", "detail": f"1 category failing"}
        else:
            stages["overall"] = {"status": "red", "detail": f"{red_count} categories failing"}

        all_ns_stages.append(stages)

        if d["real_fail"] == 0:
            continue

        top_fc = max(d["failure_classes"], key=d["failure_classes"].get) if d["failure_classes"] else None

        catalog_item = strip_sandbox_prefix(ns)

        classification = classify_namespace(
            ns, catalog_item, d["failure_classes"],
            first_eval_map.get(ns), baselines,
        )

        by_namespace.append({
            "namespace": ns,
            "cluster": d["cluster"],
            "catalog_item": catalog_item,
            "lab_name": ns_display_names.get(ns) or guid_lab_names.get(ns.split("-")[1] if ns.startswith("sandbox-") and len(ns.split("-")) >= 3 else "", "") or catalog_display_names.get(catalog_item, catalog_item),
            "owner": ns_owners.get(ns),
            "pass": d["pass"],
            "fail": d["fail"],
            "total": d["total"],
            "health_pct": health_pct,
            "top_failure": top_fc,
            "attention": classification["attention"],
            "attention_reason": classification["reason"],
            "stages": stages,
        })

    try:
        from engine.attention_classifier import should_auto_investigate
        from db.models import InvestigationRecord
        investigated_ns = set(
            row.lab_code for row in
            db.query(InvestigationRecord.lab_code).distinct().all()
        )
        for entry in by_namespace:
            if entry["attention"] not in ("stuck", "anomalous"):
                continue
            if entry["namespace"] in investigated_ns:
                continue
            _, reason, _ = should_auto_investigate(
                db, entry["namespace"],
                entry.get("top_failure") or "",
                entry.get("cluster") or "",
            )
            entry["investigation_skip_reason"] = reason
    except Exception:
        pass

    ATTENTION_ORDER = {"stuck": 0, "anomalous": 1, "provisioning": 2, "expected": 3}
    by_namespace.sort(key=lambda r: (ATTENTION_ORDER.get(r.get("attention", "expected"), 3), -r["fail"]))

    lab_map: Dict[str, Dict] = {}
    for entry in by_namespace:
        ns = entry["namespace"]
        parts = ns.split("-")
        lab_key = "-".join(parts[:2]) if len(parts) >= 2 else ns
        if lab_key not in lab_map:
            lab_map[lab_key] = {"namespaces": 0, "pass": 0, "fail": 0, "total": 0,
                                "clusters": set(), "stage_failures": {s: 0 for s in STAGES},
                                "failure_classes": {}}
        m = lab_map[lab_key]
        m["namespaces"] += 1
        m["pass"] += entry["pass"]
        m["fail"] += entry["fail"]
        m["total"] += entry["total"]
        m["clusters"].add(entry["cluster"])
        for fc, cnt in ns_data[ns]["failure_classes"].items():
            m["failure_classes"][fc] = m["failure_classes"].get(fc, 0) + cnt
            stage = STAGE_MAP.get(fc, "workload")
            m["stage_failures"][stage] += cnt

    by_lab = []
    for lab, m in sorted(lab_map.items(), key=lambda x: x[1]["fail"], reverse=True):
        stages = {}
        for s in STAGES:
            if s == "overall":
                continue
            fc_count = m["stage_failures"].get(s, 0)
            if fc_count == 0:
                stages[s] = {"status": "green", "detail": "ok"}
            else:
                stages[s] = {"status": "red", "detail": str(fc_count)}
        red_count = sum(1 for v in stages.values() if v["status"] == "red")
        if red_count == 0:
            stages["overall"] = {"status": "green", "detail": "all clear"}
        elif red_count == 1:
            stages["overall"] = {"status": "yellow", "detail": "1 failing"}
        else:
            stages["overall"] = {"status": "red", "detail": f"{red_count} failing"}

        by_lab.append({
            "lab_code": lab,
            "namespaces": m["namespaces"],
            "clusters": sorted(m["clusters"] - {""}),
            "fail": m["fail"],
            "total": m["total"],
            "stages": stages,
        })

    cluster_map: Dict[str, Dict] = {}
    for entry in by_namespace:
        c = entry["cluster"] or "unknown"
        if c not in cluster_map:
            cluster_map[c] = {"namespaces": 0, "pass": 0, "fail": 0, "total": 0,
                              "stage_failures": {s: 0 for s in STAGES},
                              "failure_classes": {}}
        cm = cluster_map[c]
        cm["namespaces"] += 1
        cm["pass"] += entry["pass"]
        cm["fail"] += entry["fail"]
        cm["total"] += entry["total"]
        for fc, cnt in ns_data[entry["namespace"]]["failure_classes"].items():
            cm["failure_classes"][fc] = cm["failure_classes"].get(fc, 0) + cnt
            stage = STAGE_MAP.get(fc, "workload")
            cm["stage_failures"][stage] += cnt

    by_cluster = []
    for c, cm in sorted(cluster_map.items(), key=lambda x: x[1]["fail"], reverse=True):
        stages = {}
        for s in STAGES:
            if s == "overall":
                continue
            fc_count = cm["stage_failures"].get(s, 0)
            if fc_count == 0:
                stages[s] = {"status": "green", "detail": "ok"}
            else:
                top_fcs = sorted(
                    [(fc, cnt) for fc, cnt in cm["failure_classes"].items() if STAGE_MAP.get(fc) == s],
                    key=lambda x: -x[1],
                )
                stages[s] = {"status": "red", "detail": f"{fc_count} ({top_fcs[0][0]})" if top_fcs else str(fc_count)}
        red_count = sum(1 for v in stages.values() if v["status"] == "red")
        if red_count == 0:
            stages["overall"] = {"status": "green", "detail": "all clear"}
        elif red_count == 1:
            stages["overall"] = {"status": "yellow", "detail": "1 failing"}
        else:
            stages["overall"] = {"status": "red", "detail": f"{red_count} failing"}

        by_cluster.append({
            "cluster": c,
            "namespaces": cm["namespaces"],
            "fail": cm["fail"],
            "total": cm["total"],
            "top_failure": max(cm["failure_classes"], key=cm["failure_classes"].get) if cm["failure_classes"] else None,
            "stages": stages,
        })

    try:
        from db.models import ResolutionRecord
        failing_ns = [r["namespace"] for r in by_namespace]
        if failing_ns:
            latest_resolutions = (
                db.query(ResolutionRecord)
                .filter(ResolutionRecord.lab_code.in_(failing_ns))
                .order_by(ResolutionRecord.resolved_at.desc())
                .all()
            )
            res_by_ns: Dict[str, Dict] = {}
            for r in latest_resolutions:
                if r.lab_code not in res_by_ns:
                    res_by_ns[r.lab_code] = {
                        "resolution_type": r.resolution_type,
                        "resolved_by": r.resolved_by,
                        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
                        "ttr_minutes": round(r.ttr_seconds / 60.0, 1) if r.ttr_seconds else None,
                        "failure_class": r.failure_class,
                    }
            for entry in by_namespace:
                entry["last_resolution"] = res_by_ns.get(entry["namespace"])
    except Exception:
        pass

    total_ns_count = len(all_ns_stages)
    stage_totals: Dict[str, Dict[str, int]] = {s: {"green": 0, "yellow": 0, "red": 0} for s in STAGES}
    for stages in all_ns_stages:
        for s in STAGES:
            st = stages.get(s, {}).get("status", "green")
            stage_totals[s][st] = stage_totals[s].get(st, 0) + 1

    attention_counts: Dict[str, int] = {}
    for entry in by_namespace:
        a = entry.get("attention", "expected")
        attention_counts[a] = attention_counts.get(a, 0) + 1

    cat_health: Dict[str, Dict] = {}
    for entry in by_namespace:
        cat = entry.get("catalog_item", "unknown")
        if cat not in cat_health:
            cat_health[cat] = {"total": 0, "stuck": 0, "anomalous": 0, "expected": 0, "provisioning": 0}
        cat_health[cat]["total"] += 1
        cat_health[cat][entry.get("attention", "expected")] += 1

    by_catalog_item = sorted([
        {"catalog_item": cat, "lab_name": catalog_display_names.get(cat, cat), **counts}
        for cat, counts in cat_health.items()
    ], key=lambda x: x["stuck"] + x["anomalous"], reverse=True)

    by_failure_class = _build_failure_class_view(by_namespace, baselines, ns_data, db)

    return {
        "stages": STAGES,
        "by_namespace": by_namespace[:500],
        "by_lab": by_lab,
        "by_cluster": by_cluster,
        "by_catalog_item": by_catalog_item,
        "by_failure_class": by_failure_class,
        "summary": {
            "total_namespaces": len(by_namespace),
            "total_monitored": total_ns_count,
            "total_labs": len(by_lab),
            "total_clusters": len(by_cluster),
            "needs_attention": attention_counts.get("stuck", 0) + attention_counts.get("anomalous", 0),
            "expected_noise": attention_counts.get("expected", 0) + attention_counts.get("provisioning", 0),
            "attention_counts": attention_counts,
            "stages_health": {
                s: "red" if t["red"] > 0 else "yellow" if t["yellow"] > 0 else "green"
                for s, t in stage_totals.items()
            },
            "stage_counts": stage_totals,
        },
    }
