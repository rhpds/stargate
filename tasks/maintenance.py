"""Maintenance tasks — MV refresh, cache warming, corpus mining."""

import logging

from celery import shared_task

logger = logging.getLogger("stargate.tasks.maintenance")


@shared_task(bind=True, max_retries=1)
def mv_refresh(self):
    """Refresh materialized views and run calibration."""
    try:
        from db.database import get_db
        from db import repository
        db = next(get_db())
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
        db.close()
        logger.info("MV refresh complete")
        return {"status": "ok"}
    except Exception as e:
        logger.warning("MV refresh failed: %s", e)
        return {"error": str(e)}


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
            db = next(get_db())
            repository.save_sandbox_metrics(db, data)
            db.close()
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
    try:
        from engine.corpus_runner import run_all_miners
        from db.database import get_db
        db = next(get_db())
        result = run_all_miners(db=db)
        db.close()
        logger.info("Corpus mining: %d findings", result.get("total_findings", 0))
        return result
    except Exception as e:
        logger.warning("Corpus mining failed: %s", e)
        return {"error": str(e)}
