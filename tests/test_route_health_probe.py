"""The route health probe: what it observes, and what it refuses to claim.

route-ready's other criteria come from `oc get`. `health_endpoint_returns_200`
only becomes observable if something issues a request, so the probe's job is
narrow on purpose: report the status line, distinguish "observed non-200" from
"did not find out", and never turn a timeout into a failure.

Unit tests mock the opener — tests/conftest.py blocks ambient sockets, so the
real request path is exercised by the integration run, not here.
"""

from pathlib import Path
import socket

import pytest
from urllib.error import HTTPError, URLError

from collectors.openshift import probe_route_health as probe
from collectors.openshift.collect_resource_state import CollectedEvidence
from collectors.openshift.evidence_normalizer import normalize_evidence
from engine.models import StageOutcome
from engine.rubric_evaluator import evaluate_rubric
from engine.rubric_loader import load_rubric

RUBRICS = Path(__file__).resolve().parents[1] / "rubrics" / "platform"


# --- opener doubles -------------------------------------------------------


class _Response:
    def __init__(self, status: int):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Opener:
    """Stands in for the urllib opener, returning or raising a canned answer."""

    def __init__(self, behaviour):
        self._behaviour = behaviour

    def open(self, request, timeout=None):
        if callable(self._behaviour):
            return self._behaviour()
        return _Response(self._behaviour)


def _install(monkeypatch, behaviour):
    monkeypatch.setattr(probe, "_opener", lambda verify: _Opener(behaviour))


# --- the observation itself ----------------------------------------------


def test_two_hundred_is_observed_success(monkeypatch):
    _install(monkeypatch, 200)
    result = probe.probe_route("https://app.example.com")
    assert result.resource_kind == "HttpProbe"
    assert result.observed["http_status"] == 200
    assert result.observed["health_endpoint_returns_200"] is True
    assert result.observed["probe_error"] is None
    assert result.observed["probe_duration_ms"] >= 0


def test_server_error_is_an_observed_non_200(monkeypatch):
    def _503():
        raise HTTPError("https://app.example.com", 503, "Service Unavailable", None, None)

    _install(monkeypatch, _503)
    result = probe.probe_route("https://app.example.com")
    assert result.observed["http_status"] == 503
    assert result.observed["health_endpoint_returns_200"] is False


def test_auth_challenge_still_counts_as_an_answer(monkeypatch):
    """An OAuth-protected route redirecting or challenging is up, not down."""

    def _401():
        raise HTTPError("https://app.example.com", 401, "Unauthorized", None, None)

    _install(monkeypatch, _401)
    result = probe.probe_route("https://app.example.com")
    assert result.observed["http_status"] == 401
    assert result.observed["health_endpoint_returns_200"] is False


def test_refused_connection_is_an_observed_non_200(monkeypatch):
    def _refused():
        raise URLError(ConnectionRefusedError(61, "Connection refused"))

    _install(monkeypatch, _refused)
    result = probe.probe_route("https://nothing.invalid")
    assert result.observed["http_status"] is None
    assert result.observed["health_endpoint_returns_200"] is False
    assert "refused" in result.observed["probe_error"].lower()


def test_timeout_is_unobserved_not_failed(monkeypatch):
    """The distinction the whole contract rests on."""

    def _slow():
        raise socket.timeout("timed out")

    _install(monkeypatch, _slow)
    result = probe.probe_route("https://slow.invalid", timeout=0.01)
    assert result.observed["http_status"] is None
    assert result.observed["health_endpoint_returns_200"] is None
    assert "timeout" in result.observed["probe_error"]


def test_url_requires_a_scheme():
    with pytest.raises(ValueError):
        probe.probe_route("example.com")


# --- URL derivation from a Route -----------------------------------------


def test_route_url_follows_tls_termination():
    tls = CollectedEvidence(
        "Route", "app", "lab", {"route_exists": True, "host": "app.example.com",
                                 "admitted": True, "tls_termination": "edge"}
    )
    plain = CollectedEvidence(
        "Route", "app", "lab", {"route_exists": True, "host": "app.example.com",
                                 "admitted": True, "tls_termination": None}
    )
    assert probe.route_url(tls) == "https://app.example.com"
    assert probe.route_url(plain) == "http://app.example.com"


def test_route_without_host_yields_no_probe():
    route = CollectedEvidence(
        "Route", "app", "lab", {"route_exists": True, "host": "", "admitted": False,
                                 "tls_termination": "edge"}
    )
    assert probe.probe_route_evidence(route) is None


# --- how the rubric consumes it ------------------------------------------


def _topology():
    return [
        CollectedEvidence("Service", "app", "lab", {"service_exists": True}),
        CollectedEvidence("Route", "app", "lab", {
            "route_exists": True, "host": "app.example.com", "admitted": True,
            "tls_termination": "edge",
        }),
        CollectedEvidence("Endpoints", "app", "lab", {
            "service_has_ready_endpoints": True, "ready_endpoint_count": 1,
        }),
    ]


