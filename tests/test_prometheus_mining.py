"""Prometheus metrics mining — TDD red/green."""

import pytest


class TestPrometheusQueries:
    def test_miner_exists(self):
        from engine.prometheus_miner import query_prometheus
        assert callable(query_prometheus)

    def test_predefined_queries_exist(self):
        from engine.prometheus_miner import HEALTH_QUERIES
        assert "pod_restarts" in HEALTH_QUERIES
        assert "oom_kills" in HEALTH_QUERIES
        assert "cpu_saturation" in HEALTH_QUERIES
        assert "pvc_filling" in HEALTH_QUERIES

    def test_parse_restart_result(self):
        from engine.prometheus_miner import parse_metric_result
        raw = {
            "metric": {"namespace": "test-ns", "pod": "broken-pod", "container": "app"},
            "value": [1716900000, "25"],
        }
        parsed = parse_metric_result(raw, "pod_restarts", "infra01")
        assert parsed["failure_class"] == "pod_high_restart_rate"
        assert parsed["namespace"] == "test-ns"
        assert parsed["cluster"] == "infra01"
        assert parsed["value"] == 25.0

    def test_parse_oom_result(self):
        from engine.prometheus_miner import parse_metric_result
        raw = {
            "metric": {"namespace": "prod", "container": "worker"},
            "value": [1716900000, "3"],
        }
        parsed = parse_metric_result(raw, "oom_kills", "infra01")
        assert parsed["failure_class"] == "container_oom_killed"


class TestMultiClusterMining:
    def test_mine_cluster_exists(self):
        from engine.prometheus_miner import mine_cluster_metrics
        assert callable(mine_cluster_metrics)

    def test_batch_results(self):
        from engine.prometheus_miner import batch_classify_metrics
        metrics = [
            {"failure_class": "pod_high_restart_rate", "namespace": "test", "cluster": "ocpv05", "value": 50},
            {"failure_class": "container_oom_killed", "namespace": "prod", "cluster": "ocpv07", "value": 3},
        ]
        result = batch_classify_metrics(metrics)
        assert result["total"] == 2
        assert result["classified"] == 2


class TestPrometheusFailureClasses:
    def test_classes_have_thresholds(self):
        from engine.prometheus_miner import HEALTH_QUERIES
        for name, q in HEALTH_QUERIES.items():
            assert "query" in q, f"{name} missing PromQL query"
            assert "failure_class" in q, f"{name} missing failure_class"
