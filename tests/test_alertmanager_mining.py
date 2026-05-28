"""Alertmanager alert mining — TDD red/green."""

import pytest


class TestAlertParser:
    def test_parser_exists(self):
        from engine.alertmanager_miner import parse_alert
        assert callable(parse_alert)

    def test_parse_memory_alert(self):
        from engine.alertmanager_miner import parse_alert
        alert = {
            "labels": {"alertname": "SystemMemoryExceedsReservation", "severity": "warning", "namespace": "openshift-machine-config-operator", "node": "ocp-infra01-ceph01"},
            "annotations": {"description": "System memory usage of 1.83G exceeds 95% of the reservation"},
            "startsAt": "2026-04-10T14:17:57Z",
        }
        result = parse_alert(alert, "infra01")
        assert result["failure_class"] == "node_memory_pressure"
        assert result["severity"] == "warning"

    def test_parse_pdb_alert(self):
        from engine.alertmanager_miner import parse_alert
        alert = {
            "labels": {"alertname": "PodDisruptionBudgetAtLimit", "severity": "warning", "namespace": "openshift-monitoring"},
            "annotations": {"description": "PDB is at minimum available"},
            "startsAt": "2026-05-01T00:00:00Z",
        }
        result = parse_alert(alert, "infra01")
        assert result["failure_class"] == "pdb_at_limit"

    def test_parse_insights_cve(self):
        from engine.alertmanager_miner import parse_alert
        alert = {
            "labels": {"alertname": "InsightsRecommendationActive", "severity": "info"},
            "annotations": {"description": "CVE-2026-31431 Linux kernel flaw"},
            "startsAt": "2026-05-08T00:00:00Z",
        }
        result = parse_alert(alert, "infra01")
        assert result["failure_class"] == "insights_cve"

    def test_parse_target_down(self):
        from engine.alertmanager_miner import parse_alert
        alert = {
            "labels": {"alertname": "TargetDown", "severity": "warning", "namespace": "openshift-monitoring", "job": "kube-state-metrics"},
            "annotations": {"description": "10% of targets down"},
            "startsAt": "2026-05-20T00:00:00Z",
        }
        result = parse_alert(alert, "infra01")
        assert result["failure_class"] == "monitoring_target_down"


class TestAlertFailureClasses:
    def test_classes_exist(self):
        from engine.alertmanager_miner import ALERT_FAILURE_CLASSES
        assert len(ALERT_FAILURE_CLASSES) >= 8

    def test_each_has_remediation(self):
        from engine.alertmanager_miner import ALERT_FAILURE_CLASSES
        for name, data in ALERT_FAILURE_CLASSES.items():
            assert "remediation" in data, f"{name} missing remediation"


class TestAlertCollection:
    def test_collect_function_exists(self):
        from engine.alertmanager_miner import collect_alerts
        assert callable(collect_alerts)

    def test_batch_classify(self):
        from engine.alertmanager_miner import batch_classify_alerts
        alerts = [
            {"labels": {"alertname": "TargetDown", "severity": "warning"}, "annotations": {"description": "targets down"}, "startsAt": "2026-05-20T00:00:00Z"},
            {"labels": {"alertname": "SystemMemoryExceedsReservation", "severity": "warning"}, "annotations": {"description": "memory exceeds"}, "startsAt": "2026-05-20T00:00:00Z"},
        ]
        result = batch_classify_alerts(alerts, "infra01")
        assert result["total"] == 2
        assert result["classified"] >= 2
