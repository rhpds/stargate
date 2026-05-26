"""Rubric validation and evaluation endpoints."""

from typing import Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.app.models import Rubric
from api.app.rubric_evaluator import evaluate_rubric
from api.app.api._helpers import load_rubric_for_stage

router = APIRouter(prefix="/api/v1", tags=["rubrics"])


class ValidateRubricRequest(BaseModel):
    rubric: Dict


class EvaluateRubricRequest(BaseModel):
    evidence: Dict


@router.post("/rubrics/validate")
async def validate_rubric(req: ValidateRubricRequest):
    try:
        rubric = Rubric(**req.rubric)
        return {"valid": True, "rubric_id": rubric.id, "version": rubric.version}
    except Exception as e:
        return {"valid": False, "error": str(e)}


@router.get("/rubrics/{stage_id}")
async def get_rubric(stage_id: str):
    rubric = load_rubric_for_stage(stage_id)
    if not rubric:
        raise HTTPException(status_code=404, detail=f"No rubric found for stage {stage_id}")
    return rubric.model_dump()


@router.post("/rubrics/{stage_id}/evaluate")
async def evaluate_rubric_endpoint(stage_id: str, req: EvaluateRubricRequest):
    rubric = load_rubric_for_stage(stage_id)
    if not rubric:
        raise HTTPException(status_code=404, detail=f"No rubric found for stage {stage_id}")

    result = evaluate_rubric(rubric, req.evidence)
    return {
        "stage_id": result.stage_id,
        "outcome": result.outcome.value,
        "failure_class": result.failure_class,
        "message": result.message,
        "criteria": [
            {"name": c.name, "required": c.required, "passed": c.passed}
            for c in result.criteria_results
        ],
    }
