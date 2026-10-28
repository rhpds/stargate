"""Operations performance contracts: shared baselines and indexed time filters."""
import importlib.util
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock


def test_targeted_history_lookups_preserve_all_time_and_latest_id_semantics(db):
    from db.evaluation_queries import first_observed_by_lab, latest_evaluations_by_pair
    from db.models import EvaluationRecord
    now = datetime.now(timezone.utc)
    for ns, fc, at, outcome in [
        ("pilot-a", "storage", now - timedelta(days=30), "fail"),
        ("pilot-a", "storage", now, "pass"),
        # A late-arriving older event still has the latest ID (existing semantics).
        ("pilot-a", "storage", now - timedelta(hours=2), "fail"),
        ("pilot-a", "pods", now, "pass"),
        ("pilot-b", "storage", now, "fail"),
    ]:
        db.add(EvaluationRecord(run_id="history", stage_id="test", lab_code=ns,
                                failure_class=fc, evaluated_at=at, outcome=outcome))
    db.commit()
    latest = latest_evaluations_by_pair(db, {("pilot-a", "storage"), ("pilot-a", "missing")})
    assert set(latest) == {("pilot-a", "storage")}
    assert latest[("pilot-a", "storage")].outcome == "fail"
    first = first_observed_by_lab(db, {"pilot-a", "missing"})
    assert first["pilot-a"].replace(tzinfo=timezone.utc) == now - timedelta(days=30)
    assert first["missing"] is None
    assert latest_evaluations_by_pair(db, set()) == {}
    assert first_observed_by_lab(db, set()) == {}


