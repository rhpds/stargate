"""Automatic LLM analysis — classifies new failures and generates remediation on each scan cycle.

Called from the MV refresh loop. Only processes failures that don't already
have a ProposedClassification. Sequential calls to avoid overwhelming the LLM endpoint.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("stargate.auto_llm")

MAX_CALLS_PER_CYCLE = 20
THROTTLE_SECONDS = 0.5

_enabled = os.environ.get("STARGATE_AUTO_LLM", "true").lower() != "false"


def is_enabled() -> bool:
    return _enabled


def set_enabled(enabled: bool):
    global _enabled
    _enabled = enabled
    logger.info(f"Auto-LLM {'enabled' if enabled else 'disabled'}")


def run_auto_analysis(db: Session) -> Dict:
    """Find unclassified failures and auto-classify them via LLM.

    Returns summary of what was processed.
    """
    if not _enabled:
        return {"classified": 0, "errors": 0, "skipped": "auto-llm disabled"}

    from db.models import EvaluationRecord, ProposedClassification
    from db import repository

    already_classified_runs = set()
    already_classified_messages = set()
    existing = db.query(
        ProposedClassification.run_id,
        ProposedClassification.stage_id,
        ProposedClassification.original_message,
    ).all()
    for run_id, stage_id, msg in existing:
        already_classified_runs.add((run_id, stage_id))
        if msg:
            already_classified_messages.add((stage_id, msg.strip()[:100]))

    unclassified = (
        db.query(EvaluationRecord)
        .filter(
            EvaluationRecord.outcome == "fail",
            (EvaluationRecord.failure_class.is_(None)) | (EvaluationRecord.failure_class == "unclassified"),
        )
        .order_by(EvaluationRecord.evaluated_at.desc())
        .limit(MAX_CALLS_PER_CYCLE * 3)
        .all()
    )

    to_classify = []
    for ev in unclassified:
        if (ev.run_id, ev.stage_id) in already_classified_runs:
            continue
        msg_key = (ev.stage_id, (ev.message or "").strip()[:100])
        if msg_key in already_classified_messages:
            continue
        to_classify.append(ev)
        if len(to_classify) >= MAX_CALLS_PER_CYCLE:
            break

    if not to_classify:
        return {"classified": 0, "errors": 0, "skipped": "all failures already classified"}

    classified = 0
    errors = 0

    for ev in to_classify:
        try:
            result = _classify_failure(db, ev)
            if result:
                classified += 1
            else:
                errors += 1
        except Exception as e:
            logger.warning(f"Auto-classify failed for {ev.run_id}/{ev.stage_id}: {e}")
            errors += 1
        time.sleep(THROTTLE_SECONDS)

    if classified > 0:
        try:
            from api.contracts import record_source_fetch
            record_source_fetch("llm")
        except Exception:
            pass
    logger.info(f"Auto-LLM: classified {classified}, errors {errors}, from {len(to_classify)} candidates")
    return {"classified": classified, "errors": errors, "candidates": len(to_classify)}


def _classify_failure(db: Session, ev) -> Optional[Dict]:
    """Classify a single failure evaluation via LLM."""
    from db.models import ProposedClassification
    from db import repository
    from api.llm import call_llm, load_prompt, LLM_MODEL

    evidence_parts = [f"""## Failure Details
