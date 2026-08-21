"""Classification proposals and provisioning recommendations."""

import json
import re
import time
from datetime import datetime, timezone
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from db import repository
from api.routers._shared import (
    _load_latest_scan,
    _load_latest_babylon,
    _fetch_labagator_sessions,
    _load_agnosticv_constraints,
    require_admin,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Classification proposals
# ---------------------------------------------------------------------------

@router.post("/dashboard/propose-classification")
def propose_classification(req: dict, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Send unclassified failure to Granite LLM and store proposed classification."""
    import urllib.request as urllib_req
    from db.models import EvaluationRecord, ProposedClassification

    run_id = req.get("run_id", "")
    stage_id = req.get("stage_id", "")
    raw_message = req.get("message", "")
    message = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw_message)[:2000]

    # Get the evaluation context
    eval_record = None
    if run_id and stage_id:
        eval_record = (
            db.query(EvaluationRecord)
            .filter(EvaluationRecord.run_id == run_id, EvaluationRecord.stage_id == stage_id)
            .first()
        )

    # Build enriched evidence for LLM
    lab = eval_record.lab_code if eval_record else req.get('lab_code', 'unknown')
    clust = eval_record.cluster_name if eval_record else req.get('cluster', 'unknown')

    evidence_parts = [f"""## Failure Details
- Stage: {stage_id}
- Cluster: {clust}
- Lab/Namespace: {lab}
- Current classification: unclassified

<user_data>
{message or (eval_record.message if eval_record else 'unknown')}
</user_data>"""]

    # Criteria results if available
    if eval_record and eval_record.criteria_results:
        evidence_parts.append(f"## Criteria Results\n{json.dumps(eval_record.criteria_results, indent=2)}")

    # Similar past classifications
    similar = repository.get_similar_classifications(db, message or (eval_record.message if eval_record else ""), limit=5)
    if similar:
        sim_lines = ["## Similar Past Classifications"]
        for s in similar:
            status = "APPROVED" if s["approved"] else "REJECTED" if s["approved"] is False else "pending"
            sim_lines.append(f"- \"{s['original_message']}\" → {s['proposed_class']} (confidence {s['confidence']}, {status}, match {s['match_score']:.0%})")
        evidence_parts.append("\n".join(sim_lines))

    # Lab failure history
    if lab and lab != "unknown":
        lab_freq = repository.get_failure_class_frequency(db, lab_code=lab, limit=50)
        if lab_freq:
            freq_lines = [f"## Lab {lab} Failure History"]
            for fc, ct in sorted(lab_freq.items(), key=lambda x: -x[1])[:8]:
                freq_lines.append(f"- {fc}: {ct} occurrences")
            evidence_parts.append("\n".join(freq_lines))

    # Cluster failure surge
    if clust and clust != "unknown":
        cluster_freq = repository.get_failure_class_frequency(db, cluster_name=clust, limit=50)
        if cluster_freq:
            total_failures = sum(cluster_freq.values())
            freq_lines = [f"## Cluster {clust} Current Failures ({total_failures} total)"]
            for fc, ct in sorted(cluster_freq.items(), key=lambda x: -x[1])[:8]:
                freq_lines.append(f"- {fc}: {ct}")
            evidence_parts.append("\n".join(freq_lines))

    # Load all known failure classes from YAML corpus
    try:
        from engine.failure_class_loader import get_all_classes, reload
        reload()
        all_classes = get_all_classes()
        class_lines = [f"- {name}: {data.get('description', '')}" for name, data in sorted(all_classes.items())]
        evidence_parts.append("## Known Failure Classes ({} total)\n{}".format(len(class_lines), "\n".join(class_lines)))
    except Exception:
        evidence_parts.append("""## Known Failure Classes
- pods_not_ready: deployment exists but pods not running
- pods_crashlooping: pods in CrashLoopBackOff
- deployment_missing: no deployment found in namespace
- route_missing: no route object exists
- namespace_missing: namespace does not exist
- cluster_unreachable: cannot connect to cluster API
- cluster_overloaded: cluster CPU/memory exceeds thresholds
- provision_failed: AnarchySubject provisioning failed""")

    evidence = "\n\n".join(evidence_parts)

    prompt = f"""{evidence}

## Task
Using the failure message, criteria results, similar past classifications, and lab/cluster failure history above, propose:
1. The most likely failure_class from the known list (or a new class name if none fit)
2. The conditions that would match this failure (as key == value pairs)
3. Your confidence level (0.0 to 1.0) — higher if similar past classifications match, lower if this is novel

Respond in this exact JSON format:
{{"proposed_class": "class_name", "conditions": ["criterion == value"], "confidence": 0.85, "reasoning": "brief explanation"}}"""

    from api.llm import call_llm, load_prompt, LLM_MODEL
    _classify_prompt = load_prompt("classify")
    llm_result = call_llm(
        endpoint="classify",
        messages=[
            {"role": "system", "content": _classify_prompt.get("system", "You are a failure classification expert for OpenShift lab environments. Respond with valid JSON only.")},
            {"role": "user", "content": prompt},
        ],
        max_tokens=_classify_prompt.get("max_tokens", 500),
        temperature=_classify_prompt.get("temperature", 0.1),
        timeout=30,
        context={"lab_code": eval_record.lab_code if eval_record else None, "cluster_name": eval_record.cluster_name if eval_record else None},
        db=db,
        prompt_version=_classify_prompt.get("version"),
    )
    if not llm_result["success"]:
        return {"error": f"LLM call failed: {llm_result['error']}"}
    llm_response = llm_result["content"]

    # Parse the LLM response
    proposed_class = "unknown"
    conditions = []
    confidence = 0.0
    reasoning = ""
    try:
        parsed = json.loads(llm_response)
        proposed_class = parsed.get("proposed_class", "unknown")
        conditions = parsed.get("conditions", [])
        confidence = parsed.get("confidence", 0.0)
        reasoning = parsed.get("reasoning", "")
    except json.JSONDecodeError:
        proposed_class = "parse_error"

    if not re.match(r"^[a-z][a-z0-9_]*$", proposed_class):
        proposed_class = "unknown"

    # Store the proposal
    proposal = ProposedClassification(
        run_id=run_id,
        stage_id=stage_id,
        original_message=message or (eval_record.message if eval_record else None),
        proposed_class=proposed_class,
        proposed_conditions=conditions,
        confidence=confidence,
        llm_model=llm_result["usage"].get("model", LLM_MODEL) if llm_result.get("usage") else LLM_MODEL,
        proposed_at=datetime.now(timezone.utc),
        llm_metric_id=llm_result.get("metric_id"),
    )
    db.add(proposal)
    db.commit()

    return {
        "proposal_id": proposal.id,
        "proposed_class": proposed_class,
        "conditions": conditions,
        "confidence": confidence,
        "reasoning": reasoning,
        "llm_raw": llm_response,
        "status": "pending_review",
    }


@router.post("/dashboard/propose-classification/{proposal_id}/review")
def review_classification(proposal_id: int, req: dict, db: Session = Depends(get_db), _auth=Depends(require_admin)):
    """Approve or reject a proposed classification."""
    from db.models import ProposedClassification

    proposal = db.query(ProposedClassification).filter(ProposedClassification.id == proposal_id).first()
    if not proposal:
        raise HTTPException(404, "Proposal not found")

    action = req.get("action", "")
    if action not in ("approve", "reject"):
        raise HTTPException(422, "action must be 'approve' or 'reject'")

    proposal.reviewed = True
    proposal.approved = action == "approve"
    proposal.reviewed_by = req.get("reviewed_by", "ops")
    proposal.reviewed_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "proposal_id": proposal.id,
        "proposed_class": proposal.proposed_class,
        "action": action,
        "status": "approved" if proposal.approved else "rejected",
    }


@router.get("/dashboard/proposed-classifications")
def list_proposed_classifications(db: Session = Depends(get_db)):
    """List all proposed classifications."""
    from db.models import ProposedClassification

    proposals = db.query(ProposedClassification).order_by(ProposedClassification.id.desc()).limit(50).all()
    return [
        {
            "id": p.id,
            "run_id": p.run_id,
            "stage_id": p.stage_id,
            "original_message": p.original_message,
            "proposed_class": p.proposed_class,
            "conditions": p.proposed_conditions,
            "confidence": p.confidence,
            "llm_model": p.llm_model,
            "proposed_at": p.proposed_at.isoformat() if p.proposed_at else None,
            "reviewed": p.reviewed,
            "approved": p.approved,
            "reviewed_by": p.reviewed_by,
        }
        for p in proposals
    ]


# ---------------------------------------------------------------------------
# Provisioning recommendations
# ---------------------------------------------------------------------------

_recs_cache: Dict = {"data": None, "ts": 0}

@router.get("/dashboard/provisioning-recommendations")
def dashboard_provisioning_recommendations(db: Session = Depends(get_db)):
    """Generate provisioning recommendations based on current state (display only)."""
    if _recs_cache["data"] and time.time() - _recs_cache["ts"] < 30:
        return _recs_cache["data"]

    from engine.policy import generate_recommendations
    from api.routers.dashboard.deployments import dashboard_summit

    summit_data = dashboard_summit(db)
    labs = summit_data.get("labs", [])

    babylon = _load_latest_babylon()
    pools = babylon.get("pools", {})

    cluster_states = []
    for s in _load_latest_scan():
        cluster_states.append({
            "cluster": s.get("cluster", ""),
            "avg_cpu": s.get("avg_cpu_pct", 0),
            "vms_per_node": s.get("vms_per_node", 0),
            "sandbox_active": s.get("sandbox_active", 0),
        })

    sessions = _fetch_labagator_sessions()

    # Gather evaluation records for rubric context
    eval_records = repository.list_evaluations(db, limit=2000)
    evaluations = [
        {
            "lab_code": getattr(ev, 'lab_code', None) if hasattr(ev, 'lab_code') else ev.get("lab_code"),
            "stage_id": getattr(ev, 'stage_id', None) if hasattr(ev, 'stage_id') else ev.get("stage_id"),
            "outcome": getattr(ev, 'outcome', None) if hasattr(ev, 'outcome') else ev.get("outcome"),
            "failure_class": getattr(ev, 'failure_class', None) if hasattr(ev, 'failure_class') else ev.get("failure_class"),
            "criteria_results": getattr(ev, 'criteria_results', None) if hasattr(ev, 'criteria_results') else ev.get("criteria_results"),
            "evaluated_at": (getattr(ev, 'evaluated_at', None).isoformat() if hasattr(ev, 'evaluated_at') and getattr(ev, 'evaluated_at', None) else None)
                if hasattr(ev, 'evaluated_at') else ev.get("evaluated_at"),
        }
        for ev in eval_records
    ]

    # Gather constraint violations per lab
    from constraints.classifier import classify_constraints
    cv_by_lab: Dict[str, List[Dict]] = {}
    for lab in labs[:50]:
        lc = lab["lab_code"]
        constraints = _load_agnosticv_constraints(lc)
        if constraints:
            violations = classify_constraints(constraints, lab)
            if violations:
                cv_by_lab[lc] = [
                    {"violation_type": v.violation_type, "expected": v.expected, "actual": v.actual,
                     "severity": v.severity, "detail": v.detail}
                    for v in violations
                ]

    result = generate_recommendations(labs, pools, cluster_states, sessions, evaluations=evaluations, constraint_violations=cv_by_lab)

    escalated_clusters = set()
    escalated_failure_classes = set()
    try:
        from db.models import EventLog
        esc_events = (
            db.query(EventLog.cluster_name, EventLog.failure_class)
            .filter(EventLog.priority >= 7)
            .distinct().all()
        )
        for cluster, fc in esc_events:
            if cluster:
                escalated_clusters.add(cluster)
            if fc:
                escalated_failure_classes.add(fc)
    except Exception:
        pass

    lab_clusters = {}
    for lab in labs:
        lc = lab.get("lab_code", "")
        inst_clusters = set()
        for inst in lab.get("instances", []):
            c = inst.get("cluster", "")
            if c:
                inst_clusters.add(c)
        if inst_clusters:
            lab_clusters[lc] = inst_clusters

    for rec in result.get("recommendations", []):
        lab_code = rec.get("lab_code", "")
        rec_clusters = lab_clusters.get(lab_code, set())
        rec["escalated"] = bool(rec_clusters & escalated_clusters)
        if not rec["escalated"] and rec.get("type") == "smoke_test_failing":
            rec["escalated"] = bool(escalated_failure_classes & {"showroom_not_ready", "pods_not_ready", "showroom_pod_down"})

    result["escalated_count"] = sum(1 for r in result.get("recommendations", []) if r.get("escalated"))
    _recs_cache["data"] = result
    _recs_cache["ts"] = time.time()
    return result