def _probe_evidence(healthy, status=None, error=None):
    return CollectedEvidence("HttpProbe", "https://app.example.com", "lab", {
        "http_status": status,
        "health_endpoint_returns_200": healthy,
        "probe_error": error,
        "probe_duration_ms": 12,
        "probed_url": "https://app.example.com",
    }, source="http-probe")


def test_observed_200_passes_route_ready():
    evidence = normalize_evidence("route-ready", _topology() + [_probe_evidence(True, 200)])
    result = evaluate_rubric(load_rubric(RUBRICS / "route-ready.yaml"), evidence)
    assert result.outcome == StageOutcome.PASS
    assert result.failure_class is None


def test_unprobed_route_stays_indeterminate():
    """Without the probe the stage must not claim a pass — the old boundary."""
    evidence = normalize_evidence("route-ready", _topology())
    assert evidence["health_endpoint_returns_200"] is None
    result = evaluate_rubric(load_rubric(RUBRICS / "route-ready.yaml"), evidence)
    assert result.outcome == StageOutcome.INDETERMINATE


def test_observed_non_200_warns_with_its_class():
    evidence = normalize_evidence("route-ready", _topology() + [_probe_evidence(False, 503)])
    result = evaluate_rubric(load_rubric(RUBRICS / "route-ready.yaml"), evidence)
    assert result.outcome == StageOutcome.WARN
    assert result.failure_class == "health_check_failed"


def test_probe_carries_status_and_reason_into_the_evidence():
    evidence = normalize_evidence(
        "route-ready", _topology() + [_probe_evidence(False, 502, "bad gateway")]
    )
    assert evidence["http_status"] == 502
    assert evidence["probe_error"] == "bad gateway"


# --- wiring into collect-dir ---------------------------------------------


def _route(host="app.example.com", termination="edge"):
    return CollectedEvidence(
        "Route", "app", "lab", {
            "route_exists": True, "host": host, "admitted": True,
            "tls_termination": termination,
        },
    )


def _endpoints(ready=True, count=1):
    return CollectedEvidence(
        "Endpoints", "app", "lab", {
            "service_has_ready_endpoints": ready, "ready_endpoint_count": count,
        },
    )


def test_probe_is_off_unless_enabled(monkeypatch):
    """Collection stays read-only by default — no request, no new evidence."""
    from cli.stargate import _with_route_probes

    monkeypatch.delenv("STARGATE_ROUTE_PROBE", raising=False)
    topology = [_route(), _endpoints()]
    assert _with_route_probes(topology, quiet=True) == topology


def test_enabled_probe_appends_http_evidence(monkeypatch):
    from cli.stargate import _with_route_probes

    monkeypatch.setenv("STARGATE_ROUTE_PROBE", "1")
    _install(monkeypatch, 200)

    result = _with_route_probes([_route(), _endpoints()], quiet=True)
    probes = [ev for ev in result if ev.resource_kind == "HttpProbe"]
    assert len(probes) == 1
    assert probes[0].observed["health_endpoint_returns_200"] is True
    assert probes[0].observed["probed_url"] == "https://app.example.com"


def test_no_ready_endpoints_means_no_probe(monkeypatch):
    """A lab with nothing serving already fails; do not spend the timeout."""
    from cli.stargate import _with_route_probes

    monkeypatch.setenv("STARGATE_ROUTE_PROBE", "1")

    def _explode(verify):
        raise AssertionError("probe opener should not be built")

    monkeypatch.setattr(probe, "_opener", _explode)
    result = _with_route_probes([_route(), _endpoints(ready=False, count=0)], quiet=True)
    assert not [ev for ev in result if ev.resource_kind == "HttpProbe"]


def test_hostless_route_adds_no_evidence(monkeypatch):
    from cli.stargate import _with_route_probes

    monkeypatch.setenv("STARGATE_ROUTE_PROBE", "1")
    result = _with_route_probes([_route(host=""), _endpoints()], quiet=True)
    assert not [ev for ev in result if ev.resource_kind == "HttpProbe"]


def test_unresolvable_host_is_unobserved(monkeypatch):
    """A DNS failure may be our resolver, not the app — do not fabricate a fail."""
    import socket as _socket

    def _no_dns():
        raise URLError(_socket.gaierror(-2, "Name or service not known"))

    _install(monkeypatch, _no_dns)
    result = probe.probe_route("https://nowhere.invalid")
    assert result.observed["http_status"] is None
    assert result.observed["health_endpoint_returns_200"] is None
    assert "name or service" in result.observed["probe_error"].lower()


def test_warn_message_names_the_status_it_observed():
    """A warn must say 503, not just 'health_endpoint_returns_200'."""
    evidence = normalize_evidence("route-ready", _topology() + [_probe_evidence(False, 403)])
    result = evaluate_rubric(load_rubric(RUBRICS / "route-ready.yaml"), evidence)
    assert result.outcome == StageOutcome.WARN
    assert "HTTP 403" in result.message


