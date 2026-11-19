"""Backfilling historical run completion — from the run's own evaluations."""

from datetime import datetime, timedelta, timezone

from scripts.backfill_run_completion import backfill


def _run(db, run_id, hours_ago=48, status="running"):
    from db.models import RunRecord
    db.add(RunRecord(
        run_id=run_id, demo_id="d", namespace="n", requested_by="t",
        status=status, rubric_version="v", started_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
    ))
    db.commit()


def _eval(db, run_id, outcome, minutes):
    from db.models import EvaluationRecord
    db.add(EvaluationRecord(
        run_id=run_id, stage_id="s", outcome=outcome,
        evaluated_at=datetime.now(timezone.utc) - timedelta(minutes=minutes),
    ))
    db.commit()


class TestBackfill:
    def test_uses_the_last_evaluation_and_failure_state(self, db):
        _run(db, "r1")
        _eval(db, "r1", "pass", 30)
        _eval(db, "r1", "fail", 10)
        _run(db, "r2")
        _eval(db, "r2", "pass", 20)

        report = backfill(db, older_than_hours=24)

        from db.models import RunRecord
        r1 = db.query(RunRecord).filter_by(run_id="r1").one()
        r2 = db.query(RunRecord).filter_by(run_id="r2").one()
        assert (r1.status, r2.status) == ("failed", "completed")
        assert r1.completed_at is not None and r2.completed_at is not None
        assert report["updated"] == 2

    def test_leaves_runs_without_evidence_alone_unless_asked(self, db):
        _run(db, "orphan")

        report = backfill(db, older_than_hours=24)

        from db.models import RunRecord
        assert db.query(RunRecord).filter_by(run_id="orphan").one().status == "running"
        assert report["skipped_no_evaluations"] == 1

    def test_status_only_closes_orphans_without_a_timestamp(self, db):
        _run(db, "orphan")

        backfill(db, older_than_hours=24, status_only=True)

        from db.models import RunRecord
        row = db.query(RunRecord).filter_by(run_id="orphan").one()
        assert (row.status, row.completed_at) == ("completed", None)

    def test_ignores_runs_inside_the_window(self, db):
        _run(db, "recent", hours_ago=1)
        _eval(db, "recent", "pass", 1)

        report = backfill(db, older_than_hours=24)

        from db.models import RunRecord
        assert db.query(RunRecord).filter_by(run_id="recent").one().status == "running"
        assert report["updated"] == 0
