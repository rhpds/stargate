"""Tests for the shared failure class schema."""

from contracts.failure_class_schema import FailureClass, normalize_raw_class


class TestFailureClassSchema:
    def test_dataclass_fields(self):
        fc = FailureClass(name="test", patterns=["pat1"])
        assert fc.name == "test"
        assert fc.patterns == ["pat1"]
        assert fc.severity == "medium"
        assert fc.source == "unknown"
        assert fc.category == "general"

    def test_normalize_raw_class(self):
        raw = {
            "name": "pods_crashlooping",
            "patterns": ["CrashLoopBackOff", "Back-off restarting"],
            "severity": "high",
            "source": "k8s-events",
            "remediation": "Check logs",
        }
        result = normalize_raw_class(raw)
        assert result["name"] == "pods_crashlooping"
        assert result["patterns"] == ["CrashLoopBackOff", "Back-off restarting"]
        assert result["severity"] == "high"
        assert result["source"] == "k8s-events"
        assert result["category"] == "pod_health"

    def test_normalize_string_pattern(self):
        raw = {"name": "test", "patterns": "single_pattern", "source": "unknown"}
        result = normalize_raw_class(raw)
        assert result["patterns"] == ["single_pattern"]

    def test_normalize_missing_fields(self):
        raw = {"name": "minimal"}
        result = normalize_raw_class(raw)
        assert result["patterns"] == []
        assert result["severity"] == "medium"
        assert result["category"] == "general"

    def test_category_mapping(self):
        for source, expected in [
            ("k8s-events", "pod_health"),
            ("alertmanager", "cluster_health"),
            ("infrastructure", "infrastructure"),
            ("summit", "provisioning"),
            ("aap", "provisioning"),
            ("other", "general"),
        ]:
            result = normalize_raw_class({"name": "t", "source": source})
            assert result["category"] == expected, f"source={source}"
