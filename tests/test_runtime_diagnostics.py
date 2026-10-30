"""Opt-in stage diagnostics must be bounded, payload-free, and fail-open."""
import importlib
from contextlib import contextmanager

import pytest


def diagnostics():
    return importlib.import_module("engine.runtime_diagnostics")


def test_disabled_stage_does_not_sample_or_log(monkeypatch):
    module = diagnostics()
    monkeypatch.delenv("STARGATE_RUNTIME_TIMING", raising=False)
    monkeypatch.setattr(module, "_sample", lambda: pytest.fail("Disabled diagnostics sampled"))
    monkeypatch.setattr(module.logger, "info", lambda *args: pytest.fail("Disabled diagnostics logged"))
    with module.diagnostic_stage("startup.database"):
        pass


@pytest.mark.parametrize("setting", ["false", "", "yes", "1"])
def test_non_true_settings_do_not_enable_diagnostics(monkeypatch, setting):
    module = diagnostics()
    monkeypatch.setenv("STARGATE_RUNTIME_TIMING", setting)
    monkeypatch.setattr(module, "_sample", lambda: pytest.fail("Unexpected diagnostic sampling"))
    with module.diagnostic_stage("startup.database"):
        pass


def test_stage_logs_start_end_wall_thread_cpu_and_rss(monkeypatch, caplog):
    module = diagnostics()
    monkeypatch.setenv("STARGATE_RUNTIME_TIMING", "TRUE")
    readings = iter([(10.0, 2.0, 100), (10.5, 2.125, 200)])
    monkeypatch.setattr(module, "_sample", lambda: next(readings))
    with caplog.at_level("INFO", logger=module.logger.name):
        with module.diagnostic_stage("refresh.clusters"):
            pass
    records = [r for r in caplog.records if r.name == module.logger.name]
    assert len(records) == 2
    assert "phase=begin stage=refresh.clusters" in records[0].getMessage()
    message = records[1].getMessage()
    for field in ("phase=end", "stage=refresh.clusters", "status=ok", "wall_ms=500.000", "thread_cpu_ms=125.000", "rss_before_bytes=100", "rss_after_bytes=200"):
        assert field in message


@pytest.mark.parametrize("error", [RuntimeError("credential-like-sensitive-evidence"), KeyboardInterrupt()])
def test_failure_is_reraised_without_logging_exception_or_payload(monkeypatch, caplog, error):
    module = diagnostics()
    monkeypatch.setenv("STARGATE_RUNTIME_TIMING", "true")
    with caplog.at_level("INFO", logger=module.logger.name), pytest.raises(type(error)) as caught:
        with module.diagnostic_stage("warm.summit"):
            raise error
    assert caught.value is error
    assert "status=error" in caplog.text
    assert "credential-like-sensitive-evidence" not in caplog.text
    assert all(r.exc_info is None for r in caplog.records if r.name == module.logger.name)


def test_unknown_stage_cannot_log_user_supplied_text(monkeypatch, caplog):
    module = diagnostics()
    monkeypatch.setenv("STARGATE_RUNTIME_TIMING", "true")
    with caplog.at_level("INFO", logger=module.logger.name):
        with module.diagnostic_stage("secret-token-and-namespace"):
            pass
    assert "stage=other" in caplog.text
    assert "secret-token-and-namespace" not in caplog.text


@pytest.mark.parametrize("fault", ["sample", "logger"])
def test_diagnostic_fault_does_not_change_application_outcome(monkeypatch, fault):
    module = diagnostics()
    monkeypatch.setenv("STARGATE_RUNTIME_TIMING", "true")

    def fail(*args, **kwargs):
        raise RuntimeError("diagnostic failure")
    monkeypatch.setattr(module if fault == "sample" else module.logger, "_sample" if fault == "sample" else "info", fail)
    with module.diagnostic_stage("warm.summit"):
        pass
    error = ValueError("original application failure")
    with pytest.raises(ValueError) as caught:
        with module.diagnostic_stage("warm.summit"):
            raise error
    assert caught.value is error


def test_diagnostics_do_not_start_allocation_tracing(monkeypatch):
    module = diagnostics()
    import tracemalloc
    monkeypatch.setenv("STARGATE_RUNTIME_TIMING", "true")
    monkeypatch.setattr(tracemalloc, "start", lambda *args: pytest.fail("Tracing started"))
    monkeypatch.setattr(tracemalloc, "take_snapshot", lambda: pytest.fail("Snapshot taken"))
    with module.diagnostic_stage("warm.summit"):
        pass


