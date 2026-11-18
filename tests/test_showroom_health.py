"""Showroom health gate — collector, normalizer, rubric pipeline."""

import json
from pathlib import Path

import pytest

from engine.models import StageOutcome
from engine.rubric_evaluator import evaluate_rubric
from engine.rubric_loader import load_rubric
from collectors.showroom.collect_showroom_health import collect_showroom_health
from collectors.openshift.collect_resource_state import collect_from_data
from collectors.openshift.evidence_normalizer import normalize_evidence


RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "platform"
SHOWROOM_FIXTURES = Path(__file__).parent.parent / "fixtures" / "showroom"


def _load(path):
    return json.loads(path.read_text())


class TestCollectShowroomHealth:
    def test_healthy_showroom(self):
        ev = collect_showroom_health(_load(SHOWROOM_FIXTURES / "healthy.json"))
        assert ev.resource_kind == "ShowroomHealth"
        assert ev.observed["showroom_pod_running"] is True
        assert ev.observed["showroom_route_reachable"] is True
        assert ev.observed["readyz_returns_200"] is True
        assert ev.observed["content_loaded"] is True
        assert ev.observed["response_time_acceptable"] is True

    def test_unhealthy_showroom(self):
        ev = collect_showroom_health(_load(SHOWROOM_FIXTURES / "unhealthy.json"))
        assert ev.observed["showroom_pod_running"] is True
        assert ev.observed["readyz_returns_200"] is False
        assert ev.observed["content_loaded"] is False
        assert ev.observed["response_time_acceptable"] is False


class TestShowroomDispatch:
    def test_showroom_dispatches(self):
        data = _load(SHOWROOM_FIXTURES / "healthy.json")
        ev = collect_from_data(data)
        assert ev.resource_kind == "ShowroomHealth"


class TestShowroomNormalizer:
    def test_normalize_healthy(self):
        data = _load(SHOWROOM_FIXTURES / "healthy.json")
        ev = collect_showroom_health(data)
        normalized = normalize_evidence("showroom-healthy", [ev])
        assert normalized["showroom_pod_running"] is True
        assert normalized["showroom_route_reachable"] is True
        assert normalized["readyz_returns_200"] is True
        assert normalized["content_loaded"] is True
        assert normalized["response_time_acceptable"] is True

    def test_normalize_unhealthy(self):
        data = _load(SHOWROOM_FIXTURES / "unhealthy.json")
        ev = collect_showroom_health(data)
        normalized = normalize_evidence("showroom-healthy", [ev])
        assert normalized["readyz_returns_200"] is False
        assert normalized["content_loaded"] is False

    def test_normalize_empty(self):
        normalized = normalize_evidence("showroom-healthy", [])
        assert normalized["showroom_pod_running"] is False
        assert normalized["showroom_route_reachable"] is False


class TestShowroomRubricPipeline:
    def test_healthy_passes(self):
        rubric = load_rubric(RUBRIC_DIR / "showroom-healthy.yaml")
        data = _load(SHOWROOM_FIXTURES / "healthy.json")
        ev = collect_showroom_health(data)
        normalized = normalize_evidence("showroom-healthy", [ev])
        result = evaluate_rubric(rubric, normalized)
        assert result.outcome == StageOutcome.PASS
        assert result.timeout_seconds == 60

    def test_unhealthy_fails_with_showroom_not_ready(self):
        rubric = load_rubric(RUBRIC_DIR / "showroom-healthy.yaml")
        data = _load(SHOWROOM_FIXTURES / "unhealthy.json")
        ev = collect_showroom_health(data)
        normalized = normalize_evidence("showroom-healthy", [ev])
        result = evaluate_rubric(rubric, normalized)
        assert result.outcome == StageOutcome.FAIL
        assert result.failure_class == "showroom_not_ready"

    def test_route_unreachable_blocks_entry(self):
        rubric = load_rubric(RUBRIC_DIR / "showroom-healthy.yaml")
        normalized = normalize_evidence("showroom-healthy", [])
        result = evaluate_rubric(rubric, normalized)
        assert result.outcome == StageOutcome.FAIL
        assert "Entry criterion" in result.message


class TestShowroomDiagnostics:
    """A failing showroom check must carry the URL and status — without them
    the failure is not reproducible (reviewer feedback, 2026-11-18)."""

    def _health(self, **status):
        base = {
            "pod_running": True,
            "route_reachable": False,
            "readyz_status": 0,
            "response_time_ms": 120,
        }
        base.update(status)
        return {"metadata": {"name": "showroom", "namespace": "sandbox-x"},
                "status": base}

    def test_collector_carries_route_url_status_and_error(self):
        ev = collect_showroom_health(self._health(
            route_url="https://showroom-x.apps.example.com",
            http_status=503,
            error="HTTP 503",
            catalog_item="zt-rhel-bu-lab-developer-cnv",
        ))
        assert ev.observed["route_url"] == "https://showroom-x.apps.example.com"
        assert ev.observed["http_status"] == 503
        assert ev.observed["error"] == "HTTP 503"
        assert ev.observed["catalog_item"] == "zt-rhel-bu-lab-developer-cnv"

    def test_normalizer_carries_diagnostics_and_ready_endpoints(self):
        health = collect_showroom_health(self._health(
            route_url="https://showroom-x.apps.example.com", http_status=503,
            catalog_item="zt-rhel-bu-lab-developer-cnv"))
        endpoints = collect_from_data({
            "kind": "Endpoints",
            "metadata": {"name": "showroom", "namespace": "sandbox-x"},
            "subsets": [],
        })
        normalized = normalize_evidence("showroom-healthy", [health, endpoints])

        assert normalized["route_url"] == "https://showroom-x.apps.example.com"
        assert normalized["http_status"] == 503
        assert normalized["ready_endpoint_count"] == 0
        assert normalized["catalog_item"] == "zt-rhel-bu-lab-developer-cnv"

    def test_failure_message_names_the_url_and_status(self):
        rubric = load_rubric(RUBRIC_DIR / "showroom-healthy.yaml")
        normalized = normalize_evidence("showroom-healthy", [])
        normalized.update({
            "route_url": "https://showroom-x.apps.example.com",
            "http_status": 503,
            "ready_endpoint_count": 0,
            "catalog_item": "zt-rhel-bu-lab-developer-cnv",
        })
        result = evaluate_rubric(rubric, normalized)

        assert result.outcome == StageOutcome.FAIL
        assert "showroom-x.apps.example.com" in result.message
        assert "503" in result.message
        assert "0 ready endpoints" in result.message
        assert "zt-rhel-bu-lab-developer-cnv" in result.message
