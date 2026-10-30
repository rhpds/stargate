"""Non-executing advisory assessment; deliberately separate from action approval."""
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from api.routers._shared import require_admin_read
from engine.stateless_pilot import PilotEvidence, PilotPolicy, assess

router = APIRouter()


@router.post("/admin/remediation/pilot/assess", dependencies=[Depends(require_admin_read)])
def assess_stateless_pilot(body: PilotEvidence):
    configured = os.environ.get("STARGATE_STATELESS_PILOT_TARGET", "")
    try:
        policy = PilotPolicy.model_validate_json(configured) if configured else None
    except (ValueError, ValidationError):
        # Never echo the raw configuration into an HTTP error.
        raise HTTPException(status_code=503, detail="Pilot target configuration invalid")
    return assess(body, policy)
