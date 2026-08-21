"""Tests for engine/proof_tracker.py — gate progression, state persistence, edge cases."""

import json
import os
import tempfile
from pathlib import Path


class TestLoadSave:
    def _make_tracker(self, tmp_path):
        from engine.proof_tracker import ProofTracker
        return ProofTracker(path=tmp_path / "proof-matrix.json")

    def test_fresh_tracker_creates_default_state(self, tmp_path):
        t = self._make_tracker(tmp_path)
        matrix = t.get_matrix()
        assert matrix["type"] == "proof-matrix"
        assert matrix["failure_classes"] == {}
        assert "updated_at" in matrix

    def test_save_creates_file(self, tmp_path):
        t = self._make_tracker(tmp_path)
        t.record_injection("test_class", {"detail": "test"})
        assert (tmp_path / "proof-matrix.json").exists()

    def test_reload_preserves_state(self, tmp_path):
        from engine.proof_tracker import ProofTracker
        path = tmp_path / "proof-matrix.json"
        t1 = ProofTracker(path=path)
        t1.record_injection("test_class", {})
        t1.record_verification("test_class", True, {})

        t2 = ProofTracker(path=path)
        assert t2.get_status("test_class") == "VERIFIED"
        fc = t2.get_matrix()["failure_classes"]["test_class"]
        assert fc["consecutive_passes"] == 1

    def test_corrupted_file_falls_back_to_default(self, tmp_path):
        from engine.proof_tracker import ProofTracker
        path = tmp_path / "proof-matrix.json"
        path.write_text("not valid json {{{")
        t = ProofTracker(path=path)
        assert t.get_matrix()["failure_classes"] == {}

    def test_missing_parent_dir_created_on_save(self):
        from engine.proof_tracker import ProofTracker
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "subdir" / "deep" / "proof.json"
            t = ProofTracker(path=path)
            t.record_injection("x", {})
            assert path.exists()


class TestRecordVerification:
    def _tracker(self, tmp_path):
        from engine.proof_tracker import ProofTracker
        return ProofTracker(path=tmp_path / "pm.json")

    def test_single_pass_sets_verified(self, tmp_path):
        t = self._tracker(tmp_path)
        t.record_verification("fc1", True, {"verify": "clean"})
        fc = t.get_matrix()["failure_classes"]["fc1"]
        assert fc["status"] == "VERIFIED"
        assert fc["consecutive_passes"] == 1
        assert fc["cycles_completed"] == 1
        assert fc["gate"] == "low_risk_auto"

    def test_failure_resets_consecutive(self, tmp_path):
        t = self._tracker(tmp_path)
        t.record_verification("fc1", True, {})
        t.record_verification("fc1", True, {})
        t.record_verification("fc1", False, {})
        fc = t.get_matrix()["failure_classes"]["fc1"]
        assert fc["status"] == "FAILED"
        assert fc["consecutive_passes"] == 0
        assert fc["cycles_completed"] == 2
        assert fc["cycles_failed"] == 1

    def test_three_passes_reaches_proven(self, tmp_path):
        t = self._tracker(tmp_path)
        for _ in range(3):
            t.record_verification("fc1", True, {})
        fc = t.get_matrix()["failure_classes"]["fc1"]
        assert fc["status"] == "PROVEN"
        assert fc["gate"] == "full_auto"
        assert fc["consecutive_passes"] == 3

    def test_proven_requires_consecutive(self, tmp_path):
        t = self._tracker(tmp_path)
        t.record_verification("fc1", True, {})
        t.record_verification("fc1", True, {})
        t.record_verification("fc1", False, {})
        t.record_verification("fc1", True, {})
        t.record_verification("fc1", True, {})
        fc = t.get_matrix()["failure_classes"]["fc1"]
        assert fc["status"] == "VERIFIED"
        assert fc["consecutive_passes"] == 2
        assert fc["gate"] == "low_risk_auto"

    def test_history_appended(self, tmp_path):
        t = self._tracker(tmp_path)
        t.record_verification("fc1", True, {"check": "pods"})
        t.record_verification("fc1", False, {"check": "pods"})
        fc = t.get_matrix()["failure_classes"]["fc1"]
        assert len(fc["history"]) == 2
        assert fc["history"][0]["clean"] is True
        assert fc["history"][1]["clean"] is False


class TestRecordInvestigationVerified:
    def _tracker(self, tmp_path):
        from engine.proof_tracker import ProofTracker
        return ProofTracker(path=tmp_path / "pm.json")

    def test_sets_investigation_proof_type(self, tmp_path):
        t = self._tracker(tmp_path)
        t.record_investigation_verified("fc1", True, {})
        fc = t.get_matrix()["failure_classes"]["fc1"]
        assert fc["proof_type"] == "investigation"

    def test_three_correct_detections_proves(self, tmp_path):
        t = self._tracker(tmp_path)
        for _ in range(3):
            t.record_investigation_verified("fc1", True, {})
        fc = t.get_matrix()["failure_classes"]["fc1"]
        assert fc["status"] == "PROVEN"
        assert fc["gate"] == "investigation_proven"

    def test_incorrect_detection_resets(self, tmp_path):
        t = self._tracker(tmp_path)
        t.record_investigation_verified("fc1", True, {})
        t.record_investigation_verified("fc1", False, {})
        fc = t.get_matrix()["failure_classes"]["fc1"]
        assert fc["status"] == "FAILED"
        assert fc["consecutive_passes"] == 0
        assert fc["cycles_failed"] == 1

    def test_history_records_detection_correct(self, tmp_path):
        t = self._tracker(tmp_path)
        t.record_investigation_verified("fc1", True, {"det": "ok"})
        entry = t.get_matrix()["failure_classes"]["fc1"]["history"][-1]
        assert entry["event"] == "investigation_verified"
        assert entry["detection_correct"] is True


