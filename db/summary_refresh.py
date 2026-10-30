"""Aggregate the complete summary window in SQL, not in API-process row loops."""
from datetime import datetime, timedelta, timezone
from functools import wraps
import logging

from sqlalchemy import and_, case, func, select

from db.models import EvaluationRecord as E, MVClusterSummary, MVPipelineStage, MVLabEvalSummary


# Stable, database-local two-int advisory keys; never use Python's salted hash.
_LOCK_NAMESPACE = 0x53544753  # STGS, separate from single-bigint advisory users.
_LOCK_KEYS = {MVClusterSummary: 1, MVPipelineStage: 2, MVLabEvalSummary: 3}
_logger = logging.getLogger("stargate")


def _single_writer(model):
    """Own a clean refresh transaction, including its evidence read.

    PostgreSQL workers try once and skip contention, rather than queue stale
    snapshots. The transaction releases ownership on commit, rollback or close.
    SQLite is only the single-writer development/unit-test backend.
    """
    def decorate(refresh):
        @wraps(refresh)
        def owned(db, now):
            if db.new or db.dirty or db.deleted:
                raise RuntimeError("Summary refresh requires a clean session")
            if db.in_nested_transaction():
                raise RuntimeError("Summary refresh cannot own a nested transaction")
            try:
                if db.get_bind().dialect.name == "postgresql":
                    if db.connection().get_isolation_level() != "READ COMMITTED":
                        raise RuntimeError("Summary refresh requires READ COMMITTED")
                    acquired = db.execute(select(func.pg_try_advisory_xact_lock(
                        _LOCK_NAMESPACE, _LOCK_KEYS[model],
                    ))).scalar_one()
                    if not acquired:
                        db.rollback()
                        _logger.info("summary_refresh status=skipped_busy table=%s", model.__tablename__)
                        return False
                return refresh(db, now)
            except BaseException:
                db.rollback()
                raise
        return owned
    return decorate


def _window(db, now, *columns):
    return db.query(*columns).filter(
        E.evaluated_at >= now - timedelta(hours=24),
        ~E.run_id.like("k8s-mine-%"),
        ~E.run_id.like("alert-mine-%"),
        ~E.run_id.like("prom-mine-%"),
    )


def _outcome_counts():
    return tuple(func.sum(case((func.lower(E.outcome) == value, 1), else_=0)).label(label)
                 for value, label in (("pass", "passed"), ("fail", "failed"), ("warn", "warned")))


def _health(row):
    total = row.passed + row.failed + row.warned
    return total, round((row.passed + row.warned) / total * 100, 1) if total else 0


def _publish(db, model, records):
    # Call only after aggregation completes: do not hold summary-table write
    # locks while the database scans history. Flush bounded pending batches.
    db.query(model).delete()
    published_at = datetime.now(timezone.utc)
    for index, record in enumerate(records, 1):
        record.updated_at = published_at
        db.add(record)
        if index % 500 == 0:
            db.flush()
    db.commit()


@_single_writer(MVClusterSummary)
def refresh_clusters(db, now):
    lab = func.nullif(E.lab_code, "")
    counts = _window(
        db, now, E.cluster_name.label("cluster_name"), *_outcome_counts(),
        func.count(func.distinct(lab)).label("labs_seen"),
        func.count(func.distinct(case((func.lower(E.outcome) == "fail", lab)))).label("labs_failing"),
    ).filter(E.cluster_name.isnot(None)).group_by(E.cluster_name).subquery()
    failures = _window(
        db, now, E.cluster_name.label("cluster_name"), E.failure_class.label("failure_class"),
        func.count().label("failure_count"),
    ).filter(E.cluster_name.isnot(None), func.lower(E.outcome) == "fail",
             E.failure_class.isnot(None), E.failure_class != "").group_by(E.cluster_name, E.failure_class).subquery()
    # One statement gives counts and failure classes the same database snapshot.
    rows = db.query(counts, failures.c.failure_class, failures.c.failure_count).outerjoin(
        failures, counts.c.cluster_name == failures.c.cluster_name,
    ).all()
    records = {}
    for row in rows:
        if row.cluster_name not in records:
            total, health = _health(row)
            records[row.cluster_name] = MVClusterSummary(
                cluster_name=row.cluster_name, total_evaluations=total,
                passed=row.passed, failed=row.failed, warned=row.warned,
                health_rate=health, failure_classes={}, labs_seen=row.labs_seen,
                labs_failing=row.labs_failing,
            )
        if row.failure_class is not None:
            records[row.cluster_name].failure_classes[row.failure_class] = row.failure_count
    _publish(db, MVClusterSummary, records.values())


@_single_writer(MVPipelineStage)
def refresh_stages(db, now):
    rows = _window(db, now, E.stage_id, *_outcome_counts()).group_by(E.stage_id).all()
    def records():
        for row in rows:
            total, health = _health(row)
            yield MVPipelineStage(stage_id=row.stage_id, pass_count=row.passed,
                                  fail_count=row.failed, warn_count=row.warned,
                                  total=total, health_rate=health)
    _publish(db, MVPipelineStage, records())


@_single_writer(MVLabEvalSummary)
def refresh_labs(db, now):
    # Prior semantics merge NULL and empty cluster names for each lab.
    cluster = func.coalesce(E.cluster_name, "")
    counts = _window(
        db, now, E.lab_code.label("lab_code"), cluster.label("cluster_name"),
        *_outcome_counts(), func.max(E.evaluated_at).label("last_evaluated_at"),
    ).filter(E.lab_code.isnot(None)).group_by(E.lab_code, cluster).subquery()
    ranked = _window(
        db, now, E.lab_code.label("lab_code"), cluster.label("cluster_name"),
        E.failure_class.label("failure_class"),
        func.row_number().over(
            partition_by=(E.lab_code, cluster),
            # Previously equal-count ties followed unspecified row iteration.
            # Stabilize them by first evaluation ID, not event timestamp.
            order_by=(func.count().desc(), func.min(E.id)),
        ).label("rank"),
    ).filter(E.lab_code.isnot(None), func.lower(E.outcome) == "fail",
             E.failure_class.isnot(None), E.failure_class != "").group_by(
                 E.lab_code, cluster, E.failure_class,
             ).subquery()
    rows = db.query(counts, ranked.c.failure_class).outerjoin(
        ranked, and_(counts.c.lab_code == ranked.c.lab_code,
                     counts.c.cluster_name == ranked.c.cluster_name, ranked.c.rank == 1),
    ).all()
    def records():
        for row in rows:
            total, health = _health(row)
            yield MVLabEvalSummary(lab_code=row.lab_code, cluster_name=row.cluster_name or None,
                                   total_evals=total, passed=row.passed, failed=row.failed,
                                   warned=row.warned, top_failure_class=row.failure_class,
                                   health_rate=health, last_evaluated_at=row.last_evaluated_at)
    _publish(db, MVLabEvalSummary, records())
