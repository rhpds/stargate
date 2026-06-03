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
    """Pre-fetch external API caches."""
    try:
        from api.routers._shared import _fetch_labagator_labs, _fetch_labagator_sessions, _fetch_demolition_sessions
        _fetch_labagator_labs()
        _fetch_labagator_sessions()
        _fetch_demolition_sessions()
        logger.info("Cache warm complete")
        return {"status": "ok"}
    except Exception as e:
        logger.warning("Cache warm failed: %s", e)
        return {"error": str(e)}


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