class TestGateProgression:
    def _tracker(self, tmp_path):
        from engine.proof_tracker import ProofTracker
        return ProofTracker(path=tmp_path / "pm.json")

    def test_injection_sets_injected(self, tmp_path):
        t = self._tracker(tmp_path)
        t.record_injection("fc1", {"pod": "test-pod"})
        assert t.get_status("fc1") == "INJECTED"

    def test_detection_sets_detected(self, tmp_path):
        t = self._tracker(tmp_path)
        t.record_injection("fc1", {})
        t.record_detection("fc1", "fc1")
        assert t.get_status("fc1") == "DETECTED"

    def test_detection_records_correctness(self, tmp_path):
        t = self._tracker(tmp_path)
        t.record_detection("fc1", "fc1")
        t.record_detection("fc2", "wrong_class")
        h1 = t.get_matrix()["failure_classes"]["fc1"]["history"][-1]
        h2 = t.get_matrix()["failure_classes"]["fc2"]["history"][-1]
        assert h1["correct"] is True
        assert h2["correct"] is False

    def test_remediation_success(self, tmp_path):
        t = self._tracker(tmp_path)
        t.record_remediation("fc1", "restart", True, {"rc": 0})
        assert t.get_status("fc1") == "REMEDIATED"

    def test_remediation_failure(self, tmp_path):
        t = self._tracker(tmp_path)
        t.record_remediation("fc1", "restart", False, {"rc": 1})
        assert t.get_status("fc1") == "FAILED"

    def test_full_lifecycle(self, tmp_path):
        t = self._tracker(tmp_path)
        t.record_injection("fc1", {})
        assert t.get_status("fc1") == "INJECTED"
        t.record_detection("fc1", "fc1")
        assert t.get_status("fc1") == "DETECTED"
        t.record_remediation("fc1", "restart", True, {})
        assert t.get_status("fc1") == "REMEDIATED"
        t.record_verification("fc1", True, {})
        assert t.get_status("fc1") == "VERIFIED"


class TestGetMatrix:
    def test_returns_full_data(self, tmp_path):
        from engine.proof_tracker import ProofTracker
        t = ProofTracker(path=tmp_path / "pm.json")
        t.record_verification("a", True, {})
        t.record_verification("b", False, {})
        m = t.get_matrix()
        assert "a" in m["failure_classes"]
        assert "b" in m["failure_classes"]
        assert m["type"] == "proof-matrix"

    def test_get_summary_counts(self, tmp_path):
        from engine.proof_tracker import ProofTracker
        t = ProofTracker(path=tmp_path / "pm.json")
        for _ in range(3):
            t.record_verification("proven_fc", True, {})
        t.record_verification("verified_fc", True, {})
        t.record_verification("failed_fc", False, {})
        t.record_injection("untested_fc", {})
        s = t.get_summary()
        assert s["proven"] == 1
        assert s["verified"] == 1
        assert s["failed"] == 1
        assert s["total"] == 4


class TestCycleResults:
    def test_stores_cycle_result(self, tmp_path):
        from engine.proof_tracker import ProofTracker
        t = ProofTracker(path=tmp_path / "pm.json")
        t.record_cycle_result("fc1", {"phase1": "ok", "phase2": "ok"})
        fc = t.get_matrix()["failure_classes"]["fc1"]
        assert len(fc["cycle_results"]) == 1
        assert fc["cycle_results"][0]["phase1"] == "ok"

    def test_caps_at_five_results(self, tmp_path):
        from engine.proof_tracker import ProofTracker
        t = ProofTracker(path=tmp_path / "pm.json")
        for i in range(7):
            t.record_cycle_result("fc1", {"run": i})
        fc = t.get_matrix()["failure_classes"]["fc1"]
        assert len(fc["cycle_results"]) == 5
        assert fc["cycle_results"][0]["run"] == 2
        assert fc["cycle_results"][-1]["run"] == 6


class TestMultipleFailureClasses:
    def test_independent_tracking(self, tmp_path):
        from engine.proof_tracker import ProofTracker
        t = ProofTracker(path=tmp_path / "pm.json")
        for _ in range(3):
            t.record_verification("fc_a", True, {})
        t.record_verification("fc_b", True, {})
        t.record_verification("fc_b", False, {})
        assert t.get_status("fc_a") == "PROVEN"
        assert t.get_status("fc_b") == "FAILED"

    def test_unknown_class_returns_untested(self, tmp_path):
        from engine.proof_tracker import ProofTracker
        t = ProofTracker(path=tmp_path / "pm.json")
        assert t.get_status("never_seen") == "UNTESTED"