def test_warn_message_names_the_reason_when_there_is_no_status():
    evidence = normalize_evidence(
        "route-ready", _topology() + [_probe_evidence(False, None, "connection refused")]
    )
    result = evaluate_rubric(load_rubric(RUBRICS / "route-ready.yaml"), evidence)
    assert result.outcome == StageOutcome.WARN
    assert "connection refused" in result.message


def test_probe_uses_the_route_path_not_root(monkeypatch):
    """A route mounted at /showroom must not be probed at / and called a 404."""
    seen = {}

    def _capture(verify):
        class _O:
            def open(self, request, timeout=None):
                seen["url"] = request.full_url
                return _Response(200)

        return _O()

    monkeypatch.setattr(probe, "_opener", _capture)
    route = CollectedEvidence(
        "Route", "app", "lab", {
            "route_exists": True, "host": "app.example.com", "admitted": True,
            "tls_termination": "edge", "path": "/showroom",
        },
    )
    result = probe.probe_route_evidence(route)
    assert seen["url"] == "https://app.example.com/showroom"
    assert result.observed["health_endpoint_returns_200"] is True


# --- several routes serve one lab -----------------------------------------


def _probe_at(url, healthy, status=None, error=None):
    return CollectedEvidence("HttpProbe", url, "lab", {
        "http_status": status,
        "health_endpoint_returns_200": healthy,
        "probe_error": error,
        "probe_duration_ms": 12,
        "probed_url": url,
    }, source="http-probe")


def test_all_routes_healthy_passes():
    evidence = normalize_evidence("route-ready", _topology() + [
        _probe_at("https://showroom.example.com", True, 200),
        _probe_at("https://vscode.example.com", True, 302),
    ])
    assert evidence["health_endpoint_returns_200"] is True
    result = evaluate_rubric(load_rubric(RUBRICS / "route-ready.yaml"), evidence)
    assert result.outcome == StageOutcome.PASS


def test_one_healthy_route_is_enough():
    """A lab ships routes whose backends the student is meant to create.

    `service_exists`, `route_exists` and `service_has_ready_endpoints` are all
    satisfied by ANY service or route in the namespace, so the optional probe
    must not demand every route answer. Live measurement: 25 of 48 lab
    namespaces had at least one `app-`/`clab-report`/`bastion-443` route at 503
    by design.
    """
    evidence = normalize_evidence("route-ready", _topology() + [
        _probe_at("https://showroom.example.com", True, 200),
        _probe_at("https://app.example.com", False, 503),
    ])
    assert evidence["health_endpoint_returns_200"] is True
    assert evidence["routes_probed"] == 2
    result = evaluate_rubric(load_rubric(RUBRICS / "route-ready.yaml"), evidence)
    assert result.outcome == StageOutcome.PASS


def test_no_route_answering_fails_the_ns_regardless_of_order():
    """`oc get routes` order must not decide whether a lab is unhealthy."""
    dead = [_probe_at("https://app.example.com", False, 503),
            _probe_at("https://bastion.example.com", False, 503)]

    for probes in (dead, list(reversed(dead))):
        evidence = normalize_evidence("route-ready", _topology() + probes)
        assert evidence["health_endpoint_returns_200"] is False
        assert evidence["http_status"] == 503
        result = evaluate_rubric(load_rubric(RUBRICS / "route-ready.yaml"), evidence)
        assert result.outcome == StageOutcome.WARN
        assert result.failure_class == "health_check_failed"


def test_only_timeouts_holds_the_stage_indeterminate():
    """Nothing answered and nothing refused: we learned nothing."""
    evidence = normalize_evidence("route-ready", _topology() + [
        _probe_at("https://slow.example.com", None, None, "timeout after 5s"),
        _probe_at("https://slower.example.com", None, None, "timeout after 5s"),
    ])
    assert evidence["health_endpoint_returns_200"] is None
    result = evaluate_rubric(load_rubric(RUBRICS / "route-ready.yaml"), evidence)
    assert result.outcome == StageOutcome.INDETERMINATE


def test_a_timeout_does_not_drag_down_an_answered_lab():
    evidence = normalize_evidence("route-ready", _topology() + [
        _probe_at("https://showroom.example.com", True, 200),
        _probe_at("https://slow.example.com", None, None, "timeout after 5s"),
    ])
    assert evidence["health_endpoint_returns_200"] is True
    result = evaluate_rubric(load_rubric(RUBRICS / "route-ready.yaml"), evidence)
    assert result.outcome == StageOutcome.PASS


def test_warn_message_says_no_route_answered_and_names_one():
    evidence = normalize_evidence("route-ready", _topology() + [
        _probe_at("https://app.example.com", False, 503),
        _probe_at("https://bastion.example.com", False, 502),
    ])
    result = evaluate_rubric(load_rubric(RUBRICS / "route-ready.yaml"), evidence)
    assert "no route answered, 2 probed" in result.message
    # the 503 is preferred over the 502 as the representative finding
    assert "HTTP 503 at https://app.example.com" in result.message
