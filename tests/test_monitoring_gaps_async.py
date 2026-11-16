"""Tests for the async monitoring-gaps endpoint.

The detectors run synchronous `oc` calls against remote clusters and can
take >120s — longer than any HTTP client waits (found live Nov 16 2026:
the Reclamation page's verdict could never resolve). The endpoint therefore
NEVER runs detectors inline: it serves the last completed scan (fresh or
stale, with its age) and refreshes in a background thread.
"""

import time

import pytest


@pytest.fixture(autouse=True)
def _cold_cache():
    from api.routers.admin import proof
    proof._reset_gaps_cache_for_tests()
    yield
    proof._reset_gaps_cache_for_tests()


def _install_detectors(monkeypatch, results=None, delay=0.0):
    """Point the background work at a controlled fake."""
    from api.routers.admin import proof
    calls = {"n": 0}

    def fake_run():
        calls["n"] += 1
        if delay:
            time.sleep(delay)
        return results if results is not None else {
            "stuck_teardowns": {"stuck": [], "stuck_count": 0},
            "resource_leaks": {"orphaned_pvs": [], "orphaned_count": 0},
            "operator_health": {"healthy": True},
        }

    monkeypatch.setattr(proof, "_run_gap_detectors", fake_run)
    return calls


class TestMonitoringGapsAsync:
    def test_first_call_is_scanning_not_blocking(self, monkeypatch):
        """Cold start: the endpoint returns immediately with status=scanning
        while the detectors run in the background — it must NOT block."""
        from api.routers.admin import proof
        calls = _install_detectors(monkeypatch, delay=5.0)

        start = time.monotonic()
        result = proof.detect_monitoring_gaps()
        elapsed = time.monotonic() - start

        assert elapsed < 1.0, "endpoint blocked on detectors"
        assert result["status"] == "scanning"
        assert "stuck_teardowns" not in result  # no data yet, honestly
        assert "message" in result

    def test_result_lands_after_background_scan(self, monkeypatch):
        """Once the thread completes, the next call serves the data as fresh."""
        from api.routers.admin import proof
        calls = _install_detectors(monkeypatch)

        first = proof.detect_monitoring_gaps()
        assert first["status"] == "scanning"

        # let the background thread finish
        for _ in range(100):
            if calls["n"] > 0:
                break
            time.sleep(0.05)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = proof.detect_monitoring_gaps()
            if result.get("status") != "scanning":
                break
            time.sleep(0.05)

        assert result["status"] == "fresh"
        assert result["stuck_teardowns"]["stuck_count"] == 0
        assert result["resource_leaks"]["orphaned_count"] == 0
        assert "age_seconds" in result
        assert "scanned_at" in result

    def test_stale_result_is_served_and_refreshes(self, monkeypatch):
        """A result older than the TTL is still served (marked stale) while
        a refresh kicks off in the background — the page never blanks."""
        from api.routers.admin import proof
        calls = _install_detectors(monkeypatch)

        proof.detect_monitoring_gaps()
        deadline = time.monotonic() + 5
        result = None
        while time.monotonic() < deadline:
            result = proof.detect_monitoring_gaps()
            if result.get("status") == "fresh":
                break
            time.sleep(0.05)
        assert result["status"] == "fresh"

        # Age the cache past the TTL, change the detector's answer.
        with proof._gaps_cache["lock"]:
            proof._gaps_cache["timestamp"] -= (proof._GAPS_TTL_SECONDS + 10)
        calls["n"] = 0

        stale = proof.detect_monitoring_gaps()
        assert stale["status"] == "stale"
        assert stale["stuck_teardowns"]["stuck_count"] == 0  # data still served

        # and a refresh was kicked
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and calls["n"] == 0:
            time.sleep(0.05)
        assert calls["n"] >= 1

    def test_concurrent_requests_do_not_stack_scans(self, monkeypatch):
        """While a scan is in flight, further calls must not start another."""
        from api.routers.admin import proof
        calls = _install_detectors(monkeypatch, delay=1.0)

        proof.detect_monitoring_gaps()
        proof.detect_monitoring_gaps()
        proof.detect_monitoring_gaps()

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and calls["n"] == 0:
            time.sleep(0.05)
        assert calls["n"] == 1, "stacked background scans"

    def test_failed_detector_still_lands_in_cache(self, monkeypatch):
        """A detector exception is caught by the runner — the cache still
        updates (with per-detector error objects), scanning never sticks."""
        from api.routers.admin import proof

        def fake_run():
            return {
                "stuck_teardowns": {"error": "boom"},
                "resource_leaks": {"error": "boom"},
                "operator_health": {"error": "boom"},
            }

        monkeypatch.setattr(proof, "_run_gap_detectors", fake_run)
        proof.detect_monitoring_gaps()

        result = None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = proof.detect_monitoring_gaps()
            if result.get("status") != "scanning":
                break
            time.sleep(0.05)

        assert result["status"] == "fresh"
        assert result["stuck_teardowns"] == {"error": "boom"}
