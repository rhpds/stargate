"""Unit tests for engine/proof_orchestrator.py — the two-phase proof cycle.

Mocks all subprocess/oc calls and external services (GeoLux, DB).
Tests both Phase 1 (inject → detect) and Phase 2 (remediate → verify → cleanup).
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


@pytest.fixture(autouse=True)
def _no_sleep():
    """Prevent real sleeps. Time advances in 0.05s steps — enough for detection loops to run."""
    call_count = 0
    base_time = 1000.0

    def tiny_advance():
        nonlocal call_count
        call_count += 1
        return base_time + call_count * 0.05

    with patch("engine.proof_orchestrator.time.sleep"), \
         patch("engine.proof_orchestrator.time.time", side_effect=tiny_advance):
        yield


@pytest.fixture
def tmp_proof_file(tmp_path):
    """A fresh proof-matrix.json in a temp dir."""
    return tmp_path / "proof-matrix.json"


@pytest.fixture
def mock_tracker(tmp_proof_file):
    """ProofTracker backed by a temp file instead of the real one."""
    with patch("engine.proof_orchestrator.ProofTracker") as cls:
        tracker = MagicMock()
        tracker._data = {"failure_classes": {}}
        tracker.get_status.return_value = "VERIFIED"
        cls.return_value = tracker
        yield tracker


@pytest.fixture
def mock_pipeline():
    with patch("engine.proof_orchestrator.PipelineRubricTracker") as cls:
        pipeline = MagicMock()
        cls.return_value = pipeline
        yield pipeline


def _oc_result(output="", exit_code=0, cmd="oc get pods"):
    return {
        "command": cmd,
        "output": output,
        "exit_code": exit_code,
        "duration_ms": 5,
    }


def _make_inject_result(failure_class="readiness_probe_failed"):
    return {
        "failure_class": failure_class,
        "commands": [_oc_result("deployment.apps/proof-readiness created")],
        "injected_resources": [f"deployment/proof-{failure_class}"],
    }


# ---------------------------------------------------------------------------
# Phase 1: run_proof_cycle — inject + detect
# ---------------------------------------------------------------------------

class TestRunProofCycleInject:
    """Tests for the injection step of Phase 1."""

    @patch("engine.proof_orchestrator._call_geolux", return_value={"skipped": True})
    @patch("engine.proof_orchestrator._load_failure_patterns", return_value={})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_successful_injection(self, mock_inject, mock_oc, mock_patterns, mock_geolux, mock_tracker, mock_pipeline):
        mock_inject.return_value = _make_inject_result()
        mock_oc.return_value = _oc_result("proof-readiness   1/1   Running   0   5s")

        from engine.proof_orchestrator import run_proof_cycle
        result = run_proof_cycle("readiness_probe_failed", mode="manual")

        assert result["failure_class"] == "readiness_probe_failed"
        assert result["steps"]["inject"]["status"] == "success"
        mock_inject.assert_called_once()
        mock_tracker.record_injection.assert_called_once()

    @patch("engine.proof_orchestrator._call_geolux", return_value={"skipped": True})
    @patch("engine.proof_orchestrator._load_failure_patterns", return_value={})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_injection_failure_returns_error(self, mock_inject, mock_oc, mock_patterns, mock_geolux, mock_tracker, mock_pipeline):
        mock_inject.return_value = {"error": "namespace blocked"}
        mock_oc.return_value = _oc_result()

        from engine.proof_orchestrator import run_proof_cycle
        result = run_proof_cycle("readiness_probe_failed", mode="manual")

        assert result["steps"]["inject"]["status"] == "failed"
        assert result["success"] is False

    @patch("engine.proof_orchestrator._call_geolux", return_value={"skipped": True})
    @patch("engine.proof_orchestrator._load_failure_patterns", return_value={})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_injection_exception_returns_error(self, mock_inject, mock_oc, mock_patterns, mock_geolux, mock_tracker, mock_pipeline):
        mock_inject.side_effect = ValueError("test namespace refused")
        mock_oc.return_value = _oc_result()

        from engine.proof_orchestrator import run_proof_cycle
        result = run_proof_cycle("readiness_probe_failed", mode="manual")

        assert result["steps"]["inject"]["status"] == "failed"
        assert "test namespace refused" in result["steps"]["inject"]["error"]


class TestRunProofCycleDetect:
    """Tests for the detection polling step of Phase 1."""

    @patch("engine.proof_orchestrator.DETECTION_TIMEOUT", 1)
    @patch("engine.proof_orchestrator.DETECTION_POLL_INTERVAL", 0.1)
    @patch("engine.proof_orchestrator._call_geolux", return_value={"skipped": True})
    @patch("engine.proof_orchestrator._load_failure_patterns", return_value={})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_detection_success_on_pod_status(self, mock_inject, mock_oc, mock_patterns, mock_geolux, mock_tracker, mock_pipeline):
        mock_inject.return_value = _make_inject_result("pods_crashlooping")
        mock_oc.return_value = _oc_result("proof-crash   0/1   CrashLoopBackOff   3   30s")

        from engine.proof_orchestrator import run_proof_cycle
        result = run_proof_cycle("pods_crashlooping", mode="manual")

        assert result["steps"]["detect"]["status"] == "detected"
        assert result["steps"]["detect"]["detected_class"] == "pods_crashlooping"
        assert result["steps"]["detect"]["correct"] is True

    @patch("engine.proof_orchestrator.DETECTION_TIMEOUT", 0.5)
    @patch("engine.proof_orchestrator.DETECTION_POLL_INTERVAL", 0.1)
    @patch("engine.proof_orchestrator._call_geolux", return_value={"skipped": True})
    @patch("engine.proof_orchestrator._load_failure_patterns", return_value={})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_detection_timeout(self, mock_inject, mock_oc, mock_patterns, mock_geolux, mock_tracker, mock_pipeline):
        mock_inject.return_value = _make_inject_result()
        mock_oc.return_value = _oc_result("proof-readiness   1/1   Running   0   5s")

        from engine.proof_orchestrator import run_proof_cycle
        result = run_proof_cycle("readiness_probe_failed", mode="manual")

        assert result["steps"]["detect"]["status"] == "timeout"
        assert result["steps"]["detect"]["correct"] is False

    @patch("engine.proof_orchestrator.DETECTION_TIMEOUT", 1)
    @patch("engine.proof_orchestrator.DETECTION_POLL_INTERVAL", 0.1)
    @patch("engine.proof_orchestrator._call_geolux", return_value={"skipped": True})
    @patch("engine.proof_orchestrator._load_failure_patterns", return_value={"quota_exceeded": "exceeded quota"})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_detection_via_events(self, mock_inject, mock_oc, mock_patterns, mock_geolux, mock_tracker, mock_pipeline):
        """Detection via event pattern from failure-classes YAML."""
        mock_inject.return_value = _make_inject_result("quota_exceeded")

        def oc_side_effect(args, kubeconfig=""):
            args_str = " ".join(args)
            # The YAML pattern check uses get events --sort-by WITHOUT --field-selector
            if "events" in args and "--sort-by" in args_str and "--field-selector" not in args_str:
                return _oc_result("Warning  FailedCreate  exceeded quota for resource")
            # The check-based detection uses events WITH --field-selector — return no match
            if "events" in args:
                return _oc_result("")
            # Pods — return Running so the pod-based check doesn't trigger first
            return _oc_result("proof-quota  1/1  Running  0  5s")

        mock_oc.side_effect = oc_side_effect

        from engine.proof_orchestrator import run_proof_cycle
        result = run_proof_cycle("quota_exceeded", mode="manual")

        assert result["steps"]["detect"]["status"] == "detected"
        assert result["steps"]["detect"]["source"] == "cluster_events"


class TestRunProofCycleHITL:
    """Tests for the HITL gate in manual mode."""

    @patch("engine.proof_orchestrator.DETECTION_TIMEOUT", 0.5)
    @patch("engine.proof_orchestrator.DETECTION_POLL_INTERVAL", 0.1)
    @patch("engine.proof_orchestrator._call_geolux", return_value={"skipped": True})
    @patch("engine.proof_orchestrator._load_failure_patterns", return_value={})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_manual_mode_creates_pending_action(self, mock_inject, mock_oc, mock_patterns, mock_geolux, mock_tracker, mock_pipeline, db):
        mock_inject.return_value = _make_inject_result("pods_crashlooping")
        mock_oc.return_value = _oc_result("proof-crash   0/1   CrashLoopBackOff   3   30s")

        from engine.proof_orchestrator import run_proof_cycle
        result = run_proof_cycle("pods_crashlooping", mode="manual", db=db)

        assert result["awaiting_approval"] is True
        assert result["steps"]["remediate"]["status"] == "awaiting_hitl_approval"

        from db.models import PendingAction
        pending = db.query(PendingAction).first()
        assert pending is not None
        assert pending.action_type == "proof_pods_crashlooping"
        assert pending.status == "pending"


class TestRunProofCycleAutoMode:
    """Auto mode should chain directly into Phase 2."""

    @patch("engine.proof_orchestrator.DETECTION_TIMEOUT", 0.5)
    @patch("engine.proof_orchestrator.DETECTION_POLL_INTERVAL", 0.1)
    @patch("engine.proof_orchestrator._update_geolux_hypotheses")
    @patch("engine.proof_orchestrator._call_geolux", return_value={"skipped": True})
    @patch("engine.proof_orchestrator._load_failure_patterns", return_value={})
    @patch("engine.proof_orchestrator.cleanup_all", return_value={"commands": [], "deleted": []})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_auto_mode_runs_phase2(self, mock_inject, mock_oc, mock_cleanup, mock_patterns,
                                    mock_geolux, mock_update_gl, mock_tracker, mock_pipeline):
        mock_inject.return_value = _make_inject_result("pods_crashlooping")
        mock_oc.return_value = _oc_result("proof-crash   0/1   CrashLoopBackOff   3   30s")

        with patch("engine.oc_executor.execute_oc_action", return_value={"success": True, "commands": [], "action_type": "delete_pod"}) as mock_exec:
            from engine.proof_orchestrator import run_proof_cycle
            result = run_proof_cycle("pods_crashlooping", mode="auto")

        assert "remediate" in result["steps"]
        assert "verify" in result["steps"]
        assert "cleanup" in result["steps"]


# ---------------------------------------------------------------------------
# Phase 2: continue_proof_cycle — remediate + verify + cleanup
# ---------------------------------------------------------------------------

class TestContinueProofCycleRemediation:
    """Tests for the remediation step in Phase 2."""

    @patch("engine.proof_orchestrator._update_geolux_hypotheses")
    @patch("engine.proof_orchestrator.cleanup_all", return_value={"commands": [], "deleted": []})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_remediation_success(self, mock_inject, mock_oc, mock_cleanup, mock_update_gl, mock_tracker, mock_pipeline):
        mock_inject.return_value = _make_inject_result()
        mock_oc.return_value = _oc_result("proof-readiness   1/1   Running   0   5s")

        with patch("engine.oc_executor.execute_oc_action", return_value={"success": True, "commands": [_oc_result("pod deleted")], "action_type": "rollout_restart"}):
            from engine.proof_orchestrator import continue_proof_cycle
            result = continue_proof_cycle("readiness_probe_failed")

        assert result["steps"]["remediate"]["status"] == "success"
        assert result["steps"]["remediate"]["executed"] is True
        mock_tracker.record_remediation.assert_called_once()

    @patch("engine.proof_orchestrator._update_geolux_hypotheses")
    @patch("engine.proof_orchestrator.cleanup_all", return_value={"commands": [], "deleted": []})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_remediation_failure(self, mock_inject, mock_oc, mock_cleanup, mock_update_gl, mock_tracker, mock_pipeline):
        mock_inject.return_value = _make_inject_result()
        mock_oc.return_value = _oc_result("proof-readiness   0/1   CrashLoopBackOff   5   2m")

        with patch("engine.oc_executor.execute_oc_action", return_value={"success": False, "commands": [], "action_type": "rollout_restart"}):
            from engine.proof_orchestrator import continue_proof_cycle
            result = continue_proof_cycle("readiness_probe_failed")

        assert result["steps"]["remediate"]["status"] == "failed"

    @patch("engine.proof_orchestrator._update_geolux_hypotheses")
    @patch("engine.proof_orchestrator.cleanup_all", return_value={"commands": [], "deleted": []})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_remediation_exception(self, mock_inject, mock_oc, mock_cleanup, mock_update_gl, mock_tracker, mock_pipeline):
        mock_inject.return_value = _make_inject_result()
        mock_oc.return_value = _oc_result()

        with patch("engine.oc_executor.execute_oc_action", side_effect=RuntimeError("executor crashed")):
            from engine.proof_orchestrator import continue_proof_cycle
            result = continue_proof_cycle("readiness_probe_failed")

        assert result["steps"]["remediate"]["status"] == "failed"
        assert "executor crashed" in result["steps"]["remediate"]["error"]


class TestContinueProofCycleVerify:
    """Tests for the verification step in Phase 2."""

    @patch("engine.proof_orchestrator._update_geolux_hypotheses")
    @patch("engine.proof_orchestrator.cleanup_all", return_value={"commands": [], "deleted": []})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_verify_clean_pods(self, mock_inject, mock_oc, mock_cleanup, mock_update_gl, mock_tracker, mock_pipeline):
        mock_inject.return_value = _make_inject_result()
        mock_oc.return_value = _oc_result("proof-readiness   1/1   Running   0   30s")

        with patch("engine.oc_executor.execute_oc_action", return_value={"success": True, "commands": [], "action_type": "rollout_restart"}):
            with patch("engine.proof_orchestrator.time.sleep"):
                from engine.proof_orchestrator import continue_proof_cycle
                result = continue_proof_cycle("readiness_probe_failed")

        assert result["steps"]["verify"]["status"] == "clean"
        assert result["steps"]["verify"]["clean"] is True
        assert result["success"] is True
        assert result["proof_mode"] == "remediation"

    @patch("engine.proof_orchestrator._update_geolux_hypotheses")
    @patch("engine.proof_orchestrator.cleanup_all", return_value={"commands": [], "deleted": []})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_verify_failed_pods_still_broken(self, mock_inject, mock_oc, mock_cleanup, mock_update_gl, mock_tracker, mock_pipeline):
        mock_inject.return_value = _make_inject_result()
        mock_oc.return_value = _oc_result("proof-crash   0/1   CrashLoopBackOff   5   3m")

        with patch("engine.oc_executor.execute_oc_action", return_value={"success": True, "commands": [], "action_type": "delete_pod"}):
            with patch("engine.proof_orchestrator.time.sleep"):
                from engine.proof_orchestrator import continue_proof_cycle
                result = continue_proof_cycle("readiness_probe_failed")

        assert result["steps"]["verify"]["status"] == "failed"
        assert result["steps"]["verify"]["clean"] is False

    @patch("engine.proof_orchestrator._update_geolux_hypotheses")
    @patch("engine.proof_orchestrator.cleanup_all", return_value={"commands": [], "deleted": []})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_verify_skipped_when_remediation_failed(self, mock_inject, mock_oc, mock_cleanup, mock_update_gl, mock_tracker, mock_pipeline):
        mock_inject.return_value = _make_inject_result()
        mock_oc.return_value = _oc_result()

        with patch("engine.oc_executor.execute_oc_action", return_value={"success": False, "commands": [], "action_type": "rollout_restart"}):
            from engine.proof_orchestrator import continue_proof_cycle
            result = continue_proof_cycle("readiness_probe_failed")

        assert result["steps"]["verify"]["status"] == "skipped"


class TestContinueProofCycleCleanup:
    """Tests for the cleanup step in Phase 2."""

    @patch("engine.proof_orchestrator._update_geolux_hypotheses")
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_cleanup_success(self, mock_inject, mock_oc, mock_update_gl, mock_tracker, mock_pipeline):
        mock_inject.return_value = _make_inject_result()
        mock_oc.return_value = _oc_result("proof-readiness   1/1   Running   0   30s")

        with patch("engine.proof_orchestrator.cleanup_all", return_value={"commands": [_oc_result("deleted")], "deleted": ["deployment/proof-readiness"]}):
            with patch("engine.oc_executor.execute_oc_action", return_value={"success": True, "commands": [], "action_type": "rollout_restart"}):
                with patch("engine.proof_orchestrator.time.sleep"):
                    from engine.proof_orchestrator import continue_proof_cycle
                    result = continue_proof_cycle("readiness_probe_failed")

        assert result["steps"]["cleanup"]["status"] == "success"
        assert "deployment/proof-readiness" in result["steps"]["cleanup"]["deleted"]

    @patch("engine.proof_orchestrator._update_geolux_hypotheses")
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_cleanup_failure_captured(self, mock_inject, mock_oc, mock_update_gl, mock_tracker, mock_pipeline):
        mock_inject.return_value = _make_inject_result()
        mock_oc.return_value = _oc_result()

        with patch("engine.proof_orchestrator.cleanup_all", side_effect=RuntimeError("cleanup timeout")):
            with patch("engine.oc_executor.execute_oc_action", return_value={"success": False, "commands": [], "action_type": "rollout_restart"}):
                from engine.proof_orchestrator import continue_proof_cycle
                result = continue_proof_cycle("readiness_probe_failed")

        assert result["steps"]["cleanup"]["status"] == "failed"
        assert "cleanup timeout" in result["steps"]["cleanup"]["error"]


# ---------------------------------------------------------------------------
# Investigation vs. remediation proof mode
# ---------------------------------------------------------------------------

class TestProofMode:
    """Proof mode determination — remediation vs investigation."""

    @patch("engine.proof_orchestrator._update_geolux_hypotheses")
    @patch("engine.proof_orchestrator.cleanup_all", return_value={"commands": [], "deleted": []})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_remediation_mode_when_verify_clean(self, mock_inject, mock_oc, mock_cleanup, mock_update_gl, mock_tracker, mock_pipeline):
        mock_inject.return_value = _make_inject_result()
        mock_oc.return_value = _oc_result("proof-readiness   1/1   Running   0   30s")

        with patch("engine.oc_executor.execute_oc_action", return_value={"success": True, "commands": [], "action_type": "rollout_restart"}):
            with patch("engine.proof_orchestrator.time.sleep"):
                from engine.proof_orchestrator import continue_proof_cycle
                result = continue_proof_cycle("readiness_probe_failed")

        assert result["proof_mode"] == "remediation"
        assert result["success"] is True
        mock_tracker.record_verification.assert_called_once_with("readiness_probe_failed", True, {"pods": mock_oc.return_value["output"][:500]})

    @patch("engine.proof_orchestrator._update_geolux_hypotheses")
    @patch("engine.proof_orchestrator.cleanup_all", return_value={"commands": [], "deleted": []})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_investigation_mode_when_detection_correct_but_verify_fails(self, mock_inject, mock_oc, mock_cleanup, mock_update_gl, mock_tracker, mock_pipeline):
        """If detection was correct but remediation didn't fix it → investigation mode."""
        mock_inject.return_value = _make_inject_result("pods_crashlooping")
        mock_oc.return_value = _oc_result("proof-crash   0/1   CrashLoopBackOff   5   3m")

        mock_tracker._data = {
            "failure_classes": {
                "pods_crashlooping": {
                    "cycle_results": [{
                        "steps": {
                            "detect": {"correct": True, "status": "detected"},
                            "inject": {"injected_resources": ["deployment/proof-crash"]},
                        }
                    }]
                }
            }
        }

        with patch("engine.oc_executor.execute_oc_action", return_value={"success": True, "commands": [], "action_type": "delete_pod"}):
            with patch("engine.proof_orchestrator.time.sleep"):
                from engine.proof_orchestrator import continue_proof_cycle
                result = continue_proof_cycle("pods_crashlooping")

        assert result["proof_mode"] == "investigation"
        assert result["success"] is True
        mock_tracker.record_investigation_verified.assert_called_once()

    @patch("engine.proof_orchestrator._update_geolux_hypotheses")
    @patch("engine.proof_orchestrator.cleanup_all", return_value={"commands": [], "deleted": []})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_failed_mode_when_detection_wrong_and_verify_fails(self, mock_inject, mock_oc, mock_cleanup, mock_update_gl, mock_tracker, mock_pipeline):
        mock_inject.return_value = _make_inject_result()
        mock_oc.return_value = _oc_result("proof-readiness   0/1   Error   1   2m")

        mock_tracker._data = {
            "failure_classes": {
                "readiness_probe_failed": {
                    "cycle_results": [{
                        "steps": {
                            "detect": {"correct": False, "status": "timeout"},
                            "inject": {"injected_resources": []},
                        }
                    }]
                }
            }
        }

        with patch("engine.oc_executor.execute_oc_action", return_value={"success": True, "commands": [], "action_type": "rollout_restart"}):
            with patch("engine.proof_orchestrator.time.sleep"):
                from engine.proof_orchestrator import continue_proof_cycle
                result = continue_proof_cycle("readiness_probe_failed")

        assert result["proof_mode"] == "failed"
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Re-injection in Phase 2
# ---------------------------------------------------------------------------

