"""Maintenance tasks — MV refresh, cache warming, corpus mining."""

import logging

from celery import shared_task

logger = logging.getLogger("stargate.tasks.maintenance")


@shared_task(bind=True, max_retries=1)
def mv_refresh(self):
    """Refresh materialized views and run calibration."""
    from db.database import get_db
    gen = get_db()
    db = next(gen)
    try:
        from db import repository
        repository.refresh_cluster_summary(db)
        repository.refresh_pipeline_stages(db)
        repository.refresh_lab_eval_summary(db)
        repository.refresh_evaluation_trends(db)
        repository.refresh_mttr_by_class(db)
        repository.refresh_overview_snapshot(db)
        try:
            from engine.learner import apply_feedback
            apply_feedback(db)
        except Exception as e:
            logger.warning("apply_feedback failed: %s", e)
        try:
            from engine.auto_llm import run_auto_analysis
            run_auto_analysis(db)
        except Exception as e:
            logger.warning("run_auto_analysis failed: %s", e)
        try:
            from engine.lab_mapper import refresh_lab_mappings
            refresh_lab_mappings(db)
        except Exception as e:
            logger.warning("refresh_lab_mappings failed: %s", e)
        logger.info("MV refresh complete")
        return {"status": "ok"}
    except Exception as e:
        logger.warning("MV refresh failed: %s", e)
        raise self.retry(exc=e)
    finally:
        gen.close()


@shared_task
def warm_caches():
    """Pre-fetch external API caches and persist sandbox metrics."""
    try:
        from api.routers._shared import _fetch_labagator_labs, _fetch_labagator_sessions, _fetch_demolition_sessions
        _fetch_labagator_labs()
        _fetch_labagator_sessions()
        _fetch_demolition_sessions()
        logger.info("Cache warm complete")
    except Exception as e:
        logger.warning("Cache warm failed: %s", e)
        return {"error": str(e)}
    try:
        from collectors.sandbox_api.collect_sandbox_api import collect_sandbox_api_health as collect_sandbox_health
        from db.database import get_db
        from db import repository
        data = collect_sandbox_health()
        if data and not data.get("error"):
            gen = get_db()
            db = next(gen)
            try:
                repository.save_sandbox_metrics(db, data)
            finally:
                gen.close()
    except Exception as e:
        logger.warning("Sandbox metrics persist failed: %s", e)
    return {"status": "ok"}


@shared_task(bind=True, max_retries=1, soft_time_limit=120)
def babylon_collect(self):
    """Collect Babylon control plane data — pools, provisioning, lab mappings."""
    try:
        from cli.babylon_worker import run_collection
        results = run_collection()
        prov = results.get("provisioning", {})
        pools = results.get("pools", {})
        logger.info(
            "Babylon collect: %d subjects, %d pools, %d lab mappings",
            prov.get("total", 0), pools.get("total_pools", 0),
            len(results.get("summit_mapping", results.get("lab_mapping", {})))
        )
        return {"status": "ok", "subjects": prov.get("total", 0), "pools": pools.get("total_pools", 0)}
    except Exception as e:
        logger.warning("Babylon collect failed: %s", e)
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=1, soft_time_limit=300)
def corpus_mine(self):
    """Run all corpus miners and load results into DB."""
    from db.database import get_db
    gen = get_db()
    db = next(gen)
    try:
        from engine.corpus_runner import run_all_miners
        result = run_all_miners(db=db)
        logger.info("Corpus mining: %d findings", result.get("total_findings", 0))
        return result
    except Exception as e:
        logger.warning("Corpus mining failed: %s", e)
        return {"error": str(e)}
    finally:
        gen.close()


@shared_task(bind=True, max_retries=1, soft_time_limit=30)
def process_investigation_queue(self):
    """Dispatch queued investigations as individual Celery tasks."""
    from db.database import get_db
    from db import repository

    gen = get_db()
    db = next(gen)
    try:
        queued = repository.get_queued_investigations(db, limit=10)
        if not queued:
            return {"dispatched": 0}

        dispatched = 0
        for record in queued:
            record.status = "dispatched"
            db.commit()
            run_single_investigation.delay(record.job_id)
            dispatched += 1
        return {"dispatched": dispatched}
    except Exception as e:
        logger.warning("Investigation dispatch failed: %s", e)
        raise self.retry(exc=e)
    finally:
        gen.close()


