"""Tests for run-detail and GeoLux retention.

The evidence table reached 70.5M rows / 27GB by Nov 2026 with no retention
at all (only scan snapshots had any), and the 80Gi PVC was projected full
by late Jan 2027. These tests pin the cascade contract (what goes, what
stays), the batching contract, the NULL-started_at guard, the GeoLux
raw-SQL path (those tables have no ORM models), and the size-budget
threshold logic.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from db import repository
from db.models import EvaluationRecord, EvidenceRecord, RunRecord, StageRecord

NOW = datetime.now(timezone.utc)


def make_run(db, run_id, started_at, stages=2, evidence_per_stage=3):
    """Seed one run with its stages, evidence, and evaluations."""
    db.add(RunRecord(
        run_id=run_id, demo_id="demo-ret", namespace=f"ns-{run_id}",
        requested_by="test", status="complete", rubric_version="v1",
        started_at=started_at, completed_at=started_at,
    ))
    for s in range(stages):
        stage_id = f"stage-{s}"
        db.add(StageRecord(run_id=run_id, stage_id=stage_id, status="complete"))
        for e in range(evidence_per_stage):
            db.add(EvidenceRecord(
                evidence_id=f"ev-{run_id}-{s}-{e}", run_id=run_id, stage_id=stage_id,
                type="resource_state", source="test", observed={},
                result="pass", timestamp=started_at,
            ))
        db.add(EvaluationRecord(
            run_id=run_id, stage_id=stage_id, outcome="pass",
            evaluated_at=started_at, lab_code=f"lab-{run_id}", cluster_name="c1",
        ))
    db.commit()
    return run_id


def _count(db, model, run_id):
    return db.query(model).filter(model.run_id == run_id).count()


class TestCleanupOldRuns:
    def test_cascade_deletes_old_keeps_recent(self, db):
        old = make_run(db, "ret-old", NOW - timedelta(days=100))
        recent = make_run(db, "ret-recent", NOW - timedelta(days=1))

        deleted = repository.cleanup_old_runs(db, days=90)

        # old: 1 run + 2 stages + 6 evidence + 2 evaluations = 11 rows
        assert deleted == 11
        for model in (RunRecord, StageRecord, EvidenceRecord, EvaluationRecord):
            assert _count(db, model, old) == 0, model.__tablename__
            assert _count(db, model, recent) > 0, model.__tablename__

    def test_batching_deletes_bounded_runs_per_call(self, db):
        for i in range(3):
            make_run(db, f"ret-batch-{i}", NOW - timedelta(days=200))

        first = repository.cleanup_old_runs(db, days=90, batch_size=2)
        assert first == 22  # two runs' worth (11 each)
        assert db.query(RunRecord).count() == 1

        second = repository.cleanup_old_runs(db, days=90, batch_size=2)
        assert second == 11
        assert repository.cleanup_old_runs(db, days=90, batch_size=2) == 0

    def test_days_zero_disables(self, db):
        make_run(db, "ret-disabled", NOW - timedelta(days=400))
        assert repository.cleanup_old_runs(db, days=0) == 0
        assert db.query(RunRecord).count() == 1

    def test_null_started_at_runs_survive(self, db):
        db.add(RunRecord(
            run_id="ret-null", demo_id="demo-ret", namespace="ns-ret-null",
            requested_by="test", status="pending", rubric_version="v1",
            started_at=None,
        ))
        db.commit()

        repository.cleanup_old_runs(db, days=90)

        assert db.query(RunRecord).filter(RunRecord.run_id == "ret-null").count() == 1


class TestCleanupOldGlx:
    def _create_tables(self, db):
        # Drop first: raw-created tables are not in Base.metadata, so the
        # fixture's per-test reset does not touch them and rows would
        # otherwise leak between tests on the shared in-memory connection.
        for table in repository.GLX_RETENTION_TABLES:
            db.execute(text(f"DROP TABLE IF EXISTS {table}"))
            db.execute(text(
                f"CREATE TABLE {table} "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TIMESTAMP)"
            ))
        db.commit()

    def _seed(self, db, table, old_n, new_n):
        for i in range(old_n):
            db.execute(text(f"INSERT INTO {table} (created_at) VALUES (:t)"),
                       {"t": NOW - timedelta(days=90)})
        for i in range(new_n):
            db.execute(text(f"INSERT INTO {table} (created_at) VALUES (:t)"),
                       {"t": NOW - timedelta(days=1)})
        db.commit()

    def test_deletes_old_rows_in_every_table_keeps_recent(self, db):
        self._create_tables(db)
        for table in repository.GLX_RETENTION_TABLES:
            self._seed(db, table, old_n=5, new_n=2)

        deleted = repository.cleanup_old_glx(db, days=60)

        assert deleted == 25  # 5 old rows x 5 tables
        for table in repository.GLX_RETENTION_TABLES:
            remaining = db.execute(text(f"SELECT count(*) FROM {table}")).scalar()
            assert remaining == 2, table

    def test_days_zero_disables(self, db):
        self._create_tables(db)
        self._seed(db, repository.GLX_RETENTION_TABLES[0], old_n=3, new_n=0)
        assert repository.cleanup_old_glx(db, days=0) == 0
        remaining = db.execute(
            text(f"SELECT count(*) FROM {repository.GLX_RETENTION_TABLES[0]}")
        ).scalar()
        assert remaining == 3

    def test_batch_size_bounds_rows_per_call(self, db):
        self._create_tables(db)
        self._seed(db, repository.GLX_RETENTION_TABLES[0], old_n=10, new_n=0)

        deleted = repository.cleanup_old_glx(db, days=60, batch_size=4)

        assert deleted == 4
        remaining = db.execute(
            text(f"SELECT count(*) FROM {repository.GLX_RETENTION_TABLES[0]}")
        ).scalar()
        assert remaining == 6


class TestDbSizeBudget:
    def test_disabled_when_budget_zero(self):
        assert repository.check_db_size_budget(50 * 1024 ** 3, 0) == ("disabled", 0.0)

    def test_ok_warn_critical_thresholds(self):
        budget = 100
        gb = 1024 ** 3
        assert repository.check_db_size_budget(50 * gb, budget)[0] == "ok"
        assert repository.check_db_size_budget(70 * gb, budget)[0] == "warn"
        assert repository.check_db_size_budget(85 * gb, budget)[0] == "critical"
        # percentage math
        status, pct = repository.check_db_size_budget(75 * gb, budget)
        assert status == "warn"
        assert abs(pct - 75.0) < 0.01
