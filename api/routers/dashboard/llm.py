"""LLM-powered dashboard endpoints — failure interpretation, trend analysis,
capacity analysis, and recommendation reasoning."""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from db.database import get_db
from api.routers._shared import (
    _load_latest_scan,
    _load_latest_babylon,
    limiter,
    require_admin,
)

router = APIRouter()
logger = logging.getLogger("stargate.dashboard.llm")


# ---------------------------------------------------------------------------
# LLM-enhanced recommendation reasoning
# ---------------------------------------------------------------------------

@router.post("/dashboard/recommendation-reasoning")
@limiter.limit("10/minute")
def dashboard_recommendation_reasoning(request: Request, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Add AI reasoning and actionable insights to policy recommendations."""
    from api.routers.dashboard.classification import dashboard_provisioning_recommendations
    recs_data = dashboard_provisioning_recommendations(db)
    recs = recs_data.get("recommendations", [])

    if not recs:
        return {"prioritized": [], "groups": [], "summary": "No active recommendations.", "llm_used": False}

    evidence_parts = []
    evidence_parts.append(f"## Current Recommendations ({len(recs)} total)")
    for r in recs[:20]:
        evidence_parts.append(
            f"- [{r.get('urgency','?')}] {r.get('type','?')}: {r.get('recommendation','')} "
            f"(target: {r.get('lab_code', r.get('cluster', r.get('pool_name', '?')))}, "
            f"confidence: {r.get('confidence_score', '?')})"
        )

    try:
        from collectors.aap.collect_aap import collect_aap_jobs
        aap = collect_aap_jobs()
        s = aap.get("summary", {})
        if s.get("total_jobs", 0) > 0:
            errors = aap.get("top_errors", [])
            evidence_parts.append(f"\n## AAP Context\nSLI: {s.get('provision_sli')}%, Failed: {s.get('failed_24h')}")
            for e in errors[:3]:
                evidence_parts.append(f"  - {e['failing_task']}: {e.get('error','')[:80]} ({e['count']}x)")
    except Exception:
        pass

    try:
        scans = _load_latest_scan()
        cluster_info = [f"  - {s.get('cluster')}: CPU={s.get('avg_cpu_pct')}%, VMs={s.get('total_vms')}, sandboxes={s.get('sandbox_active')}" for s in scans[:8]]
        evidence_parts.append(f"\n## Cluster State\n" + "\n".join(cluster_info))
    except Exception:
        pass

    try:
        from engine.pool_velocity import compute_pool_velocity
        from db.repository import get_pool_timeline
        babylon = _load_latest_babylon()
        if babylon:
            depleting = []
            for pname, pdata in babylon.get("pools", {}).items():
                if isinstance(pdata, dict) and pdata.get("min_available", 0) > 0:
                    timeline = get_pool_timeline(db, pname, hours=6)
                    if len(timeline) >= 2:
                        vel = compute_pool_velocity(timeline)
                        if vel["trend"] == "depleting":
                            depleting.append(f"  - {pname}: {vel['handles_per_hour']:.1f}/hr")
            if depleting:
                evidence_parts.append(f"\n## Depleting Pools\n" + "\n".join(depleting))
    except Exception:
        pass

    evidence_str = "\n".join(evidence_parts)

    try:
        from api.llm import call_llm, load_prompt
        prompt = load_prompt("recommendation-reasoning")
        llm_result = call_llm(
            endpoint="recommendation-reasoning",
            messages=[
                {"role": "system", "content": prompt.get("system", "Analyze recommendations. Respond with JSON only.")},
                {"role": "user", "content": prompt.get("user_template", "{evidence}").replace("{evidence}", evidence_str)},
            ],
            max_tokens=prompt.get("max_tokens", 1500),
            temperature=prompt.get("temperature", 0.2),
            timeout=60, db=db,
            prompt_version=prompt.get("version"),
        )
        if llm_result.get("success"):
            analysis = json.loads(llm_result["content"])
            return {**analysis, "llm_used": True, "recommendation_count": len(recs)}
    except Exception:
        pass

    return {
        "prioritized": [{"type": r.get("type"), "target": r.get("lab_code", r.get("cluster", "")),
                         "urgency": r.get("urgency"), "root_cause": "Rule-based detection",
                         "impact": r.get("recommendation"), "steps": [], "auto_remediable": False}
                        for r in recs[:10]],
        "groups": [],
        "summary": f"{len(recs)} recommendations from policy engine. LLM reasoning unavailable.",
        "llm_used": False,
        "recommendation_count": len(recs),
    }


# ---------------------------------------------------------------------------
# Failure interpretation (LLM-powered)
# ---------------------------------------------------------------------------

@router.post("/dashboard/failure-interpretation")
@limiter.limit("10/minute")
def dashboard_failure_interpretation(request: Request, req: dict, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """LLM-powered explanation of why a rubric evaluation failed."""
    run_id = req.get("run_id", "")
    stage_id = req.get("stage_id", "")

    evidence_parts = []
    failure_class = None

    try:
        from db.models import EvaluationRecord
        ev = db.query(EvaluationRecord).filter(
            EvaluationRecord.run_id == run_id,
            EvaluationRecord.stage_id == stage_id,
        ).order_by(EvaluationRecord.id.desc()).first()
        if ev:
            failure_class = ev.failure_class
            evidence_parts.append(f"## Evaluation Result\n- Stage: {stage_id}\n- Outcome: {ev.outcome}\n- Failure class: {failure_class}\n- Message: {ev.message}")
            if ev.criteria_results:
                evidence_parts.append(f"## Criteria Results\n{json.dumps(ev.criteria_results, indent=2)}")
    except Exception as e:
        evidence_parts.append(f"## Evaluation\nUnavailable: {e}")

    try:
        scans = _load_latest_scan()
        if scans:
            cluster_info = [{"cluster": s.get("cluster"), "cpu": s.get("avg_cpu_pct"), "vms": s.get("total_vms")} for s in scans[:5]]
            evidence_parts.append(f"## Cluster State\n{json.dumps(cluster_info)}")
    except Exception:
        pass

    evidence_str = "\n\n".join(evidence_parts) if evidence_parts else "No evaluation data found"

    try:
        from api.llm import call_llm, load_prompt
        prompt = load_prompt("failure-interpretation")
        result = call_llm(
            endpoint="failure-interpretation",
            messages=[
                {"role": "system", "content": prompt.get("system", "Explain this failure. Be concise.")},
                {"role": "user", "content": prompt.get("user_template", "{evidence}").replace("{evidence}", evidence_str)},
            ],
            max_tokens=prompt.get("max_tokens", 400),
            temperature=prompt.get("temperature", 0.2),
            timeout=30, db=db, prompt_version=prompt.get("version"),
        )
        interpretation = result.get("content", "Unable to interpret") if result.get("success") else "LLM unavailable"
    except Exception as e:
        interpretation = f"Interpretation unavailable: {e}"

    return {
        "interpretation": interpretation,
        "failure_class": failure_class,
        "stage_id": stage_id,
        "run_id": run_id,
    }


# ---------------------------------------------------------------------------
# Trend analysis (LLM-powered)
# ---------------------------------------------------------------------------

@router.post("/dashboard/trend-analysis")
@limiter.limit("10/minute")
def dashboard_trend_analysis(request: Request, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """LLM-powered trend and pattern detection across evaluation history."""
    evidence_parts = []

    try:
        from db.models import EvaluationRecord
        from sqlalchemy import func
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_evals = db.query(
            EvaluationRecord.stage_id,
            EvaluationRecord.outcome,
            EvaluationRecord.failure_class,
            func.count(EvaluationRecord.id),
        ).filter(
            EvaluationRecord.evaluated_at >= cutoff
        ).group_by(
            EvaluationRecord.stage_id,
            EvaluationRecord.outcome,
            EvaluationRecord.failure_class,
        ).all()
        trend_data = [{"stage": r[0], "outcome": r[1], "failure_class": r[2], "count": r[3]} for r in recent_evals]
        evidence_parts.append(f"## Evaluation Trends (24h)\n{json.dumps(trend_data, indent=2)}")
    except Exception as e:
        evidence_parts.append(f"## Evaluation Trends\nUnavailable: {e}")

    try:
        from engine.pool_velocity import compute_pool_velocity
        from db.repository import get_pool_timeline
        babylon = _load_latest_babylon()
        if babylon:
            pool_trends = {}
            for pname in list(babylon.get("pools", {}).keys())[:10]:
                timeline = get_pool_timeline(db, pname, hours=24)
                if timeline:
                    pool_trends[pname] = compute_pool_velocity(timeline)
            if pool_trends:
                evidence_parts.append(f"## Pool Velocity Trends (24h)\n{json.dumps(pool_trends, indent=2)}")
    except Exception:
        pass

    try:
        scans = _load_latest_scan()
        if scans:
            cluster_health = [{"cluster": s.get("cluster"), "health": s.get("health_rate"), "cpu": s.get("avg_cpu_pct")} for s in scans[:10]]
            evidence_parts.append(f"## Cluster Health\n{json.dumps(cluster_health)}")
    except Exception:
        pass

    evidence_str = "\n\n".join(evidence_parts) if evidence_parts else "No trend data available"

    try:
        from api.llm import call_llm, load_prompt
        prompt = load_prompt("trend-analysis")
        result = call_llm(
            endpoint="trend-analysis",
            messages=[
                {"role": "system", "content": prompt.get("system", "Analyze trends. Respond with JSON only.")},
                {"role": "user", "content": prompt.get("user_template", "{evidence}").replace("{evidence}", evidence_str)},
            ],
            max_tokens=prompt.get("max_tokens", 800),
            temperature=prompt.get("temperature", 0.2),
            timeout=60, db=db, prompt_version=prompt.get("version"),
        )
        analysis = json.loads(result["content"]) if result.get("success") else None
    except Exception:
        analysis = None

    return {
        "analysis": analysis,
        "evidence_summary": f"{len(evidence_parts)} data sections analyzed",
    }


# ---------------------------------------------------------------------------
# Capacity analysis (LLM-powered)
# ---------------------------------------------------------------------------

@router.post("/dashboard/capacity-analysis")
@limiter.limit("5/minute")
def dashboard_capacity_analysis(request: Request, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """LLM-powered capacity forecast — pool velocity, workload complexity, scheduling risks."""
    from engine.pool_velocity import compute_pool_velocity, estimate_exhaustion
    from engine.workload_complexity import compute_complexity_score

    evidence_parts = []

    pool_velocities = {}
    try:
        from db.repository import get_pool_timeline
        babylon = _load_latest_babylon()
        if babylon:
            pools = babylon.get("pools", {})
            for pname, pdata in pools.items():
                if isinstance(pdata, dict):
                    timeline = get_pool_timeline(db, pname, hours=6)
                    velocity = compute_pool_velocity(timeline)
                    available = pdata.get("available", 0) if isinstance(pdata, dict) else 0
                    eta = estimate_exhaustion(available, velocity["handles_per_hour"])
                    pool_velocities[pname] = {**velocity, "available": available, "exhaustion_hours": eta}
            evidence_parts.append(f"## Pool Velocity\n{json.dumps(pool_velocities, indent=2)}")
    except Exception as e:
        evidence_parts.append(f"## Pool Velocity\nUnavailable: {e}")

    complexities = {}
    try:
        from constraints.agnosticv_loader import load_all_constraints
        import os
        agv_dir = os.environ.get("STARGATE_AGNOSTICV_DIR", "")
        if agv_dir:
            from pathlib import Path
            all_constraints = load_all_constraints(Path(agv_dir))
            for slug, constraints in list(all_constraints.items())[:30]:
                complexities[slug] = compute_complexity_score(constraints)
            evidence_parts.append(f"## Workload Complexity (top 30)\n{json.dumps({k: v['score'] for k, v in sorted(complexities.items(), key=lambda x: -x[1]['score'])[:15]}, indent=2)}")
    except Exception as e:
        evidence_parts.append(f"## Workload Complexity\nUnavailable: {e}")

    try:
        scans = _load_latest_scan()
        if scans:
            cluster_summary = [{
                "cluster": s.get("cluster"),
                "avg_cpu": s.get("avg_cpu_pct"),
                "total_vms": s.get("total_vms"),
                "vms_per_node": s.get("vms_per_node"),
                "health_rate": s.get("health_rate"),
            } for s in scans[:10]]
            evidence_parts.append(f"## Cluster State\n{json.dumps(cluster_summary, indent=2)}")
    except Exception:
        pass

    evidence_str = "\n\n".join(evidence_parts) if evidence_parts else "No data available"

    llm_result = None
    try:
        from api.llm import call_llm, load_prompt
        prompt = load_prompt("capacity-forecast")
        llm_result = call_llm(
            endpoint="capacity-forecast",
            messages=[
                {"role": "system", "content": prompt.get("system", "Analyze capacity. Respond with JSON only.")},
                {"role": "user", "content": prompt.get("user_template", "{evidence}").replace("{evidence}", evidence_str)},
            ],
            max_tokens=prompt.get("max_tokens", 1500),
            temperature=prompt.get("temperature", 0.2),
            timeout=60,
            db=db,
            prompt_version=prompt.get("version"),
        )
    except Exception as e:
        llm_result = {"success": False, "error": str(e)}

    return {
        "pool_velocities": pool_velocities,
        "workload_complexities": {k: {"score": v["score"], "estimated_minutes": v["estimated_provision_minutes"]} for k, v in complexities.items()},
        "llm_analysis": json.loads(llm_result["content"]) if llm_result and llm_result.get("success") else None,
        "llm_error": llm_result.get("error") if llm_result and not llm_result.get("success") else None,
        "evidence_summary": f"{len(pool_velocities)} pools tracked, {len(complexities)} labs scored",
    }
