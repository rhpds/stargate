"""Background work owns its session; failures must not retain transactions."""
import importlib
from unittest.mock import Mock

import pytest


class StopCycle(BaseException):
    """Stop legacy infinite loops without running real timers or work."""


class Shutdown:
    def __init__(self, stopped=False):
        self.stopped = stopped
        self.waits = []

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        self.waits.append(seconds)
        if seconds != 60:
            self.stopped = True
        return self.stopped


@pytest.fixture
def owned_session(monkeypatch):
    from db import database
    events = []
    session = Mock()
    session.close.side_effect = lambda: events.append("close")
    session.rollback.side_effect = lambda: events.append("rollback")
    factory = Mock(return_value=session)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    return session, factory, events


def test_successful_background_session_closes_without_implicit_commit(owned_session):
    from db.database import background_session
    session, factory, events = owned_session
    with background_session() as db:
        assert db is session
        assert events == []
        events.append("work")
    assert events == ["work", "close"]
    factory.assert_called_once_with()
    session.commit.assert_not_called()


@pytest.mark.parametrize("error", [RuntimeError("query failed"), StopCycle()])
def test_failed_or_cancelled_background_session_rolls_back_and_closes(owned_session, error):
    from db.database import background_session
    session, _, events = owned_session
    with pytest.raises(type(error)) as caught:
        with background_session():
            events.append("work")
            raise error
    assert caught.value is error
    assert events == ["work", "rollback", "close"]
    session.commit.assert_not_called()


def test_rollback_failure_still_closes_session(owned_session):
    from db.database import background_session
    session, _, _ = owned_session
    session.rollback.side_effect = RuntimeError("rollback failed")
    with pytest.raises(RuntimeError, match="rollback failed"):
        with background_session():
            raise ValueError("work failed")
    session.close.assert_called_once_with()


def test_session_factory_failure_propagates_without_retry(owned_session):
    from db.database import background_session
    session, factory, _ = owned_session
    factory.side_effect = RuntimeError("session unavailable")
    with pytest.raises(RuntimeError, match="session unavailable"):
        with background_session():
            pytest.fail("No session was created")
    factory.assert_called_once_with()
    session.close.assert_not_called()


def test_each_background_scope_owns_a_separate_session(monkeypatch):
    from db import database
    first, second = Mock(), Mock()
    factory = Mock(side_effect=[first, second])
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    with database.background_session() as outer:
        with database.background_session() as inner:
            assert outer is first and inner is second
            first.close.assert_not_called()
        second.close.assert_called_once_with()
    first.close.assert_called_once_with()


@pytest.mark.parametrize("worker", ["shadow", "corpus"])
@pytest.mark.parametrize("fails", [False, True])
def test_background_worker_cleans_up_before_next_wait(monkeypatch, owned_session, worker, fails):
    app = importlib.import_module("api.app")
    session, _, events = owned_session
    shutdown = Shutdown()
    monkeypatch.setattr(app, "_shutdown_event", shutdown)

    def sleep(seconds):
        if seconds != 60:
            raise StopCycle()
    monkeypatch.setattr("time.sleep", sleep)

    def work(*args, **kwargs):
        assert events == [], "Session must remain owned until work ends"
        events.append("work")
        if fails:
            raise RuntimeError("synthetic cycle failure")
        return {"total_findings": 0, "by_source": {}, "total_failure_classes": 0}

    if worker == "shadow":
        monkeypatch.setattr("engine.historical_miner.run_shadow_cycle", work)
        monkeypatch.setattr(app, "_auto_resolve_incidents", lambda db: None)
        monkeypatch.setattr(app, "_record_gap_detections", lambda db: None)
        run = app._shadow_mode_loop
    else:
        monkeypatch.setattr("engine.corpus_runner.run_all_miners", work)
        run = app._corpus_mining_loop
    try:
        run()
    except StopCycle:
        pass
    assert events == (["work", "rollback", "close"] if fails else ["work", "close"])
    assert shutdown.waits == [60, 300 if worker == "shadow" else 1800]
    session.commit.assert_not_called()


@pytest.mark.parametrize("worker", ["shadow", "corpus"])
def test_background_worker_shutdown_skips_work(monkeypatch, owned_session, worker):
    app = importlib.import_module("api.app")
    _, factory, _ = owned_session
    monkeypatch.setattr(app, "_shutdown_event", Shutdown(stopped=True))
    monkeypatch.setattr("time.sleep", lambda seconds: (_ for _ in ()).throw(StopCycle()))
    try:
        getattr(app, "_shadow_mode_loop" if worker == "shadow" else "_corpus_mining_loop")()
    except StopCycle:
        pytest.fail("Shutdown must use an interruptible wait, not sleep")
    factory.assert_not_called()


