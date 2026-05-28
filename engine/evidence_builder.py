"""Shared evidence builder — assembles consistent context bundles for all LLM calls.

Every LLM call should get relevant context from all available data sources.
This module provides composable evidence sections that can be mixed based on
the call type (classify, remediate, forecast, summarize, etc.).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("stargate.evidence")


def build_evidence(
    sections: List[str],
    lab_code: Optional[str] = None,
    cluster_name: Optional[str] = None,
    failure_class: Optional[str] = None,
    db=None,
) -> str:
    """Build an evidence bundle from named sections.

    Available sections:
      'cluster_state', 'pool_state', 'aap_summary', 'sandbox_api',
      'session_schedule', 'workload_complexity', 'pool_velocity',
      'readiness_gates', 'top_failures'

    Each section is guarded by try/except — missing data doesn't break the bundle.
    """
    parts = []

    for section in sections:
        try:
            if section == "cluster_state":
                parts.append(_cluster_state(cluster_name))
            elif section == "pool_state":
                parts.append(_pool_state(lab_code))
            elif section == "aap_summary":
                parts.append(_aap_summary(lab_code))
            elif section == "sandbox_api":
                parts.append(_sandbox_api())
            elif section == "session_schedule":
                parts.append(_session_schedule())
            elif section == "workload_complexity":
                parts.append(_workload_complexity())
            elif section == "pool_velocity":
                parts.append(_pool_velocity(db))
            elif section == "readiness_gates":
                parts.append(_readiness_gates())
            elif section == "top_failures":
                parts.append(_top_failures(db))
        except Exception as e:
            logger.debug(f"Evidence section '{section}' failed: {e}")

    return "\n\n".join(p for p in parts if p)


def _cluster_state(cluster_name: Optional[str] = None) -> str:
    from api.routers._shared import _load_latest_scan
    scans = _load_latest_scan()
    if not scans:
        return ""
    if cluster_name:
        scans = [s for s in scans if s.get("cluster") == cluster_name] or scans[:3]
    else:
        scans = scans[:8]
    lines = ["### Cluster State"]
    for s in scans:
        lines.append(f"- {s.get('cluster')}: CPU={s.get('avg_cpu_pct', '?')}%, VMs={s.get('total_vms', 0)}, "
                     f"sandboxes={s.get('sandbox_active', 0)}, health={s.get('health_rate', '?')}%")
    return "\n".join(lines)


def _pool_state(lab_code: Optional[str] = None) -> str:
    from api.routers._shared import _load_latest_babylon
    babylon = _load_latest_babylon()
    if not babylon:
        return ""
    pools = babylon.get("pools", {})
    if not pools:
        return ""
    lines = ["### Pool State"]
    for pname, pdata in list(pools.items())[:10]:
        if not isinstance(pdata, dict):
            continue
        if lab_code and lab_code.lower() not in pname.lower():
            continue
        lines.append(f"- {pname}: available={pdata.get('available', '?')}, "
                     f"ready={pdata.get('ready', '?')}, min={pdata.get('min_available', '?')}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _aap_summary(lab_code: Optional[str] = None) -> str:
    from collectors.aap.collect_aap import collect_aap_jobs
    aap = collect_aap_jobs()
    s = aap.get("summary", {})
    if s.get("total_jobs", 0) == 0:
        return ""
    lines = [f"### AAP Provisioning",
             f"SLI: {s.get('provision_sli', 0)}% (target {s.get('provision_sli_target', 93)}%)",
             f"Failed 24h: {s.get('failed_24h', 0)}, Total: {s.get('total_jobs', 0)}"]
    if lab_code:
        lab_info = aap.get("by_lab", {}).get(lab_code)
        if lab_info:
            lines.append(f"Lab {lab_code}: {lab_info['total']} failures — {lab_info.get('top_error', '')}")
    else:
        errors = aap.get("top_errors", [])
        for e in errors[:3]:
            lines.append(f"- {e['failing_task']}: {e.get('error','')[:80]} ({e['count']}x)")
    return "\n".join(lines)


def _sandbox_api() -> str:
    from collectors.sandbox_api.collect_sandbox_api import collect_sandbox_counts
    from api.routers._shared import _load_latest_scan
    scans = _load_latest_scan() or []
    counts = collect_sandbox_counts(scans)
    if counts.get("total_sandboxes", 0) == 0:
        return ""
    return (f"### Sandbox-API\n"
            f"Active: {counts.get('active', 0)}, Failing: {counts.get('failing', 0)}, "
            f"Crashloop: {counts.get('crashloop', 0)}")


def _session_schedule() -> str:
    from api.routers._shared import _fetch_labagator_sessions
    sessions = _fetch_labagator_sessions()
    if not sessions:
        return ""
    from collections import Counter
    by_lab = Counter(s.get("lab_code", "") for s in sessions if s.get("lab_code"))
    lines = ["### Session Schedule"]
    for lab, count in by_lab.most_common(10):
        lines.append(f"- {lab}: {count} sessions")
    return "\n".join(lines)


def _workload_complexity() -> str:
    import os
    from pathlib import Path
    agv_dir = os.environ.get("STARGATE_AGNOSTICV_DIR", "")
    if not agv_dir:
        return ""
    from constraints.agnosticv_loader import load_all_constraints
    from engine.workload_complexity import compute_complexity_score
    all_c = load_all_constraints(Path(agv_dir))
    if not all_c:
        return ""
    scored = sorted(
        [(slug, compute_complexity_score(c)) for slug, c in list(all_c.items())[:30]],
        key=lambda x: -x[1]["score"]
    )[:5]
    lines = ["### Workload Complexity (top 5)"]
    for slug, sc in scored:
        lines.append(f"- {slug}: score={sc['score']:.2f}, est {sc['estimated_provision_minutes']}min")
    return "\n".join(lines)


def _pool_velocity(db=None) -> str:
    if not db:
        return ""
    from engine.pool_velocity import compute_pool_velocity
    from db.repository import get_pool_timeline
    from api.routers._shared import _load_latest_babylon
    babylon = _load_latest_babylon()
    if not babylon:
        return ""
    lines = ["### Pool Velocity"]
    for pname, pdata in babylon.get("pools", {}).items():
        if not isinstance(pdata, dict) or not pdata.get("min_available", 0):
            continue
        timeline = get_pool_timeline(db, pname, hours=6)
        if len(timeline) >= 2:
            vel = compute_pool_velocity(timeline)
            if vel["trend"] != "stable":
                lines.append(f"- {pname}: {vel['handles_per_hour']:.1f}/hr ({vel['trend']})")
    return "\n".join(lines) if len(lines) > 1 else ""


def _readiness_gates() -> str:
    from api.contracts import get_freshness
    f = get_freshness()
    fresh = [s for s, info in f.items() if info.get("status") == "fresh"]
    stale = [s for s, info in f.items() if info.get("status") in ("stale", "unknown")]
    lines = [f"### Data Freshness",
             f"Fresh: {', '.join(fresh) if fresh else 'none'}",
             f"Stale/unknown: {', '.join(stale) if stale else 'none'}"]
    return "\n".join(lines)


def _top_failures(db=None) -> str:
    if not db:
        return ""
    from db.models import EvaluationRecord
    from sqlalchemy import func
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    results = (
        db.query(EvaluationRecord.result_failure_class, func.count(EvaluationRecord.id))
        .filter(EvaluationRecord.result_outcome == "fail", EvaluationRecord.evaluated_at >= cutoff)
        .group_by(EvaluationRecord.result_failure_class)
        .order_by(func.count(EvaluationRecord.id).desc())
        .limit(8)
        .all()
    )
    if not results:
        return ""
    lines = ["### Top Failures (24h)"]
    for fc, count in results:
        lines.append(f"- {fc or 'unclassified'}: {count}")
    return "\n".join(lines)