def test_targeted_history_index_migration_roundtrip():
    from sqlalchemy import create_engine, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path("alembic/versions/h8c9d0e1f2a3_evaluation_history_indexes.py")
    spec = importlib.util.spec_from_file_location("history_indexes", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        conn.exec_driver_sql("CREATE TABLE evaluations (id INTEGER PRIMARY KEY, lab_code TEXT, failure_class TEXT, evaluated_at DATETIME)")
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            migration.upgrade()
            indexes = {i["name"]: i["column_names"] for i in inspect(conn).get_indexes("evaluations")}
            assert indexes["idx_eval_lab_first_seen"] == ["lab_code", "evaluated_at"]
            assert indexes["idx_eval_lab_failure_latest"] == ["lab_code", "failure_class", "id"]
            migration.downgrade()
            assert not inspect(conn).get_indexes("evaluations")
    engine.dispose()


def test_targeted_postgres_indexes_are_concurrent_and_validate_existing(monkeypatch):
    import pytest
    path = Path("alembic/versions/h8c9d0e1f2a3_evaluation_history_indexes.py")
    spec = importlib.util.spec_from_file_location("history_concurrent", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    operation = MagicMock()
    operation.get_bind.return_value.dialect.name = "postgresql"
    operation.get_bind.return_value.execute.return_value.mappings.return_value.first.return_value = None
    monkeypatch.setattr(migration, "op", operation)
    migration.upgrade()
    assert operation.get_context.return_value.autocommit_block.call_count == 2
    assert operation.create_index.call_count == 2
    for call in operation.create_index.call_args_list:
        assert call.kwargs == {"schema": "public", "postgresql_concurrently": True, "if_not_exists": True}
    operation.create_index.reset_mock()
    operation.get_bind.return_value.execute.return_value.mappings.return_value.first.return_value = {
        "indisvalid": True, "indisready": True,
        "definition": "CREATE INDEX idx_eval_lab_first_seen ON public.evaluations USING btree (lab_code, evaluated_at) WHERE lab_code IS NOT NULL"}
    with pytest.raises(RuntimeError, match="invalid or mismatched"):
        migration.upgrade()
    operation.create_index.assert_not_called()


def test_concurrent_baseline_requests_build_once(monkeypatch):
    from engine import attention_classifier as attention
    monkeypatch.setattr(attention, "_baseline_cache", None)
    monkeypatch.setattr(attention, "_baseline_cache_at", None)
    calls = []
    barrier = threading.Barrier(8)

    def build(db):
        calls.append(True)
        time.sleep(0.02)
        return {"sample": {"total_evals": 12}}

    monkeypatch.setattr(attention, "build_catalog_baselines", build)

    def request(_):
        barrier.wait(timeout=3)
        return attention.get_cached_baselines(None)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(request, range(8)))
    assert len(calls) == 1
    assert all(value is results[0] for value in results)


def test_expired_baseline_refresh_failure_preserves_prior_value(monkeypatch):
    from engine import attention_classifier as attention
    old = {"existing": {"total_evals": 5}}
    monkeypatch.setattr(attention, "_baseline_cache", old)
    monkeypatch.setattr(attention, "_baseline_cache_at", datetime.now(timezone.utc) - timedelta(hours=2))
    def failed(db):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(attention, "build_catalog_baselines", failed)
    import pytest
    with pytest.raises(RuntimeError):
        attention.get_cached_baselines(None)
    assert attention._baseline_cache is old  # Do not replace failure with false healthy data.


def test_lifecycle_and_strategies_use_shared_cache(db, monkeypatch):
    from api.routers.admin import monitoring
    calls = []
    monkeypatch.delenv("STARGATE_LABAGATOR_URL", raising=False)
    monkeypatch.setattr(monitoring, "get_cached_baselines", lambda db: calls.append(True) or {})
    assert "summary" in monitoring.lifecycle_matrix(db=db)
    monitoring._build_remediation_strategies(db)
    assert len(calls) == 2


def test_lifecycle_never_fetches_optional_display_titles(db, monkeypatch):
    import urllib.request
    from api.routers.admin import monitoring
    from api.routers import _shared
    monkeypatch.setenv("STARGATE_LABAGATOR_URL", "https://metadata.example.test")
    monkeypatch.setattr(monitoring, "get_cached_baselines", lambda db: {})
    monkeypatch.setattr(_shared, "_labagator_cache", {"labs": [{"ci_name": "catalog.pilot-app", "title": "Pilot Application"}], "ts": 0})
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Display titles must not block a page request on external HTTP")
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    assert "summary" in monitoring.lifecycle_matrix(db=db)
    assert not calls


def test_investigation_list_queries_are_batched_and_statuses_preserved(db, monkeypatch):
    from sqlalchemy import event
    from db.models import InvestigationRecord, EvaluationRecord
    from api.routers.dashboard.remediation import dashboard_investigations_list
    from engine import attention_classifier
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(attention_classifier, "get_cached_baselines", lambda db: {})
    for i in range(30):
        ns = f"sandbox-test-{i}-pilot"
        db.add(InvestigationRecord(job_id=f"test-job-{i}", lab_code=ns, cluster="infra01",
                                   failure_class="readiness_probe_failed", trigger_type="manual",
                                   status="complete", created_at=now))
        db.add(EvaluationRecord(run_id=f"test-run-{i}", stage_id="pods", lab_code=ns,
                                cluster_name="infra01", outcome="pass" if i == 0 else "fail",
                                failure_class="readiness_probe_failed", evaluated_at=now if i != 1 else now-timedelta(hours=2)))
    db.commit()
    queries = []
    def count(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)
    event.listen(db.get_bind(), "before_cursor_execute", count)
    try:
        result = dashboard_investigations_list(db=db, limit=100)
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", count)
    assert len(queries) <= 5
    by_job = {r["job_id"]: r for r in result}
    assert by_job["test-job-0"]["current_status"] == "resolved"
    assert by_job["test-job-1"]["current_status"] == "stale"
    assert by_job["test-job-2"]["current_status"] == "active"


def test_evaluation_time_index_in_metadata_and_migration_sqlite_roundtrip():
    from sqlalchemy import create_engine, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from db.database import Base
    from db.models import EvaluationRecord
    assert any([col.name for col in index.columns] == ["evaluated_at"] for index in EvaluationRecord.__table__.indexes)
    path = Path("alembic/versions/g7b8c9d0e1f2_evaluation_time_index.py")
    spec = importlib.util.spec_from_file_location("time_index_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        conn.exec_driver_sql("CREATE TABLE evaluations (id INTEGER PRIMARY KEY, evaluated_at DATETIME NOT NULL)")
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            migration.upgrade()  # An existing valid index is reusable.
            assert "idx_eval_evaluated_at" in {i["name"] for i in inspect(conn).get_indexes("evaluations")}
            migration.downgrade()
            assert "idx_eval_evaluated_at" not in {i["name"] for i in inspect(conn).get_indexes("evaluations")}
    engine.dispose()


def test_postgres_migration_uses_concurrent_autocommit_and_refuses_invalid_index(monkeypatch):
    import pytest
    path = Path("alembic/versions/g7b8c9d0e1f2_evaluation_time_index.py")
    spec = importlib.util.spec_from_file_location("concurrent_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    operation = MagicMock()
    operation.get_bind.return_value.dialect.name = "postgresql"
    operation.get_bind.return_value.execute.return_value.mappings.return_value.first.return_value = None
    monkeypatch.setattr(migration, "op", operation)
    migration.upgrade()
    operation.get_context.return_value.autocommit_block.assert_called_once()
    operation.create_index.assert_called_once_with("idx_eval_evaluated_at", "evaluations", ["evaluated_at"],
                                                   schema="public", postgresql_concurrently=True, if_not_exists=True)
    operation.create_index.reset_mock()
    operation.get_bind.return_value.execute.return_value.mappings.return_value.first.return_value = {
        "indisvalid": False, "indisready": False, "definition": "CREATE INDEX invalid"}
    with pytest.raises(RuntimeError, match="invalid or mismatched"):
        migration.upgrade()
    operation.create_index.assert_not_called()
