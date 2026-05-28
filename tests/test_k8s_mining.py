"""K8s event mining — TDD red/green.

Tests multi-cluster event collection, classification, and corpus building.
"""

import pytest


class TestEventMiner:
    def test_miner_exists(self):
        from engine.k8s_event_miner import mine_cluster_events
        assert callable(mine_cluster_events)

    def test_miner_returns_structured_events(self):
        from engine.k8s_event_miner import parse_k8s_event
        raw = {
            "type": "Warning",
            "reason": "BackOff",
            "message": "Back-off pulling image quay.io/test/broken:latest",
            "namespace": "sandbox-abc123",
            "resource_kind": "Pod",
            "resource_name": "broken-pod-xyz",
            "count": 5,
            "cluster": "ocpv05",
        }
        parsed = parse_k8s_event(raw)
        assert parsed["failure_class"] in ("image_pull_backoff", "pods_crashlooping", "unclassified")
        assert parsed["cluster"] == "ocpv05"
        assert parsed["severity"] in ("low", "medium", "high", "critical")

    def test_classify_migration_backoff(self):
        from engine.k8s_event_miner import parse_k8s_event
        raw = {"type": "Warning", "reason": "MigrationBackoff", "message": "backoff migrating vmi", "namespace": "test", "cluster": "ocpv05"}
        assert parse_k8s_event(raw)["failure_class"] == "vm_migration_backoff"

    def test_classify_image_pull(self):
        from engine.k8s_event_miner import parse_k8s_event
        raw = {"type": "Warning", "reason": "BackOff", "message": "Back-off pulling image", "namespace": "test", "cluster": "ocpv05"}
        assert parse_k8s_event(raw)["failure_class"] == "image_pull_backoff"

    def test_classify_hpa_metric_failure(self):
        from engine.k8s_event_miner import parse_k8s_event
        raw = {"type": "Warning", "reason": "FailedGetResourceMetric", "message": "failed to get cpu utilization", "namespace": "test", "cluster": "ocpv05"}
        assert parse_k8s_event(raw)["failure_class"] == "hpa_metric_failure"


class TestK8sFailureClasses:
    def test_classes_registered(self):
        from engine.k8s_event_miner import K8S_FAILURE_CLASSES
        assert "image_pull_backoff" in K8S_FAILURE_CLASSES
        assert "vm_migration_backoff" in K8S_FAILURE_CLASSES
        assert "hpa_metric_failure" in K8S_FAILURE_CLASSES

    def test_each_class_has_remediation(self):
        from engine.k8s_event_miner import K8S_FAILURE_CLASSES
        for cls_name, cls_data in K8S_FAILURE_CLASSES.items():
            assert "remediation" in cls_data, f"{cls_name} missing remediation"


class TestMultiClusterMining:
    def test_batch_mine_returns_summary(self):
        from engine.k8s_event_miner import batch_classify_events
        events = [
            {"type": "Warning", "reason": "BackOff", "message": "Back-off pulling image", "namespace": "test", "cluster": "ocpv05"},
            {"type": "Warning", "reason": "MigrationBackoff", "message": "backoff migrating vmi", "namespace": "test", "cluster": "ocpv07"},
        ]
        result = batch_classify_events(events)
        assert result["total"] == 2
        assert result["classified"] >= 2
