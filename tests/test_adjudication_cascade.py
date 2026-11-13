"""Adjudication cascade — reviews resolve their linked disputes.

TDD: written before the cascade exists. When review_diagnosis approves
or rejects an investigation, any adjudication for it that sits in
needs_human_review resolves with the human verdict — the review queue
and the adjudication queue are the same human judgment, recorded once.
"""

from datetime import datetime, timezone

import pytest

from db.models import AdjudicationRecord, InvestigationRecord


@pytest.fixture
def investigation(db):
    inv = InvestigationRecord(
        job_id="adj-cascade-1", lab_code="lab", namespace="ns",
        cluster="c", failure_class="showroom_not_ready",
        status="complete", root_cause="test root cause",
        review_state="unreviewed",
        created_at=datetime.now(timezone.utc),
    )
    db.add(inv)
    db.commit()
    return inv


@pytest.fixture
def adjudication(db, investigation):
    adj = AdjudicationRecord(
        investigation_id=investigation.id,
        diagnosis_version=1, evidence_hash="cascade-hash",
        status="needs_human_review",
        reason="verdict_disagreement",
        created_at=datetime.now(timezone.utc),
        reviews=[], judge={}, models=[], total_tokens=0,
    )
    db.add(adj)
    db.commit()
    return adj


class TestAdjudicationCascade:
    def test_approval_resolves_dispute_as_human_confirmed(self, db, monkeypatch,
                                                          investigation, adjudication):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        result = mcp_server.review_diagnosis(
            investigation.id, approved=True, notes="cascade test")
        assert "APPROVED" in result
        db.refresh(adjudication)
        assert adjudication.status == "human_confirmed"
        assert adjudication.completed_at is not None

    def test_rejection_resolves_as_human_rejected(self, db, monkeypatch,
                                                  investigation, adjudication):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        result = mcp_server.review_diagnosis(
            investigation.id, approved=False, notes="wrong")
        assert "REJECTED" in result or "Rejected" in result
        db.refresh(adjudication)
        assert adjudication.status == "human_rejected"

    def test_model_supported_adjudications_untouched(self, db, monkeypatch,
                                                     investigation):
        from api import mcp_server
        adj = AdjudicationRecord(
            investigation_id=investigation.id,
            diagnosis_version=1, evidence_hash="cascade-hash-2",
            status="model_supported",
            reason=None,
            created_at=datetime.now(timezone.utc), reviews=[], judge={}, models=[], total_tokens=0,
        )
        db.add(adj)
        db.commit()
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        mcp_server.review_diagnosis(investigation.id, approved=True, notes="")
        db.refresh(adj)
        assert adj.status == "model_supported"

    def test_no_adjudication_review_still_works(self, db, monkeypatch, investigation):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        result = mcp_server.review_diagnosis(investigation.id, approved=True)
        assert "APPROVED" in result
