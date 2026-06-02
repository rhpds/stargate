"""Integration endpoints — receives events from Launchpad and other platforms."""

import logging
import os
from collections import OrderedDict
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.app import repository
from api.app.models import Evidence, Run, RunStatus, StageOutcome
from api.app.rubric_loader import load_rubrics_from_directory, RubricLoadError
from api.app.api._helpers import load_rubric_for_stage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["integration"])

INTEGRATION_API_KEY = os.environ.get("INTEGRATION_API_KEY")

_seen_events: OrderedDict = OrderedDict()
_MAX_SEEN = 10000


def _verify_api_key(request: Request):
    if not INTEGRATION_API_KEY:
        return
    key = request.headers.get("X-API-Key")
    if key != INTEGRATION_API_KEY:
        raise HTTPException(401, "Invalid or missing X-API-Key")


def _check_duplicate(event_id: str) -> bool:
    if event_id in _seen_events:
        return True
    _seen_events[event_id] = True
    if len(_seen_events) > _MAX_SEEN:
        _seen_events.popitem(last=False)
    return False


class IntegrationEvent(BaseModel):
    source: Literal["launchpad", "stargate"]
    event_type: str
    event_id: str
    timestamp: str
    payload: dict


class EvaluateResponse(BaseModel):
    allowed: bool
    level: str
    reasons: list[str]


@router.post("/integration/events")
async def receive_event(event: IntegrationEvent, request: Request):
    """Receive lifecycle events from Launchpad or other integrated platforms."""
    _verify_api_key(request)

    if _check_duplicate(event.event_id):
        return {"received": True, "event_id": event.event_id, "duplicate": True}

    if event.source == "launchpad":
        payload = event.payload
        session_id = payload.get("session_id", "unknown")
        outcome = payload.get("outcome", "info")
        lab_code = payload.get("lab_code", "")

        run_id = f"launchpad-{session_id}"
        existing = await repository.get_run(run_id)
        if not existing:
            run = Run(
                run_id=run_id,
                demo_id=lab_code or "launchpad-session",
                namespace=payload.get("cluster_name", "unknown"),
                requested_by="launchpad",
                status=RunStatus.RUNNING,
                rubric_version="external",
            )
            await repository.create_run(run)

        stage_outcome = StageOutcome.PASS
        if outcome == "fail":
            stage_outcome = StageOutcome.FAIL
        elif outcome == "info":
            stage_outcome = StageOutcome.PASS

        evidence = Evidence(
            evidence_id=event.event_id,
            run_id=run_id,
            stage_id=event.event_type,
            type="lifecycle_event",
            source="launchpad",
            observed=payload,
            result=stage_outcome,
            timestamp=event.timestamp,
        )
        await repository.create_evidence(evidence)

        logger.info("Received Launchpad event: session=%s, outcome=%s", session_id, outcome)
        return {"received": True, "event_id": event.event_id, "run_id": run_id}

    return {"received": True, "event_id": event.event_id, "processed": False}


@router.get("/integration/evaluate", response_model=EvaluateResponse)
async def evaluate_provision(catalog_item: str, tenant: str, request: Request):
    _verify_api_key(request)
    """Pre-flight check for Launchpad provisioning requests."""
    reasons = []
    level = "allowed"

    try:
        from api.app.api._helpers import RUBRIC_DIR
        if RUBRIC_DIR.is_dir():
            from api.app.rubric_loader import load_rubrics_from_directory
            load_rubrics_from_directory(RUBRIC_DIR)
    except Exception as e:
        logger.debug("Rubric loading during evaluate: %s", e)

    return EvaluateResponse(allowed=True, level=level, reasons=reasons)
