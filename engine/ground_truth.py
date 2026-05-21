"""Ground truth dataset — builds labeled data from approved proposals and confirmed evaluations."""

from __future__ import annotations

import logging
from typing import Dict, List

from sqlalchemy.orm import Session

logger = logging.getLogger("stargate.ground_truth")


def build_ground_truth(db: Session) -> List[Dict]:
    """Build a ground truth dataset from human-validated data.

    Sources:
    1. ProposedClassification where reviewed=True AND approved=True
    2. EvaluationRecord where human_confirmed=True
    """
    from db.models import ProposedClassification, EvaluationRecord

    entries = []
    seen = set()

    proposals = (
        db.query(ProposedClassification)
        .filter(ProposedClassification.reviewed == True, ProposedClassification.approved == True)
        .all()
    )
    for p in proposals:
        key = (p.stage_id, p.proposed_class)
        if key not in seen:
            seen.add(key)
            entries.append({
                "stage_id": p.stage_id,
                "expected_class": p.proposed_class,
                "confidence": p.confidence,
                "source": "approved_proposal",
                "confirmed_at": (p.reviewed_at or p.proposed_at).isoformat() if (p.reviewed_at or p.proposed_at) else None,
                "run_id": p.run_id,
            })

    evals = (
        db.query(EvaluationRecord)
        .filter(EvaluationRecord.human_confirmed == True)
        .all()
    )
    for ev in evals:
        fc = ev.human_corrected_class or ev.failure_class
        if not fc:
            continue
        key = (ev.stage_id, fc)
        if key not in seen:
            seen.add(key)
            entries.append({
                "stage_id": ev.stage_id,
                "expected_class": fc,
                "confidence": None,
                "source": "human_confirmed",
                "confirmed_at": ev.evaluated_at.isoformat() if ev.evaluated_at else None,
                "run_id": ev.run_id,
            })

    return entries


def measure_accuracy(db: Session) -> Dict:
    """Measure LLM classification accuracy against reviewed proposals.

    Compares all reviewed proposals: approved = correct, rejected = incorrect.
    """
    from db.models import ProposedClassification

    reviewed = (
        db.query(ProposedClassification)
        .filter(ProposedClassification.reviewed == True)
        .all()
    )

    total = len(reviewed)
    correct = sum(1 for p in reviewed if p.approved)

    by_class: Dict[str, Dict] = {}
    for p in reviewed:
        cls = p.proposed_class
        if cls not in by_class:
            by_class[cls] = {"correct": 0, "total": 0}
        by_class[cls]["total"] += 1
        if p.approved:
            by_class[cls]["correct"] += 1

    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / max(total, 1), 4),
        "by_class": by_class,
    }
