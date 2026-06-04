"""Database repository — CRUD operations for StarGate persistence."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from db.models import (
    AuditLog,
    EvaluationRecord,
    EvidenceRecord,
    LabRemediationConfig,
    RemediationRecord,
    RunRecord,
    StageRecord,
)
from engine.models import (
    Evidence,
    EvidenceResource,
    Run,
    RunStatus,
    Stage,
    StageOutcome,
    StageResult,
    StageStatus,
)


# --- Runs ---

def create_run(db: Session, run: Run) -> Run:
    record = RunRecord(
        run_id=run.run_id,
        demo_id=run.demo_id,
        namespace=run.namespace,
        requested_by=run.requested_by,
        status=run.status.value,
        rubric_version=run.rubric_version,
        git_sha=run.git_sha,
        started_at=run.started_at,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return run


def get_run(db: Session, run_id: str) -> Optional[Run]:
    record = db.query(RunRecord).filter(RunRecord.run_id == run_id).first()
    if not record:
        return None
    return Run(
        run_id=record.run_id,
        demo_id=record.demo_id,
        namespace=record.namespace,
        requested_by=record.requested_by,
        status=RunStatus(record.status),
        rubric_version=record.rubric_version,
        git_sha=record.git_sha,
        started_at=record.started_at,
        completed_at=record.completed_at,
    )


def list_runs(db: Session, limit: int = 100, offset: int = 0) -> List[Run]:
    records = db.query(RunRecord).order_by(RunRecord.id.desc()).offset(offset).limit(limit).all()
    return [
        Run(
            run_id=r.run_id,
            demo_id=r.demo_id,
            namespace=r.namespace,
            requested_by=r.requested_by,
            status=RunStatus(r.status),
            rubric_version=r.rubric_version,
            git_sha=r.git_sha,
            started_at=r.started_at,
            completed_at=r.completed_at,
        )
        for r in records
    ]


def update_run_status(
    db: Session,
    run_id: str,
    status: RunStatus,
    completed_at: Optional[datetime] = None,
) -> None:
    record = db.query(RunRecord).filter(RunRecord.run_id == run_id).first()
    if record:
        record.status = status.value
        if completed_at:
            record.completed_at = completed_at
        if status == RunStatus.RUNNING and not record.started_at:
            record.started_at = datetime.now(timezone.utc)
        db.commit()


# --- Stages ---

def create_stage(db: Session, stage: Stage) -> Stage:
    record = StageRecord(
        run_id=stage.run_id,
        stage_id=stage.stage_id,
        status=stage.status.value,
        started_at=stage.started_at,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return stage


def get_stage(db: Session, run_id: str, stage_id: str) -> Optional[Stage]:
    record = (
        db.query(StageRecord)
        .filter(StageRecord.run_id == run_id, StageRecord.stage_id == stage_id)
        .first()
    )
    if not record:
        return None
    result = None
    if record.result_outcome:
        result = StageResult(
            outcome=StageOutcome(record.result_outcome),
            failure_class=record.result_failure_class,
            message=record.result_message,
        )
    return Stage(
        run_id=record.run_id,
        stage_id=record.stage_id,
        status=StageStatus(record.status),
        started_at=record.started_at,
        completed_at=record.completed_at,
        duration_seconds=record.duration_seconds,
        result=result,
    )


def list_stages(db: Session, run_id: str) -> List[Stage]:
    records = db.query(StageRecord).filter(StageRecord.run_id == run_id).order_by(StageRecord.id).all()
    stages = []
    for r in records:
        result = None
        if r.result_outcome:
            result = StageResult(
                outcome=StageOutcome(r.result_outcome),
                failure_class=r.result_failure_class,
                message=r.result_message,
            )
        stages.append(Stage(
            run_id=r.run_id,
            stage_id=r.stage_id,
            status=StageStatus(r.status),
            started_at=r.started_at,
            completed_at=r.completed_at,
            duration_seconds=r.duration_seconds,
            result=result,
        ))
    return stages


def update_stage(
    db: Session,
    run_id: str,
    stage_id: str,
    status: Optional[StageStatus] = None,
    result: Optional[StageResult] = None,
    completed_at: Optional[datetime] = None,
    duration_seconds: Optional[float] = None,
) -> Optional[Stage]:
    record = (
        db.query(StageRecord)
        .filter(StageRecord.run_id == run_id, StageRecord.stage_id == stage_id)
        .first()
    )
    if not record:
        return None
    if status:
        record.status = status.value
    if result:
        record.result_outcome = result.outcome.value
        record.result_failure_class = result.failure_class
        record.result_message = result.message
    if completed_at:
        record.completed_at = completed_at
    if duration_seconds is not None:
        record.duration_seconds = duration_seconds
    db.commit()
    return get_stage(db, run_id, stage_id)


# --- Evidence ---

def create_evidence(db: Session, evidence: Evidence) -> Evidence:
    resource_dict = None
    if evidence.resource:
        resource_dict = evidence.resource.dict() if hasattr(evidence.resource, 'dict') else evidence.resource.model_dump()
    record = EvidenceRecord(
        evidence_id=evidence.evidence_id,
        run_id=evidence.run_id,
        stage_id=evidence.stage_id,
        type=evidence.type,
        source=evidence.source,
        resource=resource_dict,
        observed=evidence.observed,
        result=evidence.result.value if hasattr(evidence.result, 'value') else evidence.result,
        timestamp=evidence.timestamp,
        raw_ref=evidence.raw_ref,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return evidence


def list_evidence_for_stage(db: Session, run_id: str, stage_id: str) -> List[Evidence]:
    records = (
        db.query(EvidenceRecord)
        .filter(EvidenceRecord.run_id == run_id, EvidenceRecord.stage_id == stage_id)
        .order_by(EvidenceRecord.id)
        .all()
    )
    return [
        Evidence(
            evidence_id=r.evidence_id,
            run_id=r.run_id,
            stage_id=r.stage_id,
            type=r.type,
            source=r.source,
            resource=EvidenceResource(**r.resource) if r.resource else None,
            observed=r.observed,
            result=StageOutcome(r.result),
            timestamp=r.timestamp,
            raw_ref=r.raw_ref,
        )
        for r in records
    ]


# --- Evaluations ---

def create_evaluation(
    db: Session,
    run_id: str,
    stage_id: str,
    outcome: str,
    failure_class: Optional[str],
    message: Optional[str],
    criteria_results: Optional[list],
    lab_code: Optional[str] = None,
    cluster_name: Optional[str] = None,
) -> EvaluationRecord:
    record = EvaluationRecord(
        run_id=run_id,
        stage_id=stage_id,
        outcome=outcome,
        failure_class=failure_class,
        message=message,
        criteria_results=criteria_results,
        evaluated_at=datetime.now(timezone.utc),
        lab_code=lab_code,
        cluster_name=cluster_name,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_evaluations(
    db: Session,
    lab_code: Optional[str] = None,
    stage_id: Optional[str] = None,
    cluster_name: Optional[str] = None,
    limit: int = 50,
) -> List[EvaluationRecord]:
    query = db.query(EvaluationRecord)
    if lab_code:
        query = query.filter(EvaluationRecord.lab_code == lab_code)
    if stage_id:
        query = query.filter(EvaluationRecord.stage_id == stage_id)
    if cluster_name:
        query = query.filter(EvaluationRecord.cluster_name == cluster_name)
    return query.order_by(EvaluationRecord.id.desc()).limit(limit).all()


# --- Bundle queries ---

def get_evaluation_history(
    db: Session,
    lab_code: str,
    stage_id: Optional[str] = None,
    cluster_name: Optional[str] = None,
    limit: int = 20,
) -> List[dict]:
    """Get historical evaluations for a lab, optionally filtered by stage and cluster."""
    query = db.query(EvaluationRecord).filter(EvaluationRecord.lab_code == lab_code)
    if stage_id:
        query = query.filter(EvaluationRecord.stage_id == stage_id)
    if cluster_name:
        query = query.filter(EvaluationRecord.cluster_name == cluster_name)
    records = query.order_by(EvaluationRecord.id.desc()).limit(limit).all()
    return [
        {
            "run_id": r.run_id,
            "stage_id": r.stage_id,
            "outcome": r.outcome,
            "failure_class": r.failure_class,
            "message": r.message,
            "evaluated_at": r.evaluated_at.isoformat() if r.evaluated_at else None,
            "cluster_name": r.cluster_name,
        }
        for r in records
    ]


def get_failure_class_frequency(
    db: Session,
    lab_code: Optional[str] = None,
    cluster_name: Optional[str] = None,
    limit: int = 100,
) -> dict:
    """Count failure class occurrences, optionally scoped to lab or cluster."""
    query = db.query(EvaluationRecord).filter(EvaluationRecord.outcome == "fail")
    if lab_code:
        query = query.filter(EvaluationRecord.lab_code == lab_code)
    if cluster_name:
        query = query.filter(EvaluationRecord.cluster_name == cluster_name)
    records = query.order_by(EvaluationRecord.id.desc()).limit(limit).all()

    counts: dict = {}
    for r in records:
        fc = r.failure_class or "unclassified"
        counts[fc] = counts.get(fc, 0) + 1
    return counts


def get_last_passing_run(
    db: Session,
    lab_code: str,
    stage_id: Optional[str] = None,
) -> Optional[dict]:
    """Find the most recent passing evaluation for a lab."""
    query = (
        db.query(EvaluationRecord)
        .filter(EvaluationRecord.lab_code == lab_code, EvaluationRecord.outcome == "pass")
    )
    if stage_id:
        query = query.filter(EvaluationRecord.stage_id == stage_id)
    record = query.order_by(EvaluationRecord.id.desc()).first()
    if not record:
        return None
    return {
        "run_id": record.run_id,
        "stage_id": record.stage_id,
        "evaluated_at": record.evaluated_at.isoformat() if record.evaluated_at else None,
        "cluster_name": record.cluster_name,
    }


def get_cluster_failure_summary(
    db: Session,
    cluster_name: str,
    limit: int = 200,
) -> dict:
    """Aggregate failure data for a cluster."""
    records = (
        db.query(EvaluationRecord)
        .filter(EvaluationRecord.cluster_name == cluster_name)
        .order_by(EvaluationRecord.id.desc())
        .limit(limit)
        .all()
    )

    warning_classes = {"guest_agent_not_connected", "health_check_failed"}

    passed = 0
    real_failed = 0
    warned = 0
    failure_classes: dict = {}
    labs_seen = set()
    labs_failing = set()

    for r in records:
        if r.lab_code:
            labs_seen.add(r.lab_code)
        if r.outcome == "pass":
            passed += 1
        elif r.outcome == "fail":
            fc = r.failure_class or "unclassified"
            if fc in warning_classes:
                warned += 1
            else:
                real_failed += 1
                failure_classes[fc] = failure_classes.get(fc, 0) + 1
                if r.lab_code:
                    labs_failing.add(r.lab_code)
        elif r.outcome == "warn":
            warned += 1

    total = len(records)
    healthy = passed + warned

    return {
        "cluster": cluster_name,
        "total_evaluations": total,
        "passed": passed,
        "failed": real_failed,
        "warned": warned,
        "health_rate": round(healthy / total * 100, 1) if total > 0 else 0,
        "failure_classes": failure_classes,
        "labs_seen": len(labs_seen),
        "labs_failing": len(labs_failing),
    }


def get_namespaces_for_cluster(db: Session, cluster_name: str, limit: int = 200) -> List[dict]:
    """Aggregate per-namespace stats for a cluster."""
    from sqlalchemy import func, case

    rows = (
        db.query(
            EvaluationRecord.lab_code,
            func.count(EvaluationRecord.id).label("total"),
            func.sum(case((EvaluationRecord.outcome == "pass", 1), else_=0)).label("passed"),
            func.sum(case((EvaluationRecord.outcome == "fail", 1), else_=0)).label("failed"),
            func.max(EvaluationRecord.evaluated_at).label("last_evaluated"),
        )
        .filter(
            EvaluationRecord.cluster_name == cluster_name,
            EvaluationRecord.lab_code.isnot(None),
        )
        .group_by(EvaluationRecord.lab_code)
        .order_by(func.sum(case((EvaluationRecord.outcome == "fail", 1), else_=0)).desc())
        .limit(limit)
        .all()
    )

    results = []
    for lab_code, total, passed, failed, last_evaluated in rows:
        health = round((total - failed) / total * 100, 1) if total > 0 else 0
        fc_rows = (
            db.query(EvaluationRecord.failure_class, func.count(EvaluationRecord.id))
            .filter(
                EvaluationRecord.cluster_name == cluster_name,
                EvaluationRecord.lab_code == lab_code,
                EvaluationRecord.outcome == "fail",
                EvaluationRecord.failure_class.isnot(None),
            )
            .group_by(EvaluationRecord.failure_class)
            .all()
        )
        failure_classes = {fc: ct for fc, ct in fc_rows}
        top_failure = max(failure_classes, key=failure_classes.get) if failure_classes else None
        results.append({
            "namespace": lab_code,
            "total": total,
            "passed": passed,
            "failed": failed,
            "health_rate": health,
            "failure_classes": failure_classes,
            "top_failure": top_failure,
            "last_evaluated": last_evaluated.isoformat() if last_evaluated else None,
        })

    return results


# --- Materialized view refresh functions ---

def refresh_cluster_summary(db: Session) -> None:
    from db.models import EvaluationRecord, MVClusterSummary
    from sqlalchemy import func
    from datetime import datetime, timezone

    db.query(MVClusterSummary).delete()

    rows = (
        db.query(
            EvaluationRecord.cluster_name,
            EvaluationRecord.outcome,
            EvaluationRecord.failure_class,
            EvaluationRecord.lab_code,
        )
        .filter(EvaluationRecord.cluster_name.isnot(None))
        .all()
    )

    clusters: dict = {}
    for cluster_name, outcome, failure_class, lab_code in rows:
        if cluster_name not in clusters:
            clusters[cluster_name] = {"p": 0, "f": 0, "w": 0, "fc": {}, "labs": set(), "labs_f": set()}
        c = clusters[cluster_name]
        o = outcome.lower() if outcome else ""
        if o == "pass":
            c["p"] += 1
        elif o == "fail":
            c["f"] += 1
            if failure_class:
                c["fc"][failure_class] = c["fc"].get(failure_class, 0) + 1
            if lab_code:
                c["labs_f"].add(lab_code)
        elif o == "warn":
            c["w"] += 1
        if lab_code:
            c["labs"].add(lab_code)

    now = datetime.now(timezone.utc)
    for name, c in clusters.items():
        total = c["p"] + c["f"] + c["w"]
        healthy = c["p"] + c["w"]
        db.add(MVClusterSummary(
            cluster_name=name,
            total_evaluations=total,
            passed=c["p"],
            failed=c["f"],
            warned=c["w"],
            health_rate=round(healthy / total * 100, 1) if total > 0 else 0,
            failure_classes=c["fc"],
            labs_seen=len(c["labs"]),
            labs_failing=len(c["labs_f"]),
            updated_at=now,
        ))
    db.commit()


def refresh_pipeline_stages(db: Session) -> None:
    from db.models import EvaluationRecord, MVPipelineStage
    from datetime import datetime, timezone

    db.query(MVPipelineStage).delete()

    rows = (
        db.query(EvaluationRecord.stage_id, EvaluationRecord.outcome)
        .all()
    )

    stages: dict = {}
    for stage_id, outcome in rows:
        if stage_id not in stages:
            stages[stage_id] = {"p": 0, "f": 0, "w": 0}
        o = outcome.lower() if outcome else ""
        if o == "pass":
            stages[stage_id]["p"] += 1
        elif o == "fail":
            stages[stage_id]["f"] += 1
        elif o == "warn":
            stages[stage_id]["w"] += 1

    now = datetime.now(timezone.utc)
    for sid, s in stages.items():
        total = s["p"] + s["f"] + s["w"]
        healthy = s["p"] + s["w"]
        db.add(MVPipelineStage(
            stage_id=sid,
            pass_count=s["p"],
            fail_count=s["f"],
            warn_count=s["w"],
            total=total,
            health_rate=round(healthy / total * 100, 1) if total > 0 else 0,
            updated_at=now,
        ))
    db.commit()


def refresh_lab_eval_summary(db: Session) -> None:
    from db.models import EvaluationRecord, MVLabEvalSummary
    from sqlalchemy import func
    from datetime import datetime, timezone

    db.query(MVLabEvalSummary).delete()

    rows = (
        db.query(
            EvaluationRecord.lab_code,
            EvaluationRecord.cluster_name,
            EvaluationRecord.outcome,
            EvaluationRecord.failure_class,
            EvaluationRecord.evaluated_at,
        )
        .filter(EvaluationRecord.lab_code.isnot(None))
        .all()
    )

    labs: dict = {}
    for lab_code, cluster_name, outcome, failure_class, evaluated_at in rows:
        key = (lab_code, cluster_name or "")
        if key not in labs:
            labs[key] = {"p": 0, "f": 0, "w": 0, "fc": {}, "last": None}
        l = labs[key]
        o = outcome.lower() if outcome else ""
        if o == "pass":
            l["p"] += 1
        elif o == "fail":
            l["f"] += 1
            if failure_class:
                l["fc"][failure_class] = l["fc"].get(failure_class, 0) + 1
        elif o == "warn":
            l["w"] += 1
        if evaluated_at and (l["last"] is None or evaluated_at > l["last"]):
            l["last"] = evaluated_at

    now = datetime.now(timezone.utc)
    for (lab_code, cluster_name), l in labs.items():
        total = l["p"] + l["f"] + l["w"]
        healthy = l["p"] + l["w"]
        top_fc = max(l["fc"], key=l["fc"].get) if l["fc"] else None
        db.add(MVLabEvalSummary(
            lab_code=lab_code,
            cluster_name=cluster_name or None,
            total_evals=total,
            passed=l["p"],
            failed=l["f"],
            warned=l["w"],
            top_failure_class=top_fc,
            health_rate=round(healthy / total * 100, 1) if total > 0 else 0,
            last_evaluated_at=l["last"],
            updated_at=now,
        ))
    db.commit()


def get_all_cluster_summaries(db: Session) -> dict:
    from db.models import MVClusterSummary
    results = db.query(MVClusterSummary).all()
    return {
        r.cluster_name: {
            "total_evaluations": r.total_evaluations,
            "passed": r.passed,
            "failed": r.failed,
            "warned": r.warned,
            "health_rate": r.health_rate,
            "failure_classes": r.failure_classes or {},
            "labs_seen": r.labs_seen,
            "labs_failing": r.labs_failing,
        }
        for r in results
    }


def save_scan_snapshot(db: Session, scan_type: str, data: dict) -> None:
    """Persist a scan snapshot to the database."""
    from db.models import ScanSnapshot
    from datetime import datetime, timezone
    snapshot = ScanSnapshot(
        scan_type=scan_type,
        data=data,
        scanned_at=datetime.now(timezone.utc),
    )
    db.add(snapshot)
    db.commit()


def get_latest_scan_snapshot(db: Session, scan_type: str) -> Optional[dict]:
    """Get the most recent scan snapshot of a given type."""
    from db.models import ScanSnapshot
    record = (
        db.query(ScanSnapshot)
        .filter(ScanSnapshot.scan_type == scan_type)
        .order_by(ScanSnapshot.scanned_at.desc())
        .first()
    )
    if not record:
        return None
    return record.data


def get_scan_timeline(db: Session, scan_type: str, limit: int = 50) -> list:
    """Get recent scan snapshots for timeline display."""
    from db.models import ScanSnapshot
    records = (
        db.query(ScanSnapshot)
        .filter(ScanSnapshot.scan_type == scan_type)
        .order_by(ScanSnapshot.scanned_at.desc())
        .limit(limit)
        .all()
    )
    return [{"data": r.data, "scanned_at": r.scanned_at.isoformat()} for r in reversed(records)]


def save_receipt(db: Session, receipt_type: str, phase: str, data: dict, passed: bool) -> None:
    from db.models import Receipt
    from datetime import datetime, timezone
    receipt = Receipt(
        receipt_type=receipt_type,
        phase=phase,
        data=data,
        passed=passed,
        generated_at=datetime.now(timezone.utc),
    )
    db.add(receipt)
    db.commit()


def get_receipts(db: Session, receipt_type: str = None, phase: str = None, limit: int = 50) -> list:
    from db.models import Receipt
    query = db.query(Receipt)
    if receipt_type:
        query = query.filter(Receipt.receipt_type == receipt_type)
    if phase:
        query = query.filter(Receipt.phase == phase)
    records = query.order_by(Receipt.id.desc()).limit(limit).all()
    return [
        {
            "id": r.id,
            "receipt_type": r.receipt_type,
            "phase": r.phase,
            "data": r.data,
            "passed": r.passed,
            "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        }
        for r in records
    ]


def get_latest_receipt(db: Session, receipt_type: str) -> dict:
    from db.models import Receipt
    record = db.query(Receipt).filter(Receipt.receipt_type == receipt_type).order_by(Receipt.id.desc()).first()
    if not record:
        return None
    return {
        "id": record.id,
        "receipt_type": record.receipt_type,
        "phase": record.phase,
        "data": record.data,
        "passed": record.passed,
        "generated_at": record.generated_at.isoformat() if record.generated_at else None,
    }


def get_recent_remediations(
    db: Session,
    lab_code: Optional[str] = None,
    cluster_name: Optional[str] = None,
    failure_class: Optional[str] = None,
    limit: int = 10,
) -> List[dict]:
    """Get recent remediation attempts and their outcomes."""
    from db.models import RemediationRecord
    query = db.query(RemediationRecord)
    if lab_code:
        query = query.filter(RemediationRecord.run_id.like(f"%{lab_code}%"))
    if failure_class:
        query = query.filter(RemediationRecord.failure_class == failure_class)
    records = query.order_by(RemediationRecord.id.desc()).limit(limit).all()
    return [
        {
            "remediation_id": r.remediation_id,
            "failure_class": r.failure_class,
            "action_taken": r.action_taken,
            "resolved": r.resolved,
            "applied_at": r.applied_at.isoformat() if r.applied_at else None,
            "notes": r.notes,
        }
        for r in records
    ]


def get_blast_radius(
    db: Session,
    lab_code: Optional[str] = None,
    cluster_name: Optional[str] = None,
    failure_class: Optional[str] = None,
    limit: int = 20,
) -> dict:
    """Get blast radius from event log — how widespread is a failure?"""
    from db.models import EventLog
    query = db.query(EventLog).filter(EventLog.filtered == False)
    if lab_code:
        query = query.filter(EventLog.lab_code == lab_code)
    if cluster_name:
        query = query.filter(EventLog.cluster_name == cluster_name)
    if failure_class:
        query = query.filter(EventLog.failure_class == failure_class)
    events = query.order_by(EventLog.id.desc()).limit(limit).all()

    if not events:
        return {"total_events": 0, "labs_affected": [], "clusters_affected": [], "systemic": False, "escalated": 0}

    labs = set()
    clusters = set()
    systemic = False
    escalated = 0
    for e in events:
        if e.lab_code:
            labs.add(e.lab_code)
        if e.cluster_name:
            clusters.add(e.cluster_name)
        if e.systemic:
            systemic = True
        if e.priority and e.priority >= 4.0:
            escalated += 1

    return {
        "total_events": len(events),
        "labs_affected": sorted(labs),
        "clusters_affected": sorted(clusters),
        "systemic": systemic,
        "escalated": escalated,
    }


def get_similar_classifications(
    db: Session,
    message: str,
    limit: int = 5,
) -> List[dict]:
    """Find similar past classifications by matching keywords in the original message."""
    from db.models import ProposedClassification
    keywords = [w.lower() for w in message.split() if len(w) > 4][:5]
    if not keywords:
        return []

    results = []
    proposals = db.query(ProposedClassification).filter(
        ProposedClassification.reviewed == True
    ).order_by(ProposedClassification.id.desc()).limit(200).all()

    for p in proposals:
        if not p.original_message:
            continue
        msg_lower = p.original_message.lower()
        matches = sum(1 for kw in keywords if kw in msg_lower)
        if matches >= 2:
            results.append({
                "proposed_class": p.proposed_class,
                "confidence": p.confidence,
                "approved": p.approved,
                "original_message": p.original_message[:100],
                "match_score": matches / len(keywords),
            })
    results.sort(key=lambda x: -x["match_score"])
    return results[:limit]


def get_proposed_classifications(
    db: Session,
    lab_code: Optional[str] = None,
    stage_id: Optional[str] = None,
    pending_only: bool = False,
    limit: int = 100,
) -> List[dict]:
    """Get proposed classifications, optionally filtered by lab/stage."""
    from db.models import ProposedClassification, EvaluationRecord

    query = db.query(ProposedClassification)
    if pending_only:
        query = query.filter(ProposedClassification.reviewed == False)
    if stage_id:
        query = query.filter(ProposedClassification.stage_id == stage_id)

    if lab_code:
        eval_run_ids = [
            r[0] for r in db.query(EvaluationRecord.run_id)
            .filter(EvaluationRecord.lab_code == lab_code)
            .distinct().all()
        ]
        if eval_run_ids:
            query = query.filter(ProposedClassification.run_id.in_(eval_run_ids))
        else:
            return []

    proposals = query.order_by(ProposedClassification.id.desc()).limit(limit).all()
    return [
        {
            "id": p.id,
            "run_id": p.run_id,
            "stage_id": p.stage_id,
            "proposed_class": p.proposed_class,
            "confidence": p.confidence,
            "conditions": p.proposed_conditions,
            "original_message": p.original_message,
            "reviewed": p.reviewed,
            "approved": p.approved,
            "proposed_at": p.proposed_at.isoformat() if p.proposed_at else None,
            "reviewed_by": p.reviewed_by,
        }
        for p in proposals
    ]


# --- Pool Snapshots ---

def save_pool_snapshot(db: Session, pool_name: str, available: int, ready: int, min_required: int, total_handles: int):
    """Save a pool handle snapshot for velocity tracking."""
    from db.models import PoolSnapshot
    snap = PoolSnapshot(
        pool_name=pool_name,
        available=available,
        ready=ready,
        min_required=min_required,
        total_handles=total_handles,
        captured_at=datetime.now(timezone.utc),
    )
    db.add(snap)
    db.commit()


def get_pool_timeline(db: Session, pool_name: str, hours: int = 6) -> list:
    """Get pool snapshots for the last N hours."""
    from db.models import PoolSnapshot
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    snaps = (
        db.query(PoolSnapshot)
        .filter(PoolSnapshot.pool_name == pool_name, PoolSnapshot.captured_at >= cutoff)
        .order_by(PoolSnapshot.captured_at)
        .all()
    )
    return [
        {"available": s.available, "ready": s.ready, "min_required": s.min_required,
         "total_handles": s.total_handles, "captured_at": s.captured_at.isoformat()}
        for s in snaps
    ]


def cleanup_old_pool_snapshots(db: Session, days: int = 7):
    """Remove pool snapshots older than N days."""
    from db.models import PoolSnapshot
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    db.query(PoolSnapshot).filter(PoolSnapshot.captured_at < cutoff).delete()
    db.commit()


# --- Lab Remediation Config ---

def get_lab_remediation_config(db: Session, lab_code: str) -> Optional[LabRemediationConfig]:
    return db.query(LabRemediationConfig).filter(LabRemediationConfig.lab_code == lab_code).first()


def get_all_lab_remediation_configs(db: Session) -> List[LabRemediationConfig]:
    return db.query(LabRemediationConfig).order_by(LabRemediationConfig.lab_code).all()


def upsert_lab_remediation_config(
    db: Session,
    lab_code: str,
    execution_mode: str,
    max_actions_per_hour: int = 5,
    enabled_by: Optional[str] = None,
    notes: Optional[str] = None,
) -> LabRemediationConfig:
    record = db.query(LabRemediationConfig).filter(LabRemediationConfig.lab_code == lab_code).first()
    now = datetime.now(timezone.utc)
    if record:
        record.execution_mode = execution_mode
        record.max_actions_per_hour = max_actions_per_hour
        record.enabled_by = enabled_by
        record.enabled_at = now
        record.notes = notes
    else:
        record = LabRemediationConfig(
            lab_code=lab_code,
            execution_mode=execution_mode,
            max_actions_per_hour=max_actions_per_hour,
            enabled_by=enabled_by,
            enabled_at=now,
            notes=notes,
        )
        db.add(record)
    db.commit()
    db.refresh(record)
    return record


def delete_lab_remediation_config(db: Session, lab_code: str) -> bool:
    count = db.query(LabRemediationConfig).filter(LabRemediationConfig.lab_code == lab_code).delete()
    db.commit()
    return count > 0


def get_remediation_activity(db: Session, limit: int = 50) -> List[dict]:
    records = (
        db.query(AuditLog)
        .filter(AuditLog.action_type != "proposed")
        .order_by(AuditLog.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "action_type": r.action_type,
            "target": r.target,
            "status": r.status,
            "proposed_by": r.proposed_by,
            "approved_by": r.approved_by,
            "executed_at": r.executed_at.isoformat() if r.executed_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "result": r.result,
        }
        for r in records
    ]


def count_recent_actions(db: Session, lab_code: str, hours: int = 1) -> int:
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return (
        db.query(AuditLog)
        .filter(
            AuditLog.status == "executed",
            AuditLog.executed_at >= cutoff,
            AuditLog.target.contains(lab_code),
        )
        .count()
    )


# ---------------------------------------------------------------------------
# Historical Data — AAP, Provisioning, Sandbox metrics
# ---------------------------------------------------------------------------

def save_aap_metrics(db: Session, data: Dict) -> None:
    from db.models import AAPJobMetric
    summary = data.get("summary", {})
    top_errors = data.get("top_errors", [])
    metric = AAPJobMetric(
        captured_at=datetime.now(timezone.utc),
        total_jobs=summary.get("total_jobs", 0),
        successful=summary.get("successful", 0),
        failed=summary.get("failed", 0),
        running=summary.get("running", 0),
        success_rate=summary.get("success_rate"),
        provision_sli=summary.get("provision_sli"),
        sli_met=summary.get("sli_met"),
        top_error=top_errors[0]["error"][:500] if top_errors else None,
        by_cluster=data.get("by_cluster"),
        by_lab=data.get("by_lab"),
    )
    db.add(metric)
    db.commit()


def get_aap_timeline(db: Session, hours: int = 24) -> List[Dict]:
    from db.models import AAPJobMetric
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = db.query(AAPJobMetric).filter(AAPJobMetric.captured_at >= cutoff).order_by(AAPJobMetric.captured_at).all()
    return [
        {
            "captured_at": r.captured_at.isoformat(),
            "total_jobs": r.total_jobs,
            "successful": r.successful,
            "failed": r.failed,
            "success_rate": r.success_rate,
            "provision_sli": r.provision_sli,
            "sli_met": r.sli_met,
            "top_error": r.top_error,
        }
        for r in rows
    ]


def save_provisioning_snapshot(db: Session, data: Dict) -> None:
    from db.models import ProvisioningSnapshot
    summit = data.get("summit_2026", {})
    snap = ProvisioningSnapshot(
        captured_at=datetime.now(timezone.utc),
        total=data.get("total", 0),
        started=data.get("started", 0),
        failed=data.get("failed", 0),
        failure_rate=data.get("failure_rate"),
        by_state=data.get("by_state"),
        summit_total=summit.get("total"),
        summit_started=summit.get("started"),
        summit_failed=summit.get("failed"),
    )
    db.add(snap)
    db.commit()


def get_provisioning_timeline(db: Session, hours: int = 24) -> List[Dict]:
    from db.models import ProvisioningSnapshot
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = db.query(ProvisioningSnapshot).filter(ProvisioningSnapshot.captured_at >= cutoff).order_by(ProvisioningSnapshot.captured_at).all()
    return [
        {
            "captured_at": r.captured_at.isoformat(),
            "total": r.total,
            "started": r.started,
            "failed": r.failed,
            "failure_rate": r.failure_rate,
            "by_state": r.by_state,
        }
        for r in rows
    ]


def save_sandbox_metrics(db: Session, data: Dict) -> None:
    from db.models import SandboxAPIMetric
    metric = SandboxAPIMetric(
        captured_at=datetime.now(timezone.utc),
        api_healthy=data.get("api_healthy"),
        replicas_desired=data.get("replicas_desired"),
        replicas_ready=data.get("replicas_ready"),
        queue_depth=data.get("queue_depth"),
        total_sandboxes=data.get("total_sandboxes"),
        active=data.get("active"),
        failing=data.get("failing"),
        crashloop=data.get("crashloop"),
        by_cluster=data.get("by_cluster"),
    )
    db.add(metric)
    db.commit()


def get_sandbox_timeline(db: Session, hours: int = 24) -> List[Dict]:
    from db.models import SandboxAPIMetric
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = db.query(SandboxAPIMetric).filter(SandboxAPIMetric.captured_at >= cutoff).order_by(SandboxAPIMetric.captured_at).all()
    return [
        {
            "captured_at": r.captured_at.isoformat(),
            "api_healthy": r.api_healthy,
            "queue_depth": r.queue_depth,
            "total_sandboxes": r.total_sandboxes,
            "active": r.active,
            "failing": r.failing,
            "crashloop": r.crashloop,
        }
        for r in rows
    ]


def compute_mttr(db: Session, hours: int = 168) -> Dict:
    """Compute mean time to recovery from evaluation pass/fail transitions."""
    from db.models import EvaluationRecord
    from datetime import timedelta
    from sqlalchemy import func

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    evals = (
        db.query(EvaluationRecord)
        .filter(EvaluationRecord.evaluated_at >= cutoff, EvaluationRecord.failure_class.isnot(None))
        .order_by(EvaluationRecord.lab_code, EvaluationRecord.failure_class, EvaluationRecord.evaluated_at)
        .all()
    )

    durations_by_class: Dict[str, List[float]] = {}
    prev: Dict[str, Any] = {}

    for ev in evals:
        key = f"{ev.lab_code}:{ev.failure_class}"
        if ev.outcome == "fail":
            if key not in prev:
                prev[key] = ev.evaluated_at
        elif ev.outcome == "pass" and key in prev:
            start = prev.pop(key)
            if ev.evaluated_at and start:
                duration = (ev.evaluated_at - start).total_seconds() / 60.0
                if duration > 0:
                    fc = ev.failure_class or "unknown"
                    durations_by_class.setdefault(fc, []).append(duration)

    all_durations = [d for ds in durations_by_class.values() for d in ds]
    overall_mttr = sum(all_durations) / len(all_durations) if all_durations else None

    by_class = []
    for fc, ds in sorted(durations_by_class.items(), key=lambda x: -len(x[1])):
        ds_sorted = sorted(ds)
        by_class.append({
            "failure_class": fc,
            "count": len(ds),
            "avg_minutes": round(sum(ds) / len(ds), 1),
            "p50": round(ds_sorted[len(ds_sorted) // 2], 1),
            "p95": round(ds_sorted[int(len(ds_sorted) * 0.95)], 1) if len(ds_sorted) > 1 else round(ds_sorted[0], 1),
        })

    return {
        "overall_mttr_minutes": round(overall_mttr, 1) if overall_mttr else None,
        "total_recoveries": len(all_durations),
        "by_class": by_class[:20],
    }