@pytest.mark.parametrize("fails", [False, True])
def test_summit_cache_warm_owns_session_on_success_and_failure(monkeypatch, owned_session, fails):
    app = importlib.import_module("api.app")
    monkeypatch.setattr("api.routers._shared._aap_cache", {"data": {}, "ts": 0}, raising=False)
    _, _, events = owned_session
    for name in ("_fetch_labagator_labs", "_fetch_labagator_sessions", "_fetch_demolition_sessions"):
        monkeypatch.setattr("api.routers._shared." + name, lambda: {})
    monkeypatch.setattr("collectors.aap.collect_aap.collect_aap_jobs", lambda: {})
    monkeypatch.setattr("engine.functional_alignment.gate_enabled", lambda name: False)

    def summit(**kwargs):
        assert events == []
        assert kwargs["include_all"] is False
        events.append("work")
        if fails:
            raise RuntimeError("synthetic cache failure")
    monkeypatch.setattr("api.routers.dashboard.dashboard_summit", summit)
    app._warm_caches()
    assert events == (["work", "rollback", "close"] if fails else ["work", "close"])


@pytest.mark.parametrize("fails", [False, True])
def test_aap_cache_warm_cleans_up_ingestion_session(monkeypatch, owned_session, fails):
    app = importlib.import_module("api.app")
    monkeypatch.setattr("api.routers._shared._aap_cache", {"data": {}, "ts": 0}, raising=False)
    _, _, events = owned_session
    for name in ("_fetch_labagator_labs", "_fetch_labagator_sessions", "_fetch_demolition_sessions"):
        monkeypatch.setattr("api.routers._shared." + name, lambda: {})
    monkeypatch.setattr("collectors.aap.collect_aap.collect_aap_jobs", lambda: {})
    monkeypatch.setattr("engine.functional_alignment.gate_enabled", lambda name: True)
    monkeypatch.setattr("engine.functional_alignment.ingest_aap_collection_status", lambda *args: None)
    monkeypatch.setattr("api.routers.dashboard.dashboard_summit", lambda **kwargs: None)

    def ingest(*args):
        assert events == []
        events.append("work")
        if fails:
            raise RuntimeError("synthetic ingestion failure")
    monkeypatch.setattr("engine.functional_alignment.ingest_aap_failures", ingest)
    app._warm_caches()
    # Cache warming continues with a separate owned scope after AAP succeeds or fails.
    assert events == (["work", "rollback", "close", "close"] if fails else ["work", "close", "close"])


@pytest.mark.parametrize("stage", ["_auto_resolve_incidents", "_record_gap_detections"])
def test_shadow_later_stage_failure_also_releases_session(monkeypatch, owned_session, stage):
    app = importlib.import_module("api.app")
    _, _, events = owned_session
    monkeypatch.setattr(app, "_shutdown_event", Shutdown())
    monkeypatch.setattr("engine.historical_miner.run_shadow_cycle", lambda *args, **kwargs: None)
    monkeypatch.setattr(app, "_auto_resolve_incidents", lambda db: None)
    monkeypatch.setattr(app, "_record_gap_detections", lambda db: None)

    def fail(db):
        events.append("later_stage")
        raise RuntimeError("synthetic later-stage failure")
    monkeypatch.setattr(app, stage, fail)
    app._shadow_mode_loop()
    assert events == ["later_stage", "rollback", "close"]


@pytest.mark.parametrize("worker", ["shadow", "corpus"])
def test_shutdown_during_cycle_still_closes_session(monkeypatch, owned_session, worker):
    app = importlib.import_module("api.app")
    _, factory, events = owned_session
    shutdown = Shutdown()
    monkeypatch.setattr(app, "_shutdown_event", shutdown)

    def stop(*args, **kwargs):
        events.append("work")
        shutdown.stopped = True
        return {"total_findings": 0, "by_source": {}, "total_failure_classes": 0}
    if worker == "shadow":
        monkeypatch.setattr("engine.historical_miner.run_shadow_cycle", stop)
        monkeypatch.setattr(app, "_auto_resolve_incidents", lambda db: None)
        monkeypatch.setattr(app, "_record_gap_detections", lambda db: None)
        app._shadow_mode_loop()
    else:
        monkeypatch.setattr("engine.corpus_runner.run_all_miners", stop)
        app._corpus_mining_loop()
    assert events == ["work", "close"]
    factory.assert_called_once_with()


@pytest.mark.parametrize("outcome", ["error", "uncommitted", "committed"])
def test_real_sqlite_transaction_is_rolled_back_unless_explicitly_committed(monkeypatch, outcome):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from db import database

    engine = create_engine("sqlite://")
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "get_session_factory", lambda: factory)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE cleanup_probe (id INTEGER PRIMARY KEY)"))

        def work():
            with database.background_session() as session:
                session.execute(text("INSERT INTO cleanup_probe (id) VALUES (1)"))
                if outcome == "error":
                    raise RuntimeError("synthetic transaction failure")
                if outcome == "committed":
                    session.commit()

        if outcome == "error":
            with pytest.raises(RuntimeError, match="synthetic transaction failure"):
                work()
        else:
            work()
        # A fresh scope can read immediately, with no transaction left behind.
        with database.background_session() as session:
            count = session.execute(text("SELECT count(*) FROM cleanup_probe")).scalar()
            assert count == (1 if outcome == "committed" else 0)
    finally:
        engine.dispose()
