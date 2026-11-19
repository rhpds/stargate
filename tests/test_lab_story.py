"""One lab's loop as one object — the demo's continuity guarantee."""

from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc)


def _eval(db, lab, stage, outcome, cls=None, message=None, minutes=10):
    from db.models import EvaluationRecord
    db.add(EvaluationRecord(
        run_id=f"r-{lab}-{stage}", stage_id=stage, outcome=outcome,
        failure_class=cls if outcome == "fail" else None,
        message=message, lab_code=lab, cluster_name="ocpv08",
        evaluated_at=NOW - timedelta(minutes=minutes),
    ))
    db.commit()


def _investigation(db, lab):
    from db.models import InvestigationRecord
    row = InvestigationRecord(
        job_id=f"job-{lab}", lab_code=lab, namespace=lab, cluster="ocpv08",
        failure_class="showroom_not_ready", trigger_type="auto",
        status="complete", review_state="unreviewed",
        root_cause="nginx proxied to the wrong route", created_at=NOW,
    )
    db.add(row)
    db.commit()
    return row


def _action(db, lab, status="pending"):
    from db.models import PendingAction
    db.add(PendingAction(
        action_type="inspect_showroom_route", target=lab, confidence=0.8,
        proposed_by="investigation", status=status, proposed_at=NOW,
    ))
    db.commit()


def _knowledge(db, investigation_id):
    from db.models import KnowledgeEntry
    db.add(KnowledgeEntry(
        signature="sig", version=1, active=True,
        root_cause="wrong route", remediation="probe showroom-*",
        provenance={}, investigation_id=investigation_id,
        reviewed_by="reviewer", reviewed_at=NOW,
    ))
    db.commit()


class TestLabStory:
    def test_returns_the_loop_with_gaps_explicit(self, db):
        from db.repository import lab_story

        _eval(db, "sandbox-a", "namespace-ready", "pass", minutes=20)
        _eval(db, "sandbox-a", "showroom-healthy", "fail",
              cls="showroom_not_ready",
              message="Entry criterion not met: showroom_route_reachable", minutes=10)
        inv = _investigation(db, "sandbox-a")
        _action(db, "sandbox-a")
        _knowledge(db, inv.id)

        story = lab_story(db, "sandbox-a")

        assert story["found"] is True
        assert story["signal"]["state"] == "failing"
        assert story["classification"]["failure_class"] == "showroom_not_ready"
        assert story["classification"]["criterion"] == "showroom_route_reachable"
        assert story["decision"]["investigation_id"] == inv.id
        assert story["decision"]["legs"]["diagnosis"] is True
        assert story["decision"]["legs"]["verification"] is False
        assert story["action"]["pending_for_lab"] == 1
        assert story["learning"]["knowledge_for_lab"] == 1

    def test_absent_action_and_knowledge_are_reported(self, db):
        from db.repository import lab_story

        _eval(db, "sandbox-b", "showroom-healthy", "fail",
              cls="showroom_not_ready", message="Entry criterion not met: showroom_route_reachable")

        story = lab_story(db, "sandbox-b")

        assert story["action"]["pending_for_lab"] == 0
        assert story["action"]["action_type"] is None
        assert story["learning"]["knowledge_for_lab"] == 0

    def test_unknown_lab_is_explicit(self, db):
        from db.repository import lab_story
        assert lab_story(db, "sandbox-none")["found"] is False
