"""Cluster health gate — collector, normalizer, rubric pipeline."""

import json
from pathlib import Path

import pytest

from api.app.models import StageOutcome
from api.app.rubric_evaluator import evaluate_rubric
from api.app.rubric_loader import load_rubric
from collectors.cluster_scheduler.collect_cluster_health import collect_cluster_health
from collectors.openshift.collect_resource_state import collect_from_data
from collectors.openshift.evidence_normalizer import normalize_evidence


RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "platform"
CLUSTER_FIXTURES = Path(__file__).parent.parent / "fixtures" / "cluster-scheduler"


def _load(path):
    return json.loads(path.read_text())


class TestCollectClusterHealth:
    def test_healthy_cluster(self):
        ev = collect_cluster_health(_load(CLUSTER_FIXTURES / "healthy.json"))
        assert ev.resource_kind == "ClusterHealth"
        assert ev.observed["cluster_reachable"] is True
        assert ev.observed["cpu_usage_acceptable"] is True
        assert ev.observed["memory_usage_acceptable"] is True
        assert ev.observed["no_critical_alerts"] is True
        assert ev.observed["nodes_healthy"] is True
        assert ev.observed["health_score"] == 92

    def test_degraded_cluster(self):
        ev = collect_cluster_health(_load(CLUSTER_FIXTURES / "degraded.json"))
        assert ev.observed["cluster_reachable"] is True
        assert ev.observed["cpu_usage_acceptable"] is False
        assert ev.observed["memory_usage_acceptable"] is True
        assert ev.observed["no_critical_alerts"] is False
        assert ev.observed["nodes_healthy"] is False
        assert ev.observed["health_score"] == 35


class TestClusterDispatch:
    def test_cluster_health_dispatches(self):
        data = _load(CLUSTER_FIXTURES / "healthy.json")
        ev = collect_from_data(data)
        assert ev.resource_kind == "ClusterHealth"


class TestClusterHealthNormalizer:
    def test_normalize_healthy(self):
        data = _load(CLUSTER_FIXTURES / "healthy.json")
        ev = collect_cluster_health(data)
        normalized = normalize_evidence("cluster-health", [ev])
        assert normalized["cluster_reachable"] is True
        assert normalized["cpu_usage_acceptable"] is True
        assert normalized["memory_usage_acceptable"] is True
        assert normalized["no_critical_alerts"] is True
        assert normalized["nodes_healthy"] is True

    def test_normalize_degraded(self):
        data = _load(CLUSTER_FIXTURES / "degraded.json")
        ev = collect_cluster_health(data)
        normalized = normalize_evidence("cluster-health", [ev])
        assert normalized["cpu_usage_acceptable"] is False
        assert normalized["no_critical_alerts"] is False

    def test_normalize_empty(self):
        normalized = normalize_evidence("cluster-health", [])
        assert normalized["cluster_reachable"] is False


class TestClusterHealthRubricPipeline:
    def test_healthy_passes(self):
        rubric = load_rubric(RUBRIC_DIR / "cluster-health.yaml")
        data = _load(CLUSTER_FIXTURES / "healthy.json")
        ev = collect_cluster_health(data)
        normalized = normalize_evidence("cluster-health", [ev])
        result = evaluate_rubric(rubric, normalized)
        assert result.outcome == StageOutcome.PASS
        assert result.timeout_seconds == 30

    def test_degraded_fails_with_cluster_overloaded(self):
        rubric = load_rubric(RUBRIC_DIR / "cluster-health.yaml")
        data = _load(CLUSTER_FIXTURES / "degraded.json")
        ev = collect_cluster_health(data)
        normalized = normalize_evidence("cluster-health", [ev])
        result = evaluate_rubric(rubric, normalized)
        assert result.outcome == StageOutcome.FAIL
        assert result.failure_class == "cluster_overloaded"

    def test_unreachable_fails(self):
        rubric = load_rubric(RUBRIC_DIR / "cluster-health.yaml")
        normalized = normalize_evidence("cluster-health", [])
        result = evaluate_rubric(rubric, normalized)
        assert result.outcome == StageOutcome.FAIL
        assert result.failure_class == "cluster_unreachable"

    def test_warn_on_unhealthy_nodes(self):
        rubric = load_rubric(RUBRIC_DIR / "cluster-health.yaml")
        data = _load(CLUSTER_FIXTURES / "healthy.json")
        data["metrics"]["unhealthy_nodes"] = 1
        ev = collect_cluster_health(data)
        normalized = normalize_evidence("cluster-health", [ev])
        result = evaluate_rubric(rubric, normalized)
        assert result.outcome == StageOutcome.WARN
