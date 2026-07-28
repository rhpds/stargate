"""RED/GREEN TDD: tests written FIRST.

Tests for the synthetic remediation proof system.
All operations scoped to stargate-test namespace.
"""

import pytest
from unittest.mock import patch, MagicMock
from engine.failure_injector import ALLOWED_NAMESPACE, _validate_namespace, INJECTORS
from engine.proof_tracker import ProofTracker


class TestNamespaceSafety:
    def test_validate_namespace_allows_test(self):
        _validate_namespace(ALLOWED_NAMESPACE)  # Should not raise

    def test_validate_namespace_blocks_production(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            _validate_namespace("production-namespace")

    def test_validate_namespace_blocks_openshift(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            _validate_namespace("openshift-monitoring")

    def test_validate_namespace_blocks_sandbox(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            _validate_namespace("sandbox-abc-ocp4-cluster")

    def test_validate_namespace_blocks_stargate(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            _validate_namespace("stargate")


class TestInjectorRegistry:
    def test_all_high_impact_classes_have_injectors(self):
        expected = ["pods_crashlooping", "readiness_probe_failed", "image_pull_backoff", "claim_misbound", "oom_killed", "quota_exceeded", "scheduling_failed"]
        for fc in expected:
            assert fc in INJECTORS, f"Missing injector for {fc}"

    def test_inject_failure_rejects_unknown_class(self):
        from engine.failure_injector import inject_failure
        result = inject_failure("nonexistent_class", ALLOWED_NAMESPACE)
        assert "error" in result


class TestProofTracker:
    def test_initial_status_is_untested(self, tmp_path):
        tracker = ProofTracker(path=tmp_path / "proof.json")
        assert tracker.get_status("pods_crashlooping") == "UNTESTED"

    def test_injection_moves_to_injected(self, tmp_path):
        tracker = ProofTracker(path=tmp_path / "proof.json")
        tracker.record_injection("pods_crashlooping", {"resources": ["deployment/test"]})
        assert tracker.get_status("pods_crashlooping") == "INJECTED"

    def test_detection_moves_to_detected(self, tmp_path):
        tracker = ProofTracker(path=tmp_path / "proof.json")
        tracker.record_injection("pods_crashlooping", {})
        tracker.record_detection("pods_crashlooping", "pods_crashlooping")
        assert tracker.get_status("pods_crashlooping") == "DETECTED"

    def test_remediation_moves_to_remediated(self, tmp_path):
        tracker = ProofTracker(path=tmp_path / "proof.json")
        tracker.record_injection("pods_crashlooping", {})
        tracker.record_remediation("pods_crashlooping", "restart", True, {})
        assert tracker.get_status("pods_crashlooping") == "REMEDIATED"

    def test_verification_moves_to_verified(self, tmp_path):
        tracker = ProofTracker(path=tmp_path / "proof.json")
        tracker.record_injection("pods_crashlooping", {})
        tracker.record_verification("pods_crashlooping", True, {})
        assert tracker.get_status("pods_crashlooping") == "VERIFIED"

    def test_three_cycles_reaches_proven(self, tmp_path):
        tracker = ProofTracker(path=tmp_path / "proof.json")
        for _ in range(3):
            tracker.record_injection("pods_crashlooping", {})
            tracker.record_verification("pods_crashlooping", True, {})
        assert tracker.get_status("pods_crashlooping") == "PROVEN"

    def test_failure_resets_consecutive(self, tmp_path):
        tracker = ProofTracker(path=tmp_path / "proof.json")
        tracker.record_verification("pods_crashlooping", True, {})
        tracker.record_verification("pods_crashlooping", True, {})
        tracker.record_verification("pods_crashlooping", False, {})  # Fail
        assert tracker.get_status("pods_crashlooping") == "FAILED"
        tracker.record_verification("pods_crashlooping", True, {})
        assert tracker.get_status("pods_crashlooping") != "PROVEN"  # Reset

    def test_matrix_summary(self, tmp_path):
        tracker = ProofTracker(path=tmp_path / "proof.json")
        tracker.record_injection("a", {})
        tracker.record_injection("b", {})
        s = tracker.get_summary()
        assert s["total"] == 2

    def test_proven_sets_full_auto_gate(self, tmp_path):
        tracker = ProofTracker(path=tmp_path / "proof.json")
        for _ in range(3):
            tracker.record_verification("test_class", True, {})
        fc = tracker._data["failure_classes"]["test_class"]
        assert fc["gate"] == "full_auto"
