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
            ("k8s_events", "pod_health"),
            ("alertmanager", "cluster_health"),
            ("infrastructure", "infrastructure"),
            ("summit", "provisioning"),
            ("aap", "provisioning"),
            ("aap2_grafana", "provisioning"),
            ("other", "general"),
        ]:
            result = normalize_raw_class({"name": "t", "source": source})
            assert result["category"] == expected, f"source={source}"

    def test_real_catalog_sources_map_to_intended_categories(self):
        """The YAML-declared source keys must hit the map — regression for AAP
        classes normalizing to 'general' because the map said 'aap' while
        aap.yaml declares source: aap2_grafana."""
        from engine.failure_class_loader import get_all_classes

        classes = get_all_classes()
        assert classes, "taxonomy failed to load"
        unmapped = sorted({
            cls["_source"] for cls in classes
            if cls.get("_source") and normalize_raw_class(cls)["category"] == "general"
        })
        # troshka has no category mapping by design; everything else must map
        assert unmapped == ["troshka"], f"sources falling back to 'general': {unmapped}"
        aap = [c for c in classes if c.get("_source") == "aap2_grafana"]
        assert aap, "AAP catalog missing"
        assert all(normalize_raw_class(c)["category"] == "provisioning" for c in aap)
