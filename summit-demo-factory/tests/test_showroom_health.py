"""Showroom health gate — collector, normalizer, rubric pipeline."""

import json
from pathlib import Path

import pytest

from api.app.models import StageOutcome
from api.app.rubric_evaluator import evaluate_rubric
from api.app.rubric_loader import load_rubric
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
