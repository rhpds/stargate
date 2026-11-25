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
    from engine.functional_alignment import investigation_source_evidence
    source_evidence = investigation_source_evidence(db, record.job_id)
    if source_evidence:
        evidence_lines.append(source_evidence)
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
        cost_estimate=result.get("cost_estimate"),
        root_cause=fields.get("root_cause"),
        remediation_suggestion=fields.get("remediation_suggestion"),
        trust_dimensions={
            "verdict": fields.get("verdict"),
            "confidence": fields.get("confidence"),
            "usage_optimized": bool(result.get("usage_optimized")),
            "evidence_sufficient": bool(result.get("evidence_sufficient")),
        },
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


_ADJUDICATION_HEADER = "### Model adjudication"


def _strip_adjudication_summary(analysis: str) -> str:
    """Remove the appended model-adjudication block before parsing.

    ``run_investigation`` appends a review summary to the analysis — lines like
    "Blind reviewer 2: ACTIONABLE (75% model confidence)" and the judge's
    rationale. Those are reviewer *opinions*, not the investigating agent's
    verdict, and they sit after the report with no Verdict heading. Reading
    them as report text invented a verdict for 48 stored investigations, so the
    block is dropped before any field is parsed.
    """
    if not analysis:
        return analysis
    index = analysis.find(_ADJUDICATION_HEADER)
    return analysis[:index].rstrip() if index != -1 else analysis


def _extract_structured_fields(analysis: str) -> dict:
    """Extract quality fields from common markdown heading variants."""
    import re
    if not analysis:
        return {"root_cause": None, "remediation_suggestion": None, "verdict": None, "confidence": None}

    # The adjudication summary is reviewer output, not the report; never parse it.
    analysis = _strip_adjudication_summary(analysis)

    # Allow emoji and other unicode decoration between the section number
    # and the heading text (the Sonnet agent produces "### 2. 🔍 Root Cause").
    heading = r"(?:^|\n)\s*(?:#{1,6}\s*)?(?:\d+\.\s*)?(?:[^\w\n]{0,4}\s*)?(?:\*\*)?%s(?:\*\*)?\s*:?[ \t]*\n?"
    next_heading = r"(?=\n\s*(?:#{1,6}\s*|(?:\d+\.\s*)?\*\*)|\Z)"

    def section(name: str, limit=None):
        match = re.search((heading % name) + r"(.+?)" + next_heading, analysis, re.IGNORECASE | re.DOTALL)
        value = match.group(1).strip() if match else None
        return value[:limit] if value and limit else value

    def sections(name: str):
        pattern = (heading % name) + r"(.+?)" + next_heading
        return [m.group(1) for m in re.finditer(pattern, analysis, re.IGNORECASE | re.DOTALL)]

    root_cause = section(r"Root Cause", 500)
    remediation = section(r"(?:Recommended |Shadow )?Remediation(?: Strategy)?", 2000)
    # Trim trailing verdict/confidence that bleed into the remediation section
    if remediation:
        import re as _re
        remediation = _re.split(
            r'\n\s*(?:Verdict|Confidence|Owner|Shadow Remediation)\s*[:\n]',
            remediation, flags=_re.IGNORECASE
        )[0].strip()
    # The agent renders the verdict in several shapes, and only one of them puts
    # the enum next to the word: "**Verdict**: ACTIONABLE", a table row
    # "| Verdict | TRANSIENT |", or — most commonly — a heading followed by a
    # blockquote:
    #
    #     ### 6. Verdict
    #
    #     > **TRANSIENT**
    #
    # The old pattern required the enum to follow "Verdict" through nothing but
    # `[:\s*]`, so the `>` form, the `|` form and a bolded value on the next
    # line all produced NULL — 45% of stored investigations had no verdict at
    # all, which silently disabled verdict-based suppression and tri-state
    # reporting. Search the Verdict section for the enum instead of requiring
    # adjacency.
    #
    # There is deliberately no document-wide fallback. An earlier version
    # scanned the whole analysis for a bare enum, "case-sensitive so prose
    # cannot invent a verdict" — but prose does write ACTIONABLE in upper case:
    # "the underlying teardown_stuck pattern is ACTIONABLE", "the PVC is
    # primary — ACTIONABLE". All 50 stored investigations that had a verdict but
    # no Verdict section traced back to that scan or to the adjudication block,
    # so it recovered no real verdict and invented 50. A report that does not
    # state a verdict has no verdict.
    #
    # The heading itself is matched case-insensitively, so an earlier lower-case
    # mention can match first and end before the real heading — a YAML
    # `verdict: complete` key inside a remediation snippet does exactly that.
    # Consider every candidate and take the first that states an enum; one that
    # does not name a verdict says nothing.
    verdict = None
    for verdict_scope in sections(r"Verdict"):
        v_match = re.search(r"\b(TRANSIENT|ACTIONABLE|UNKNOWN)\b", verdict_scope)
        if not v_match:
            # Models occasionally lowercase the enum inside the section; the
            # section is narrow enough that this cannot pick up prose from
            # elsewhere.
            v_match = re.search(
                r"\b(TRANSIENT|ACTIONABLE|UNKNOWN)\b", verdict_scope, re.IGNORECASE
            )
        if v_match:
            verdict = v_match.group(1).upper()
            break

    confidence = None
    c_match = re.search(
        r"confidence(?:\*\*)?\s*:?\s*(?:\*\*)?([01](?:\.\d+)?|\d{1,3})(?:\s*%)?",
        analysis,
        re.IGNORECASE,
    )
    if c_match:
        confidence = float(c_match.group(1))
        if confidence > 1:
            confidence /= 100
        confidence = max(0.0, min(confidence, 1.0))

    return {"root_cause": root_cause, "remediation_suggestion": remediation,
            "verdict": verdict, "confidence": confidence}