def test_logging_survives_migration_logger_disablement(monkeypatch, caplog):
    module = diagnostics()
    monkeypatch.setenv("STARGATE_RUNTIME_TIMING", "true")
    monkeypatch.setattr(module.logger, "disabled", True)
    with caplog.at_level("INFO", logger=module.logger.name):
        with module.diagnostic_stage("startup.database"):
            pass
    assert "phase=end stage=startup.database" in caplog.text


def test_startup_has_stage_boundaries_without_starting_threads(monkeypatch):
    app = importlib.import_module("api.app")
    events = []

    @contextmanager
    def stage(name):
        events.append(("begin", name))
        yield
        events.append(("end", name))
    monkeypatch.setattr(app, "diagnostic_stage", stage)
    for attr, label in (("init_db", "startup.database"), ("_clone_agnosticv", "startup.catalog"), ("_register_event_consumers", "startup.consumers")):
        monkeypatch.setattr(app, attr, lambda label=label: events.append(("work", label)))
    monkeypatch.setattr("engine.memory_diagnostics.start_memory_diagnostics", lambda event: None)
    monkeypatch.setattr("threading.Thread.start", lambda thread: None)
    app.on_startup()
    for label in ("startup.database", "startup.catalog", "startup.consumers"):
        index = events.index(("work", label))
        assert events[index-1:index+2] == [("begin", label), ("work", label), ("end", label)]


@pytest.mark.parametrize("fails", [False, True])
def test_warm_cache_stage_markers_cover_owned_sessions(monkeypatch, caplog, fails):
    app = importlib.import_module("api.app")
    module = diagnostics()
    monkeypatch.setenv("STARGATE_RUNTIME_TIMING", "true")
    monkeypatch.setattr("api.routers._shared._aap_cache", {"data": {}, "ts": 0}, raising=False)
    for name in ("_fetch_labagator_labs", "_fetch_labagator_sessions", "_fetch_demolition_sessions"):
        monkeypatch.setattr("api.routers._shared." + name, lambda: {})
    monkeypatch.setattr("collectors.aap.collect_aap.collect_aap_jobs", lambda: {})
    monkeypatch.setattr("engine.functional_alignment.gate_enabled", lambda name: True)
    monkeypatch.setattr("engine.functional_alignment.ingest_aap_failures", lambda *args: None)
    monkeypatch.setattr("engine.functional_alignment.ingest_aap_collection_status", lambda *args: None)

    def summit(**kwargs):
        if fails:
            raise RuntimeError("synthetic cache failure")
    monkeypatch.setattr("api.routers.dashboard.dashboard_summit", summit)
    with caplog.at_level("INFO", logger=module.logger.name):
        app._warm_caches()
    messages = [r.getMessage() for r in caplog.records if r.name == module.logger.name]
    assert len(messages) == 8
    for label in ("warm.inventory", "warm.aap_collection", "warm.aap_ingestion", "warm.summit"):
        assert any("phase=begin stage=" + label in message for message in messages)
        status = "error" if fails and label == "warm.summit" else "ok"
        assert any("phase=end stage=" + label + " status=" + status in message for message in messages)


@pytest.mark.parametrize("failed_index", [0, 1, 2])
def test_refresh_markers_identify_failed_step_without_changing_cleanup(monkeypatch, caplog, failed_index):
    import threading
    from unittest.mock import Mock
    app = importlib.import_module("api.app")
    module = diagnostics()
    monkeypatch.setenv("STARGATE_RUNTIME_TIMING", "true")
    shutdown = threading.Event()
    monkeypatch.setattr(shutdown, "wait", lambda seconds: shutdown.set() or True)
    monkeypatch.setattr(app, "_shutdown_event", shutdown)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    session = Mock()
    monkeypatch.setattr("db.database.get_session_factory", lambda: lambda: session)
    names = ("refresh_cluster_summary", "refresh_pipeline_stages", "refresh_lab_eval_summary")
    labels = ("refresh.clusters", "refresh.pipeline", "refresh.labs")

    def refresh(db, index):
        assert db is session
        if index == failed_index:
            raise RuntimeError("synthetic refresh failure")
    for index, name in enumerate(names):
        monkeypatch.setattr(app.repository, name, lambda db, index=index: refresh(db, index))
    monkeypatch.setattr("api.routers._shared._load_latest_scan", lambda: [])
    monkeypatch.setattr(app, "_cleanup_scan_history", lambda: None)
    with caplog.at_level("INFO", logger=module.logger.name):
        app._mv_refresh_loop()
    messages = [r.getMessage() for r in caplog.records if r.name == module.logger.name]
    assert len(messages) == (failed_index + 1) * 2
    assert any("phase=end stage=" + labels[failed_index] + " status=error" in message for message in messages)
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()
