"""Tests for engine.namespace_matcher — fnmatch-based namespace-to-lab mapping."""

from engine.namespace_matcher import match_namespace_to_lab


SAMPLE_MAPPINGS = [
    {"namespace_pattern": "ocp4-*-rhdp-*", "lab_code": "ocp4-rhdp"},
    {"namespace_pattern": "summit-*-lab-*", "lab_code": "summit-lab"},
    {"namespace_pattern": "demo-aap-*", "lab_code": "aap-demo"},
    {"namespace_pattern": "sandbox-*", "lab_code": "sandbox"},
]


class TestMatchNamespaceToLab:
    """Tests for match_namespace_to_lab()."""

    def test_exact_glob_match(self):
        result = match_namespace_to_lab("ocp4-cluster1-rhdp-001", SAMPLE_MAPPINGS)
        assert result == "ocp4-rhdp"

    def test_summit_pattern_match(self):
        result = match_namespace_to_lab("summit-2026-lab-42", SAMPLE_MAPPINGS)
        assert result == "summit-lab"

    def test_aap_prefix_match(self):
        result = match_namespace_to_lab("demo-aap-staging", SAMPLE_MAPPINGS)
        assert result == "aap-demo"

    def test_sandbox_wildcard_match(self):
        result = match_namespace_to_lab("sandbox-xyz-123", SAMPLE_MAPPINGS)
        assert result == "sandbox"

    def test_no_match_returns_none(self):
        result = match_namespace_to_lab("kube-system", SAMPLE_MAPPINGS)
        assert result is None

    def test_empty_namespace_no_match(self):
        result = match_namespace_to_lab("", SAMPLE_MAPPINGS)
        assert result is None

    def test_empty_mappings_returns_none(self):
        result = match_namespace_to_lab("ocp4-cluster1-rhdp-001", [])
        assert result is None

    def test_empty_pattern_skipped(self):
        mappings = [
            {"namespace_pattern": "", "lab_code": "should-not-match"},
            {"namespace_pattern": "real-*", "lab_code": "real"},
        ]
        result = match_namespace_to_lab("real-ns", mappings)
        assert result == "real"

    def test_missing_pattern_key_skipped(self):
        mappings = [
            {"lab_code": "no-pattern"},
            {"namespace_pattern": "valid-*", "lab_code": "valid"},
        ]
        result = match_namespace_to_lab("valid-ns", mappings)
        assert result == "valid"

    def test_first_match_wins(self):
        """When multiple patterns match, the first one wins."""
        mappings = [
            {"namespace_pattern": "demo-*", "lab_code": "generic-demo"},
            {"namespace_pattern": "demo-aap-*", "lab_code": "aap-demo"},
        ]
        result = match_namespace_to_lab("demo-aap-prod", mappings)
        assert result == "generic-demo"

    def test_case_sensitivity(self):
        """fnmatch is case-sensitive on Unix."""
        result = match_namespace_to_lab("OCP4-cluster1-RHDP-001", SAMPLE_MAPPINGS)
        assert result is None

    def test_missing_lab_code_returns_none(self):
        mappings = [{"namespace_pattern": "test-*"}]
        result = match_namespace_to_lab("test-ns", mappings)
        assert result is None
