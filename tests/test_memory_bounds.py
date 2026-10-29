"""Memory regressions: bounded catalog retention and reusable TLS trust stores."""
from concurrent.futures import ThreadPoolExecutor


def test_aap_tls_context_is_shared_across_threads_and_respects_verification(monkeypatch):
    from collectors.aap import collect_aap as collector

    calls = []
    original = collector.ssl.create_default_context

    def create():
        calls.append(True)
        return original()

    monkeypatch.setattr(collector.ssl, "create_default_context", create)
    monkeypatch.setattr(collector, "_ssl_contexts", {})
    monkeypatch.setenv("STARGATE_SSL_VERIFY", "true")
    with ThreadPoolExecutor(max_workers=8) as pool:
        contexts = list(pool.map(lambda _: collector._make_ssl_ctx(), range(2000)))
    assert len(calls) == 1
    assert all(ctx is contexts[0] for ctx in contexts)
    monkeypatch.setenv("STARGATE_SSL_VERIFY", "false")
    insecure = collector._make_ssl_ctx()
    assert insecure is not contexts[0]
    assert not insecure.check_hostname
    monkeypatch.setenv("STARGATE_SSL_VERIFY", "true")
    assert collector._make_ssl_ctx() is contexts[0]
    assert len(calls) == 2


def test_constraints_cache_bounds_and_independent_expiry(monkeypatch):
    from api.routers import _shared as shared
    from collections import OrderedDict

    monkeypatch.setattr(shared, "_constraints_cache", OrderedDict())
    monkeypatch.setattr(shared, "_CONSTRAINTS_CACHE_MAX_ENTRIES", 3)
    clock = [1000.0]
    monkeypatch.setattr(shared.time, "monotonic", lambda: clock[0])
    shared._cache_constraints(("old", "catalog.a"), {"version": 1})
    clock[0] += shared._CONSTRAINTS_CACHE_TTL - 1
    shared._cache_constraints(("new", "catalog.a"), {"version": 2})
    clock[0] += 2
    assert shared._cached_constraints(("old", "catalog.a")) is None
    assert shared._cached_constraints(("new", "catalog.a")) == {"version": 2}
    assert shared._cached_constraints(("new", "catalog.b")) is None
    for n in range(1000):
        shared._cache_constraints((str(n), "catalog.a"), {"value": n})
    assert len(shared._constraints_cache) == 3
    assert shared._cached_constraints(("999", "catalog.a")) == {"value": 999}


def test_memory_diagnostics_disabled_by_default(monkeypatch):
    from engine import memory_diagnostics as diagnostics
    monkeypatch.delenv("STARGATE_MEMORY_DIAGNOSTICS", raising=False)
    monkeypatch.setattr(diagnostics.tracemalloc, "start", lambda *a: (_ for _ in ()).throw(AssertionError()))
    diagnostics.start_memory_diagnostics(None)


def test_memory_diagnostics_recovers_logger_disabled_by_migrations(monkeypatch):
    import threading
    from engine import memory_diagnostics as diagnostics
    monkeypatch.setenv("STARGATE_MEMORY_DIAGNOSTICS", "true")
    monkeypatch.setattr(diagnostics.logger, "disabled", True)
    monkeypatch.setattr(diagnostics.tracemalloc, "is_tracing", lambda: True)
    stopped = threading.Event()
    stopped.set()
    diagnostics.start_memory_diagnostics(stopped)
    assert diagnostics.logger.disabled is False


def test_memory_sample_reports_only_counters_below_threshold(monkeypatch, caplog):
    from engine import memory_diagnostics as diagnostics
    monkeypatch.setattr(diagnostics.logger, "disabled", False)
    monkeypatch.setattr(diagnostics, "resident_bytes", lambda: 100)
    monkeypatch.setattr(diagnostics.tracemalloc, "get_traced_memory", lambda: (10, 20))
    monkeypatch.setattr(diagnostics.tracemalloc, "take_snapshot", lambda: (_ for _ in ()).throw(AssertionError()))
    with caplog.at_level("INFO", logger="stargate.memory"):
        diagnostics.log_memory_sample()
    assert "rss_bytes=100 python_bytes=10 python_peak_bytes=20" in caplog.text


def test_aap_responses_closed_on_decode_failure(monkeypatch):
    import pytest
    from collectors.aap import collect_aap as collector

    class Response:
        closed = False

        def read(self):
            return b"not-json"

        def close(self):
            self.closed = True

    responses = []

    def open_response(*args, **kwargs):
        response = Response()
        responses.append(response)
        return response

    monkeypatch.setattr(collector.urllib.request, "urlopen", open_response)
    controller = {"url": "https://aap.example", "token": "test"}
    with pytest.raises(ValueError):
        collector._fetch_jobs(controller, "page_size=200")
    assert collector._fetch_job_events(controller, 1) == []
    collector._fetch_job_counts(controller, "2026-01-01T00:00:00")
    assert len(responses) >= 6
    assert all(response.closed for response in responses)
