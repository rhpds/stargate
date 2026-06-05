"""Workflow tests — Corpus Mining: K8s events + alerts → failure class corpus."""


class TestK8sEventClassification:

    def test_failure_classes_defined(self):
        from engine.k8s_event_miner import K8S_FAILURE_CLASSES
        assert len(K8S_FAILURE_CLASSES) > 0
        assert "image_pull_backoff" in K8S_FAILURE_CLASSES or "image_pull_failed" in K8S_FAILURE_CLASSES

    def test_crashloop_class_exists(self):
        from engine.k8s_event_miner import K8S_FAILURE_CLASSES
        crashloop_classes = [k for k in K8S_FAILURE_CLASSES if "crash" in k or "backoff" in k]
        assert len(crashloop_classes) > 0


class TestAlertmanagerClassification:

    def test_alert_mapping_exists(self):
        from engine.alertmanager_miner import batch_classify_alerts
        assert callable(batch_classify_alerts)


class TestFailureClassLoader:

    def test_loads_classes(self):
        from engine.failure_class_loader import get_all_classes
        classes = get_all_classes()
        assert len(classes) > 0
