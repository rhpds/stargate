"""Learner — closes the feedback loop by analyzing human feedback.

Reads from llm_feedback table, calculates calibration factors per endpoint,
and stores them for future confidence adjustment.
"""

import logging
from typing import Dict, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("stargate.learner")


def apply_feedback(db: Session) -> Dict[str, Dict]:
    """Analyze all feedback and produce calibration data per endpoint."""
    from db.models import LLMFeedback, Receipt
    from datetime import datetime, timezone

    feedback = db.query(LLMFeedback).all()
    if not feedback:
        return {}

    by_endpoint: Dict[str, Dict] = {}
    for f in feedback:
        ep = f.endpoint or "unknown"
        if ep not in by_endpoint:
            by_endpoint[ep] = {"total": 0, "helpful": 0, "not_helpful": 0}
        by_endpoint[ep]["total"] += 1
        if f.helpful:
            by_endpoint[ep]["helpful"] += 1
        else:
            by_endpoint[ep]["not_helpful"] += 1

    result = {}
    for ep, counts in by_endpoint.items():
        rate = counts["helpful"] / max(counts["total"], 1)
        result[ep] = {
            "total_feedback": counts["total"],
            "helpful": counts["helpful"],
            "not_helpful": counts["not_helpful"],
            "helpful_rate": round(rate, 3),
            "calibration_factor": round(rate, 3),
        }

    # Persist calibration as a receipt
    try:
        from db.repository import save_receipt
        save_receipt(db, "calibration", None, result, True)
    except Exception as e:
        logger.warning(f"Failed to save calibration receipt: {e}")

    return result


def get_calibration(db: Session, endpoint: str) -> Optional[Dict]:
    """Get the latest calibration data for an endpoint."""
    from db.repository import get_latest_receipt
    receipt = get_latest_receipt(db, "calibration")
    if not receipt:
        return None
    data = receipt.get("data", {})
    return data.get(endpoint)


def apply_calibration(db: Session, endpoint: str, raw_confidence: float) -> float:
    """Apply calibration factor to a raw confidence score.

    Returns adjusted confidence if calibration data exists, otherwise raw score.
    """
    cal = get_calibration(db, endpoint)
    if cal is None:
        return raw_confidence
    factor = cal.get("calibration_factor", 1.0)
    return round(raw_confidence * factor, 4)
