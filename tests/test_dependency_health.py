"""Tests for external dependency health monitoring (collectors/dependency_health.py).

Network mocked. The probe semantics are chosen for the documented Oct 14/21
2026 incidents: sso.redhat.com / api.openshift.com returned 5xx and crashed
the Assisted Installer integration (546+ provision failures on Oct 14).
"""

from unittest.mock import patch

import pytest
from sqlalchemy import text

from collectors.dependency_health import (
    _probe,
    _targets,
    probe_dependencies,
    record_probe_evaluations,
    run_health_check,
)
from tests.conftest import TestSession, test_engine


def _urlopen_result(status=None, error=None, elapsed=0.5):
    """Build a fake probe outcome by patching _probe's HTTP layer."""


def test_probe_pass_on_2xx_3xx_4xx():
    """A 4xx on a base URL is normal — the service answered."""
    class FakeResp:
        status = 403
        def read(self, n): return b""
        def __enter__(self): return self
        def __exit__(self, *a): return False

    with patch("collectors.dependency_health.urllib.request.urlopen", return_value=FakeResp()):
        r = _probe({"name": "sso", "url": "https://sso.example.com/"})
    assert r["outcome"] == "pass"
    assert r["failure_class"] is None


def test_probe_fail_on_5xx():
    """5xx is the Oct-21 signature — the provision-breaking case."""
    import urllib.error

    err = urllib.error.HTTPError("url", 503, "Service Unavailable", {}, None)
    with patch("collectors.dependency_health.urllib.request.urlopen", side_effect=err):
        r = _probe({"name": "sso", "url": "https://sso.example.com/"})
    assert r["outcome"] == "fail"
    assert r["failure_class"] == "external_dependency_5xx"
    assert "Oct-21" in r["message"] or "503" in r["message"]


def test_probe_fail_on_unreachable():
    """Timeouts/DNS failures are unreachable, a distinct failure class."""
    import urllib.error

    with patch(
        "collectors.dependency_health.urllib.request.urlopen",
        side_effect=urllib.error.URLError("timed out"),
    ):
        r = _probe({"name": "sso", "url": "https://sso.example.com/"})
    assert r["outcome"] == "fail"
    assert r["failure_class"] == "external_dependency_unreachable"


def test_probe_warn_on_slow():
    """Slow-but-up dependencies warn rather than fail."""
    class FakeResp:
        status = 200
        def read(self, n): return b""
        def __enter__(self): return self
        def __exit__(self, *a): return False

    with patch("collectors.dependency_health.urllib.request.urlopen", return_value=FakeResp()):
        with patch("collectors.dependency_health.time.monotonic",
                   side_effect=[0.0, 12.0]):  # 12s elapsed
            r = _probe({"name": "sso", "url": "https://sso.example.com/"})
    assert r["outcome"] == "warn"
    assert r["failure_class"] == "external_dependency_slow"


def test_targets_default_and_override(monkeypatch):
    # defaults cover the documented incident dependencies
    assert {t["name"] for t in _targets()} >= {"sso.redhat.com", "api.openshift.com"}
    # explicit config replaces defaults
    monkeypatch.setenv("STARGATE_DEPENDENCY_HEALTH_TARGETS",
                       '[{"name": "custom", "url": "https://custom.example.com/"}]')
    assert _targets() == [{"name": "custom", "url": "https://custom.example.com/"}]
    # explicit empty list disables probing (the loop guard)
    monkeypatch.setenv("STARGATE_DEPENDENCY_HEALTH_TARGETS", "[]")
    assert _targets() == []


def test_run_health_check_records_and_emits(monkeypatch):
    """The shared pipeline records evaluations and emits
    external_dependency_degraded events with the 'do not chase downstream
    symptoms' remediation."""
    from api.routers._shared import _event_bus
    _event_bus.history.clear()

    fake_report = {
        "dependencies_probed": 2, "passing": 1, "warned": 0, "failing": 1,
        "failing_dependencies": ["sso.redhat.com"], "slow_dependencies": [],
        "results": [
            {"dependency": "sso.redhat.com", "url": "https://sso.redhat.com/",
             "outcome": "fail", "failure_class": "external_dependency_5xx",
             "http_status": 503, "latency_seconds": 0.4,
             "message": "HTTP 503 — the Oct-21 signature", "error": None,
             "probed_at": "2026-11-02T05:00:00+00:00"},
            {"dependency": "api.openshift.com", "url": "https://api.openshift.com/",
             "outcome": "pass", "failure_class": None, "http_status": 200,
             "latency_seconds": 0.5, "message": "HTTP 200 in 0.5s", "error": None,
             "probed_at": "2026-11-02T05:00:00+00:00"},
        ],
        "probed_at": "2026-11-02T05:00:00+00:00",
    }
    monkeypatch.setattr("collectors.dependency_health.probe_dependencies",
                        lambda force=False: fake_report)

    from db.database import Base
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()
    try:
        report = run_health_check(db, force=True)
    finally:
        db.rollback()
        db.close()

    assert report["evaluations_recorded"] == 2
    events = [e for e in _event_bus.history if e.event_type == "external_dependency_degraded"]
    assert len(events) == 1
    e = events[0]
    assert e.cluster_name == "sso.redhat.com"
    assert e.priority == 8.0  # 5xx is the incident-grade priority
    assert "Do NOT chase downstream" in e.metadata["remediation"]
    _event_bus.history.clear()


def test_dashboard_dependency_health_endpoint(client, monkeypatch):
    fake = {
        "dependencies_probed": 3, "passing": 3, "warned": 0, "failing": 0,
        "failing_dependencies": [], "slow_dependencies": [], "results": [],
        "probed_at": "2026-11-02T05:00:00+00:00",
    }
    monkeypatch.setattr("collectors.dependency_health.run_health_check",
                        lambda db, force=False: {**fake, "evaluations_recorded": 0})
    resp = client.get("/dashboard/dependency-health")
    assert resp.status_code == 200
    assert resp.json()["dependencies_probed"] == 3