@shared_task(bind=True, max_retries=1, soft_time_limit=300)
def run_single_investigation(self, job_id: str):
    """Execute a single investigation — runs in its own Celery worker slot."""
    from db.database import get_db
    from db import repository

    gen = get_db()
    db = next(gen)
    try:
        from db.models import InvestigationRecord
        record = db.query(InvestigationRecord).filter(
            InvestigationRecord.job_id == job_id
        ).first()
        if not record or record.status not in ("dispatched", "queued"):
            return {"skipped": True, "job_id": job_id}

        _run_single_investigation(record, db)
        return {"job_id": job_id}
    except Exception as e:
        logger.warning("Investigation %s failed: %s", job_id, e)
        try:
            repository.fail_investigation(db, job_id, str(e))
        except Exception:
            pass
        raise self.retry(exc=e)
    finally:
        gen.close()


def _run_single_investigation(record, db):
    """Execute a single investigation and update the DB record."""
    import os
    from db import repository
    from engine.investigation_agent import run_investigation

    repository.start_investigation(db, record.job_id)

    evidence_lines = [
        f"Failure class: {record.failure_class}",
        f"Namespace: {record.lab_code}",
        f"Cluster: {record.cluster}",
        f"Trigger: {record.trigger_type}",
    ]
    from db.models import EvaluationRecord
    recent = (
        db.query(EvaluationRecord)
        .filter(EvaluationRecord.lab_code == record.lab_code)
        .order_by(EvaluationRecord.id.desc())
        .limit(5)
        .all()
    )
    if recent:
        evidence_lines.append("\nRecent evaluations:")
        for e in recent:
            evidence_lines.append(
                f"  {e.evaluated_at}: {e.outcome} — "
                f"{e.failure_class or 'none'} | {(e.message or '')[:150]}"
            )

    kubeconfig_dir = ""
    kc_path = os.environ.get("STARGATE_EXECUTOR_KUBECONFIG", "")
    if kc_path:
        kubeconfig_dir = os.path.dirname(kc_path)

    result = run_investigation(
        namespace=record.lab_code,
        cluster=record.cluster or "",
        failure_class=record.failure_class or "",
        initial_evidence="\n".join(evidence_lines),
        kubeconfig_dir=kubeconfig_dir,
        job_id=record.job_id,
        db=db,
    )

    model_used = os.environ.get("STARGATE_AGENT_MODEL", "")
    fields = _extract_structured_fields(result.get("analysis", ""))

    repository.complete_investigation(
        db, record.job_id,
        analysis=result.get("analysis", ""),
        tool_calls=result.get("tool_calls", []),
        iterations=result.get("iterations", 0),
        model_used=model_used,
        root_cause=fields.get("root_cause"),
        remediation_suggestion=fields.get("remediation_suggestion"),
        trust_dimensions={"verdict": fields.get("verdict")},
        fallback=result.get("fallback", False),
        error=result.get("error"),
    )

    try:
        from events.models import Event as StarGateEvent
        from api.routers._shared import _event_bus
        _event_bus.emit(StarGateEvent(
            event_type="investigation.completed",
            lab_code=record.lab_code,
            cluster_name=record.cluster,
            failure_class=record.failure_class,
            message=f"Investigation {record.job_id} completed",
            metadata={
                "job_id": record.job_id,
                "trigger_type": record.trigger_type,
                "iterations": result.get("iterations", 0),
            },
        ))
    except Exception as e:
        logger.debug("Failed to emit investigation.completed event: %s", e)


def _extract_structured_fields(analysis: str) -> dict:
    """Extract Root Cause, Shadow Remediation, and Verdict from markdown analysis."""
    import re
    if not analysis:
        return {"root_cause": None, "remediation_suggestion": None, "verdict": None}
    root_cause = None
    remediation = None
    verdict = None

    rc_match = re.search(r'\*\*Root Cause\*\*[:\s]*(.+?)(?=\n\*\*|\Z)', analysis, re.DOTALL)
    if rc_match:
        root_cause = rc_match.group(1).strip()[:500]

    sr_match = re.search(r'\*\*Shadow Remediation\*\*[^:]*[:\s]*(.+?)(?=\n\*\*|\Z)', analysis, re.DOTALL)
    if sr_match:
        remediation = sr_match.group(1).strip()

    v_match = re.search(r'(?:verdict|Verdict)[:\s*]*\*?\*?(TRANSIENT|ACTIONABLE|UNKNOWN)\*?\*?', analysis, re.IGNORECASE)
    if v_match:
        verdict = v_match.group(1).upper()

    return {"root_cause": root_cause, "remediation_suggestion": remediation, "verdict": verdict}
