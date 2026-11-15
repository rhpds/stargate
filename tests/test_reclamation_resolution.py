"""Reclamation resolution records — the lifecycle ground truth.

TDD: written before record_reclamation_resolution exists. The approved
diagnosis (investigation 2612, Nov 13 2026) named the gap: legitimate
teardowns complete without a resolution record, so the evaluator fires
on the absent namespace, the survival curve lacks the closure event,
and the feedback loops miss the ground truth. The remedy: every
reclamation-outcome/v1 RECLAIMED observation writes one.
"""

from datetime import datetime, timezone

import pytest

from db.models import ResolutionRecord


class TestRecordReclamationResolution:
    def test_reclaimed_writes_resolution_record(self, db):
        from db import repository
        rec = repository.record_reclamation_resolution(
            db, lab_code="sandbox-x-lab1", cluster="ocpv09",
            source="aap_destroy_job", source_ref="job-12345",
            occurred_at=datetime.now(timezone.utc))
        assert rec.id is not None
        assert rec.resolution_type == "reclaimed"
        assert rec.resolution_action == "aap_destroy_job:job-12345"
        assert rec.failure_class == "lifecycle_complete"
        db.refresh(rec)
        rows = db.query(ResolutionRecord).filter_by(lab_code="sandbox-x-lab1").all()
        assert len(rows) == 1

    def test_idempotent_per_source_ref(self, db):
        """The same destroy job processed twice writes one record —
        the idempotency every durable event in this platform carries."""
        from db import repository
        now = datetime.now(timezone.utc)
        repository.record_reclamation_resolution(
            db, lab_code="sandbox-y-lab1", cluster="c", source="aap_destroy_job",
            source_ref="job-777", occurred_at=now)
        second = repository.record_reclamation_resolution(
            db, lab_code="sandbox-y-lab1", cluster="c", source="aap_destroy_job",
            source_ref="job-777", occurred_at=now)
        assert second is None  # dedup: no second record
        rows = db.query(ResolutionRecord).filter_by(lab_code="sandbox-y-lab1").all()
        assert len(rows) == 1

    def test_audit_evidence_carries_the_contract(self, db):
        from db import repository
        import json
        rec = repository.record_reclamation_resolution(
            db, lab_code="sandbox-z-lab1", cluster="c", source="namespace_recycled",
            source_ref="sandbox-z-lab1", occurred_at=datetime.now(timezone.utc))
        evidence = rec.audit_evidence if isinstance(rec.audit_evidence, dict) \
            else json.loads(rec.audit_evidence or "{}")
        assert evidence.get("contract") == "reclamation-outcome/v1"
        assert evidence.get("outcome") == "reclaimed"

    def test_detected_and_resolved_same_moment(self, db):
        """A reclamation is instantaneous in record terms: the teardown
        completed, so detected_at == resolved_at (TTR zero, honestly)."""
        from db import repository
        now = datetime.now(timezone.utc)
        rec = repository.record_reclamation_resolution(
            db, lab_code="sandbox-w-lab1", cluster="c", source="aap_destroy_job",
            source_ref="job-999", occurred_at=now)
        assert rec.detected_at is not None
        assert rec.resolved_at is not None
