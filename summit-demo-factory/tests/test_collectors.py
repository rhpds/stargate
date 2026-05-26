"""Collector tests — parse oc JSON fixtures, verify evidence output."""

import json
from pathlib import Path

import pytest

from collectors.openshift.collect_resource_state import (
    collect_deployment,
    collect_endpoints,
    collect_events,
    collect_from_file,
    collect_namespace,
    collect_namespace_state,
    collect_pods,
    collect_route,
    collect_service,
)
from collectors.openshift.evidence_normalizer import normalize_evidence
from api.app.rubric_evaluator import evaluate_rubric
from api.app.rubric_loader import load_rubrics_from_directory
from api.app.models import StageOutcome


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "oc"
HEALTHY_DIR = FIXTURE_DIR / "healthy"
UNHEALTHY_DIR = FIXTURE_DIR / "unhealthy"
RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "platform"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


# --- Individual collector tests ---

class TestCollectNamespace:
    def test_healthy_namespace(self):
        data = _load_json(HEALTHY_DIR / "namespace.json")
        ev = collect_namespace(data)
        assert ev.resource_kind == "Namespace"
        assert ev.resource_name == "summit-demo-001"
        assert ev.observed["namespace_exists"] is True
        assert ev.observed["phase"] == "Active"

    def test_unhealthy_namespace(self):
        data = _load_json(UNHEALTHY_DIR / "namespace.json")
        ev = collect_namespace(data)
        assert ev.observed["namespace_exists"] is True


class TestCollectDeployment:
    def test_healthy_deployment(self):
        data = _load_json(HEALTHY_DIR / "deployment.json")
        ev = collect_deployment(data)
        assert ev.resource_kind == "Deployment"
        assert ev.observed["deployment_exists"] is True
        assert ev.observed["desired_replicas_ready"] is True
        assert ev.observed["ready_replicas"] == 1
        assert ev.observed["available"] is True

    def test_unhealthy_deployment(self):
        data = _load_json(UNHEALTHY_DIR / "deployment.json")
        ev = collect_deployment(data)
        assert ev.observed["deployment_exists"] is True
        assert ev.observed["desired_replicas_ready"] is False
        assert ev.observed["ready_replicas"] == 0
        assert ev.observed["available"] is False
        assert ev.observed["unavailable_replicas"] == 1


class TestCollectPods:
    def test_healthy_pods(self):
        data = _load_json(HEALTHY_DIR / "pods.json")
        ev = collect_pods(data)
        assert ev.resource_kind == "PodList"
        assert ev.observed["total_pods"] == 1
        assert ev.observed["ready_pods"] == 1
        assert ev.observed["crashloop_pods"] == 0
        assert ev.observed["no_crashloop_pods"] is True
        assert ev.observed["all_pods_ready"] is True

    def test_unhealthy_pods_crashloop(self):
        data = _load_json(UNHEALTHY_DIR / "pods.json")
        ev = collect_pods(data)
        assert ev.observed["total_pods"] == 1
        assert ev.observed["ready_pods"] == 0
        assert ev.observed["crashloop_pods"] == 1
        assert ev.observed["no_crashloop_pods"] is False
        assert ev.observed["all_pods_ready"] is False

        pod_detail = ev.observed["pod_details"][0]
        assert pod_detail["crashloop"] is True
        assert pod_detail["restarts"] == 5


class TestCollectService:
    def test_service(self):
        data = _load_json(HEALTHY_DIR / "service.json")
        ev = collect_service(data)
        assert ev.resource_kind == "Service"
        assert ev.observed["service_exists"] is True
        assert ev.observed["selector"] == {"app": "demo-app"}


class TestCollectEndpoints:
    def test_healthy_endpoints(self):
        data = _load_json(HEALTHY_DIR / "endpoints.json")
        ev = collect_endpoints(data)
        assert ev.resource_kind == "Endpoints"
        assert ev.observed["ready_endpoint_count"] == 1
        assert ev.observed["service_has_ready_endpoints"] is True
        assert ev.observed["not_ready_endpoint_count"] == 0

    def test_unhealthy_endpoints(self):
        data = _load_json(UNHEALTHY_DIR / "endpoints.json")
        ev = collect_endpoints(data)
        assert ev.observed["ready_endpoint_count"] == 0
        assert ev.observed["service_has_ready_endpoints"] is False
        assert ev.observed["not_ready_endpoint_count"] == 1


class TestCollectRoute:
    def test_healthy_route(self):
        data = _load_json(HEALTHY_DIR / "route.json")
        ev = collect_route(data)
        assert ev.resource_kind == "Route"
        assert ev.observed["route_exists"] is True
        assert ev.observed["admitted"] is True
        assert "apps.cluster.example.com" in ev.observed["host"]
        assert ev.observed["tls_termination"] == "edge"


class TestCollectEvents:
    def test_healthy_events(self):
        data = _load_json(HEALTHY_DIR / "events.json")
        ev = collect_events(data)
        assert ev.observed["total_events"] == 2
        assert ev.observed["warning_events"] == 0
        assert ev.observed["has_warnings"] is False

    def test_unhealthy_events(self):
        data = _load_json(UNHEALTHY_DIR / "events.json")
        ev = collect_events(data)
        assert ev.observed["total_events"] == 2
        assert ev.observed["warning_events"] == 2
        assert ev.observed["has_warnings"] is True
        assert ev.observed["warnings"][0]["reason"] == "BackOff"