class TestPhase2Reinject:
    """Phase 2 re-injects the failure if the original resources are gone."""

    @patch("engine.proof_orchestrator._update_geolux_hypotheses")
    @patch("engine.proof_orchestrator.cleanup_all", return_value={"commands": [], "deleted": []})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_reinjects_when_pods_gone(self, mock_inject, mock_oc, mock_cleanup, mock_update_gl, mock_tracker, mock_pipeline):
        mock_inject.return_value = _make_inject_result()
        mock_oc.return_value = _oc_result("")  # empty namespace — pods are gone

        mock_tracker._data = {
            "failure_classes": {
                "readiness_probe_failed": {
                    "cycle_results": [{
                        "steps": {
                            "inject": {"injected_resources": ["deployment/proof-readiness"]},
                            "detect": {"correct": True},
                        }
                    }]
                }
            }
        }

        with patch("engine.oc_executor.execute_oc_action", return_value={"success": False, "commands": [], "action_type": "rollout_restart"}):
            with patch("engine.proof_orchestrator.time.sleep"):
                from engine.proof_orchestrator import continue_proof_cycle
                result = continue_proof_cycle("readiness_probe_failed")

        # inject_failure called for re-injection
        assert mock_inject.call_count >= 1

    @patch("engine.proof_orchestrator._update_geolux_hypotheses")
    @patch("engine.proof_orchestrator.cleanup_all", return_value={"commands": [], "deleted": []})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_no_reinject_when_pods_present(self, mock_inject, mock_oc, mock_cleanup, mock_update_gl, mock_tracker, mock_pipeline):
        mock_inject.return_value = _make_inject_result()
        mock_oc.return_value = _oc_result("proof-readiness-probe-failed   1/1   Running   0   30s")

        mock_tracker._data = {
            "failure_classes": {
                "readiness_probe_failed": {
                    "cycle_results": [{
                        "steps": {
                            "inject": {"injected_resources": ["deployment/proof-readiness-probe-failed"]},
                            "detect": {"correct": True},
                        }
                    }]
                }
            }
        }

        with patch("engine.oc_executor.execute_oc_action", return_value={"success": True, "commands": [], "action_type": "rollout_restart"}):
            with patch("engine.proof_orchestrator.time.sleep"):
                from engine.proof_orchestrator import continue_proof_cycle
                result = continue_proof_cycle("readiness_probe_failed")

        # inject_failure should NOT be called — pods are still there
        mock_inject.assert_not_called()


