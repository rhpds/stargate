"""Tests for the investigate -> suggest -> approve -> verify loop closure.

- ACTIONABLE investigations queue a human-review PendingAction carrying the
  full lineage (investigation, triggering eval, catalog candidates)
- TRANSIENT/UNKNOWN investigations and suggestion-less investigations queue
  nothing
- Queuing is idempotent per investigation
- link_remediation_verification links executed remediations to the first
  passing eval after application (the verify leg)
"""

from datetime import datetime, timedelta, timezone

from db import repository
from db.models import EvaluationRecord, InvestigationRecord, PendingAction, RemediationRecord


def _investigation(db, *, verdict, suggestion="Restart the crashlooping deployment", fc="pods_crashlooping"):
    record = InvestigationRecord(
        job_id="job-loop-1", lab_code="sandbox-loop", cluster="ocpv05",
        namespace="sandbox-loop", failure_class=fc, trigger_type="auto_anomalous",
        status="queued", triggering_eval_id=42, created_at=datetime.now(timezone.utc),
    )
    db.add(record)
    db.commit()
    return record


def _complete(db, record, verdict, suggestion="Restart the crashlooping deployment"):
    repository.complete_investigation(
        db, record.job_id, analysis="## Diagnosis\nstuff",
        root_cause="bad config", remediation_suggestion=suggestion,
        trust_dimensions={"verdict": verdict, "confidence": 80},
    )
    db.refresh(record)


class TestActionableInvestigationQueuesAction:
    def test_actionable_creates_pending_action_with_lineage(self, db):
        record = _investigation(db, verdict="ACTIONABLE")
        _complete(db, record, "ACTIONABLE")

        action = db.query(PendingAction).filter(PendingAction.proposed_by == "investigation").one()
        assert action.status == "pending"  # human-review only, never executes
        assert action.target == "sandbox-loop"
        params = action.parameters
        assert params["investigation_id"] == record.id
        assert params["job_id"] == "job-loop-1"
        assert params["triggering_eval_id"] == 42
        assert "Restart the crashlooping deployment" in params["remediation_suggestion"]
        assert "pods_crashlooping" in params["failure_class"]
        # catalog mapping: pods_crashlooping -> cleanup_stuck
        assert "cleanup_stuck" in params["catalog_actions"]
        assert action.action_type == "cleanup_stuck"

    def test_transient_does_not_queue(self, db):
        record = _investigation(db, verdict="TRANSIENT")
        _complete(db, record, "TRANSIENT")
        assert db.query(PendingAction).filter(PendingAction.proposed_by == "investigation").count() == 0

    def test_unknown_does_not_queue(self, db):
        record = _investigation(db, verdict="UNKNOWN")
        _complete(db, record, "UNKNOWN")
        assert db.query(PendingAction).filter(PendingAction.proposed_by == "investigation").count() == 0

    def test_actionable_without_suggestion_does_not_queue(self, db):
        record = _investigation(db, verdict="ACTIONABLE")
        _complete(db, record, "ACTIONABLE", suggestion="")
        assert db.query(PendingAction).filter(PendingAction.proposed_by == "investigation").count() == 0

    def test_queuing_is_idempotent_per_investigation(self, db):
        record = _investigation(db, verdict="ACTIONABLE")
        _complete(db, record, "ACTIONABLE")
        # A second completion of the same investigation must not duplicate
        repository.complete_investigation(
            db, record.job_id, analysis="again", root_cause="again",
            remediation_suggestion="Restart it",
            trust_dimensions={"verdict": "ACTIONABLE", "confidence": 80},
        )
        assert db.query(PendingAction).filter(PendingAction.proposed_by == "investigation").count() == 1

    def test_lifecycle_failure_class_maps_to_reclamation_catalog(self, db):
        record = _investigation(db, verdict="ACTIONABLE", fc="teardown_stuck")
        _complete(db, record, "ACTIONABLE")
        action = db.query(PendingAction).filter(PendingAction.proposed_by == "investigation").one()
        # Reclamation classes map through the remediation catalog's
        # allowed_when (the hardcoded policy map lacks them): the queued
        # action carries the actual reclamation candidates.
        params = action.parameters
        assert "investigate_stuck_teardown" in params["catalog_actions"]
        assert "inspect_anarchy_destroy_state" in params["catalog_actions"]
        assert action.action_type in params["catalog_actions"]


class TestVerificationLink:
    def _remediation(self, db, applied_hours_ago=3):
        rec = RemediationRecord(
            run_id="sandbox-loop", stage_id="", failure_class="pods_crashlooping",
            remediation_id="cleanup_stuck", action_taken="restart",
            resolved=None, applied_at=datetime.now(timezone.utc) - timedelta(hours=applied_hours_ago),
            applied_by="admin:admin", notes="investigation:1",
        )
        db.add(rec)
        db.commit()
        return rec

    def test_passing_eval_after_application_verifies(self, db):
        remediation = self._remediation(db)
        db.add(EvaluationRecord(
            run_id="scan-1", stage_id="cluster-health", lab_code="sandbox-loop",
            cluster_name="ocpv05", outcome="pass", failure_class=None,
            message="healthy", evaluated_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ))
        db.commit()

        linked = repository.link_remediation_verification(db)

        assert linked == 1
        db.refresh(remediation)
        assert remediation.resolved is True
        assert remediation.verification_eval_id is not None

    def test_no_passing_eval_leaves_unresolved(self, db):
        remediation = self._remediation(db)
        db.add(EvaluationRecord(
            run_id="scan-1", stage_id="cluster-health", lab_code="sandbox-loop",
            cluster_name="ocpv05", outcome="fail", failure_class="pods_crashlooping",
            message="still broken", evaluated_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ))
        db.commit()

        linked = repository.link_remediation_verification(db)

        assert linked == 0
        db.refresh(remediation)
        assert remediation.resolved is None
        assert remediation.verification_eval_id is None

    def test_passing_eval_before_application_does_not_verify(self, db):
        remediation = self._remediation(db, applied_hours_ago=1)
        db.add(EvaluationRecord(
            run_id="scan-0", stage_id="cluster-health", lab_code="sandbox-loop",
            cluster_name="ocpv05", outcome="pass", failure_class=None,
            message="old pass", evaluated_at=datetime.now(timezone.utc) - timedelta(hours=5),
        ))
        db.commit()

        linked = repository.link_remediation_verification(db)

        assert linked == 0
        db.refresh(remediation)
        assert remediation.resolved is None