# --- File-based collection ---

class TestCollectFromFile:
    def test_collect_namespace_file(self):
        ev = collect_from_file(HEALTHY_DIR / "namespace.json")
        assert ev.resource_kind == "Namespace"
        assert "file:" in ev.source

    def test_collect_all_healthy(self):
        results = collect_namespace_state(HEALTHY_DIR)
        kinds = {r.resource_kind for r in results}
        assert "Namespace" in kinds
        assert "Deployment" in kinds
        assert "PodList" in kinds
        assert "Service" in kinds
        assert "Endpoints" in kinds
        assert "Route" in kinds
        assert "EventList" in kinds


# --- Normalizer tests ---

class TestEvidenceNormalizer:
    def _collect(self, fixture_dir: Path):
        return collect_namespace_state(fixture_dir)

    def test_normalize_namespace_ready_healthy(self):
        evidence_list = self._collect(HEALTHY_DIR)
        normalized = normalize_evidence("namespace-ready", evidence_list)
        assert normalized["namespace_exists"] is True

    def test_normalize_deployment_ready_healthy(self):
        evidence_list = self._collect(HEALTHY_DIR)
        normalized = normalize_evidence("deployment-ready", evidence_list)
        assert normalized["namespace_exists"] is True
        assert normalized["deployment_exists"] is True
        assert normalized["desired_replicas_ready"] is True
        assert normalized["no_crashloop_pods"] is True

    def test_normalize_deployment_ready_unhealthy(self):
        evidence_list = self._collect(UNHEALTHY_DIR)
        normalized = normalize_evidence("deployment-ready", evidence_list)
        assert normalized["deployment_exists"] is True
        assert normalized["desired_replicas_ready"] is False
        assert normalized["no_crashloop_pods"] is False

    def test_normalize_route_ready_healthy(self):
        evidence_list = self._collect(HEALTHY_DIR)
        normalized = normalize_evidence("route-ready", evidence_list)
        assert normalized["service_exists"] is True
        assert normalized["route_exists"] is True
        assert normalized["service_has_ready_endpoints"] is True

    def test_normalize_route_ready_unhealthy(self):
        evidence_list = self._collect(UNHEALTHY_DIR)
        normalized = normalize_evidence("route-ready", evidence_list)
        assert normalized["service_exists"] is True
        assert normalized["route_exists"] is True
        assert normalized["service_has_ready_endpoints"] is False


# --- End-to-end: collector -> normalizer -> rubric evaluator ---

class TestCollectorToRubricPipeline:
    """Full pipeline: oc JSON fixtures -> collector -> normalizer -> rubric evaluator."""

    def _load_rubrics(self):
        rubrics = {}
        for r in load_rubrics_from_directory(RUBRIC_DIR):
            rubrics[r.stage] = r
        return rubrics

    def test_healthy_namespace_passes_rubric(self):
        rubrics = self._load_rubrics()
        evidence_list = collect_namespace_state(HEALTHY_DIR)
        normalized = normalize_evidence("namespace-ready", evidence_list)
        result = evaluate_rubric(rubrics["namespace-ready"], normalized)
        assert result.outcome == StageOutcome.PASS

    def test_healthy_deployment_passes_rubric(self):
        rubrics = self._load_rubrics()
        evidence_list = collect_namespace_state(HEALTHY_DIR)
        normalized = normalize_evidence("deployment-ready", evidence_list)
        result = evaluate_rubric(rubrics["deployment-ready"], normalized)
        assert result.outcome == StageOutcome.PASS

    def test_healthy_route_passes_rubric(self):
        rubrics = self._load_rubrics()
        evidence_list = collect_namespace_state(HEALTHY_DIR)
        normalized = normalize_evidence("route-ready", evidence_list)
        result = evaluate_rubric(rubrics["route-ready"], normalized)
        assert result.outcome == StageOutcome.PASS

    def test_unhealthy_deployment_fails_rubric(self):
        rubrics = self._load_rubrics()
        evidence_list = collect_namespace_state(UNHEALTHY_DIR)
        normalized = normalize_evidence("deployment-ready", evidence_list)
        result = evaluate_rubric(rubrics["deployment-ready"], normalized)
        assert result.outcome == StageOutcome.FAIL

    def test_unhealthy_route_fails_rubric(self):
        rubrics = self._load_rubrics()
        evidence_list = collect_namespace_state(UNHEALTHY_DIR)
        normalized = normalize_evidence("route-ready", evidence_list)
        result = evaluate_rubric(rubrics["route-ready"], normalized)
        assert result.outcome == StageOutcome.FAIL
        assert result.failure_class == "service_has_no_endpoints"

    def test_unhealthy_deployment_identifies_crashloop(self):
        rubrics = self._load_rubrics()
        evidence_list = collect_namespace_state(UNHEALTHY_DIR)
        normalized = normalize_evidence("deployment-ready", evidence_list)
        result = evaluate_rubric(rubrics["deployment-ready"], normalized)
        assert result.outcome == StageOutcome.FAIL
        assert result.failure_class == "pods_crashlooping"