# ---------------------------------------------------------------------------
# GeoLux integration
# ---------------------------------------------------------------------------

class TestGeoLuxIntegration:
    """GeoLux calls during proof cycle."""

    @patch("engine.proof_orchestrator.DETECTION_TIMEOUT", 0.5)
    @patch("engine.proof_orchestrator.DETECTION_POLL_INTERVAL", 0.1)
    @patch("engine.proof_orchestrator._load_failure_patterns", return_value={})
    @patch("engine.proof_orchestrator._oc")
    @patch("engine.proof_orchestrator.inject_failure")
    def test_geolux_result_attached(self, mock_inject, mock_oc, mock_patterns, mock_tracker, mock_pipeline):
        mock_inject.return_value = _make_inject_result()
        mock_oc.return_value = _oc_result()

        with patch("engine.proof_orchestrator._call_geolux", return_value={"hypothesis": {"processed": True}, "status": "success"}) as mock_gl:
            from engine.proof_orchestrator import run_proof_cycle
            result = run_proof_cycle("readiness_probe_failed", mode="manual")

        assert "geolux" in result
        assert result["geolux"]["status"] == "success"

    def test_call_geolux_skipped_without_url(self):
        with patch.dict("os.environ", {"STARGATE_GEOLUX_URL": ""}, clear=False):
            from engine.proof_orchestrator import _call_geolux
            result = _call_geolux("readiness_probe_failed", "stargate-test", "readiness_probe_failed", [], "")
            assert result["skipped"] is True


# ---------------------------------------------------------------------------
# _oc helper
# ---------------------------------------------------------------------------

class TestOcHelper:

    @patch("subprocess.run")
    def test_oc_returns_trace_dict(self, mock_run):
        mock_run.return_value = MagicMock(stdout="pod/test", stderr="", returncode=0)
        from engine.proof_orchestrator import _oc
        result = _oc(["get", "pods", "-n", "test"])
        assert result["command"] == "oc get pods -n test"
        assert result["exit_code"] == 0
        assert "duration_ms" in result

    @patch("subprocess.run")
    def test_oc_returns_stderr_on_failure(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", stderr="forbidden", returncode=1)
        from engine.proof_orchestrator import _oc
        result = _oc(["get", "pods"])
        assert "forbidden" in result["output"]
        assert result["exit_code"] == 1

    @patch("subprocess.run")
    def test_oc_uses_kubeconfig_env(self, mock_run):
        mock_run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
        from engine.proof_orchestrator import _oc
        _oc(["get", "pods"], kubeconfig="/path/to/kube")
        env = mock_run.call_args[1]["env"]
        assert env["KUBECONFIG"] == "/path/to/kube"
