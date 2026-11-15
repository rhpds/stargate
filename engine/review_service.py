"""Investigation review service — one definition site for the review act.

Both surfaces call this: the MCP tool (review_diagnosis) and the
dashboard HTTP endpoint. Records the review, publishes the knowledge
entry on approval, and cascades into linked adjudication disputes.
Returns human-readable result parts.
"""

from datetime import datetime, timezone
from typing import List, Optional


def perform_review(db, investigation_id: int, approved: bool,
                   notes: str, reviewer_id: str) -> List[str]:
    """Execute one review. Returns result parts (joined by the caller)."""
    import hashlib
    from db.models import InvestigationRecord, KnowledgeEntry

    inv = db.query(InvestigationRecord).filter(
        InvestigationRecord.id == investigation_id).first()
    if not inv:
        return [f"ERROR: investigation {investigation_id} not found"]

    if inv.review_state == "reviewed":
        existing = db.query(KnowledgeEntry).filter(
            KnowledgeEntry.investigation_id == investigation_id,
            KnowledgeEntry.active == True,
        ).first()
        if existing:
            return [
                f"Investigation {investigation_id} already reviewed and published "
                f"as knowledge entry v{existing.version} by {existing.reviewed_by}. "
                f"No changes made."
            ]

    inv.review_state = "reviewed" if approved else "rejected"
    inv.reviewed_at = datetime.now(timezone.utc)
    inv.reviewed_by = reviewer_id

    result_parts = [
        f"Review recorded for investigation {investigation_id}: "
        f"{'APPROVED' if approved else 'REJECTED'}"
    ]

    if approved and inv.root_cause and inv.remediation_suggestion:
        signature = f"{inv.lab_code}:{inv.failure_class}".lower()
        prior = db.query(KnowledgeEntry).filter_by(
            signature=signature, active=True
        ).order_by(KnowledgeEntry.version.desc()).first()
        version = (prior.version + 1) if prior else 1
        now = datetime.now(timezone.utc)
        if prior:
            prior.active = False
            prior.retired_at = now
        entry = KnowledgeEntry(
            signature=signature, version=version, active=True,
            root_cause=inv.root_cause,
            remediation=inv.remediation_suggestion,
            metadata_json={"lab_code": inv.lab_code,
                           "failure_class": inv.failure_class,
                           "review_notes": notes[:500] if notes else None},
            provenance={"investigation_id": inv.id, "job_id": inv.job_id,
                        "evidence_hash": inv.evidence_hash},
            confidence=(inv.trust_dimensions or {}).get("confidence"),
            investigation_id=inv.id,
            reviewed_by=reviewer_id, reviewed_at=now,
        )
        db.add(entry)
        result_parts.append(
            f"Published to knowledge base as {signature} v{version}. "
            f"Future investigations for this failure class will reference this diagnosis."
        )
    elif approved:
        result_parts.append(
            "NOTE: this investigation has no root_cause/remediation_suggestion, "
            "so no knowledge entry was published."
        )
    else:
        result_parts.append(
            "Rejected diagnoses are marked for re-examination and will "
            "not be used for knowledge."
        )

    # Cascade into linked adjudication disputes (the same human judgment)
    try:
        from engine.adjudication import resolve_for_review
        resolved = resolve_for_review(db, investigation_id, approved)
        if resolved:
            result_parts.append(
                f"Resolved {resolved} linked adjudication dispute(s) "
                f"({'human_confirmed' if approved else 'human_rejected'}).")
    except Exception as exc:
        result_parts.append(f"(adjudication cascade skipped: {exc})")

    db.commit()
    return result_parts


def reviewer_id_from_key(caller_key: Optional[str]) -> str:
    """MCP attribution: hashed key id (never the raw key)."""
    import hashlib
    import os
    key = caller_key or os.environ.get("_MCP_CALLER_KEY", "unknown")
    return "mcp:" + hashlib.sha256(key.encode()).hexdigest()[:8]