- Stage: {ev.stage_id}
- Message: {ev.message or 'unknown'}
- Cluster: {ev.cluster_name or 'unknown'}
- Lab/Namespace: {ev.lab_code or 'unknown'}
- Current classification: {ev.failure_class or 'unclassified'}"""]

    if ev.criteria_results:
        evidence_parts.append(f"## Criteria Results\n{json.dumps(ev.criteria_results, indent=2)}")

    similar = repository.get_similar_classifications(
        db, ev.message or "", limit=5
    )
    if similar:
        sim_lines = ["## Similar Past Classifications"]
        for s in similar:
            status = "APPROVED" if s["approved"] else "REJECTED" if s["approved"] is False else "pending"
            sim_lines.append(
                f"- \"{s['original_message']}\" → {s['proposed_class']} "
                f"(confidence {s['confidence']}, {status}, match {s['match_score']:.0%})"
            )
        evidence_parts.append("\n".join(sim_lines))

    if ev.lab_code:
        lab_freq = repository.get_failure_class_frequency(db, lab_code=ev.lab_code, limit=50)
        if lab_freq:
            freq_lines = [f"## Lab {ev.lab_code} Failure History"]
            for fc, ct in sorted(lab_freq.items(), key=lambda x: -x[1])[:8]:
                freq_lines.append(f"- {fc}: {ct} occurrences")
            evidence_parts.append("\n".join(freq_lines))

    # AAP provisioning context
    try:
        from collectors.aap.collect_aap import collect_aap_jobs
        aap = collect_aap_jobs()
        lab_aap = aap.get("by_lab", {})
        # Check if any lab matching this namespace has AAP failures
        for lab_code, info in lab_aap.items():
            if ev.lab_code and lab_code.lower() in ev.lab_code.lower():
                evidence_parts.append(f"## AAP Provisioning Data\n- {info['total']} AAP job failures for {lab_code}\n- Top error: {info.get('top_error', 'unknown')}")
                break
    except Exception:
        pass

    # Pool state context
    try:
        from api.routers._shared import _load_latest_babylon
        babylon = _load_latest_babylon()
        if babylon and ev.lab_code:
            pools = babylon.get("pools", {})
            for pname, pdata in pools.items():
                if isinstance(pdata, dict) and ev.lab_code.lower() in pname.lower():
                    evidence_parts.append(f"## Pool State\n- Pool: {pname}\n- Available: {pdata.get('available', '?')}\n- Ready: {pdata.get('ready', '?')}\n- Min required: {pdata.get('min_available', '?')}")
                    break
    except Exception:
        pass

    # Cluster CPU context
    try:
        from api.routers._shared import _load_latest_scan
        scans = _load_latest_scan()
        if scans and ev.cluster_name:
            for s in scans:
                if s.get("cluster") == ev.cluster_name:
                    evidence_parts.append(f"## Cluster Utilization\n- CPU: {s.get('avg_cpu_pct', '?')}%\n- VMs: {s.get('total_vms', '?')}\n- VMs/node: {s.get('vms_per_node', '?')}\n- Health: {s.get('health_rate', '?')}%")
                    break
    except Exception:
        pass

    evidence_parts.append("""## Known Failure Classes
- pods_not_ready, pods_crashlooping, deployment_missing, route_missing
- service_missing, service_has_no_endpoints, namespace_missing
- datavolume_missing, datavolume_not_ready, datavolume_failed
- vmi_not_running, vm_missing, guest_agent_not_connected
- showroom_not_reachable, showroom_not_ready, showroom_pod_down
- health_check_failed, cluster_unreachable, cluster_overloaded, provision_failed""")

    evidence = "\n\n".join(evidence_parts)

    _classify_prompt = load_prompt("classify")
    llm_result = call_llm(
        endpoint="classify",
        messages=[
            {"role": "system", "content": _classify_prompt.get("system", "You are a failure classification expert for OpenShift lab environments. Respond with valid JSON only.")},
            {"role": "user", "content": evidence},
        ],
        max_tokens=_classify_prompt.get("max_tokens", 500),
        temperature=_classify_prompt.get("temperature", 0.1),
        timeout=30,
        context={"lab_code": ev.lab_code, "cluster_name": ev.cluster_name, "failure_class": ev.failure_class},
        db=db,
        prompt_version=_classify_prompt.get("version"),
    )

    if not llm_result["success"]:
        logger.warning(f"LLM classify failed: {llm_result.get('error')}")
        return None

    proposed_class = ev.failure_class or "unknown"
    conditions = []
    confidence = 0.0
    try:
        parsed = json.loads(llm_result["content"])
        proposed_class = parsed.get("proposed_class", proposed_class)
        conditions = parsed.get("conditions", [])
        confidence = parsed.get("confidence", 0.0)
    except (json.JSONDecodeError, ValueError):
        pass

    proposal = ProposedClassification(
        run_id=ev.run_id,
        stage_id=ev.stage_id,
        original_message=ev.message,
        proposed_class=proposed_class,
        proposed_conditions=conditions,
        confidence=confidence,
        llm_model=LLM_MODEL,
        proposed_at=datetime.now(timezone.utc),
        llm_metric_id=llm_result.get("metric_id"),
    )
    db.add(proposal)
    db.commit()

    return {"proposed_class": proposed_class, "confidence": confidence}
