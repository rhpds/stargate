"""Failure class YAML validation — ensures all definitions are valid and complete."""

import pytest
from pathlib import Path
import yaml


FAILURE_CLASSES_DIR = Path(__file__).parent.parent / "failure-classes"


class TestYAMLStructure:
    """All failure class YAML files parse and have required fields."""

    def test_yaml_files_exist(self):
        files = list(FAILURE_CLASSES_DIR.glob("*.yaml"))
        assert len(files) >= 3, f"Expected at least 3 YAML files, found {len(files)}"

    @pytest.mark.parametrize("yaml_file", list(FAILURE_CLASSES_DIR.glob("*.yaml")))
    def test_yaml_parses(self, yaml_file):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "id" in data
        assert "version" in data
        assert "classes" in data

    @pytest.mark.parametrize("yaml_file", list(FAILURE_CLASSES_DIR.glob("*.yaml")))
    def test_each_class_has_required_fields(self, yaml_file):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        for cls_name, cls_data in data.get("classes", {}).items():
            assert "severity" in cls_data, f"{yaml_file.name}:{cls_name} missing severity"
            assert "remediation" in cls_data, f"{yaml_file.name}:{cls_name} missing remediation"
            assert len(cls_data["remediation"]) > 0, f"{yaml_file.name}:{cls_name} has empty remediation"
            assert cls_data["severity"] in ("low", "medium", "high", "critical", "warning", "info", "none"), \
                f"{yaml_file.name}:{cls_name} invalid severity: {cls_data['severity']}"


class TestFailureClassLoader:
    def test_loader_loads_all_classes(self):
        from engine.failure_class_loader import get_all_classes, reload
        reload()
        classes = get_all_classes()
        assert len(classes) >= 50, f"Expected at least 50 classes, got {len(classes)}"

    def test_classify_by_pattern(self):
        from engine.failure_class_loader import classify_by_pattern, reload
        reload()
        cls, data = classify_by_pattern("Back-off pulling image quay.io/test:broken")
        assert cls == "image_pull_backoff"
        assert "remediation" in data

    def test_classify_by_alertname(self):
        from engine.failure_class_loader import classify_by_alertname, reload
        reload()
        cls, data = classify_by_alertname("TargetDown")
        assert cls == "monitoring_target_down"

    def test_get_classes_by_source(self):
        from engine.failure_class_loader import get_classes_by_source, reload
        reload()
        aap = get_classes_by_source("aap2_grafana")
        k8s = get_classes_by_source("k8s_events")
        alerts = get_classes_by_source("alertmanager")
        assert len(aap) >= 11
        assert len(k8s) >= 24
        assert len(alerts) >= 15
