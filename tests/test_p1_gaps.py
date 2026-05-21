"""P1 Gap Closure Tests — RED/GREEN TDD.

Tests for: feedback loop closure, prompt versioning, substrate routing
in policy, scan cleanup, continuous re-evaluation.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "stargate-synthetic-client-emulator"))

from tests.conftest import client, db


class TestFeedbackLoopClosure:
    def test_learner_module_exists(self):
        """engine/learner.py exists and is importable."""
        from engine.learner import apply_feedback
        assert callable(apply_feedback)

    def test_feedback_consumed(self, db):
        """Stored feedback is analyzed and produces calibration data."""
        from engine.learner import apply_feedback
        from db.models import LLMFeedback
        from datetime import datetime, timezone

        db.add(LLMFeedback(endpoint="remediation", helpful=True, submitted_at=datetime.now(timezone.utc)))
        db.add(LLMFeedback(endpoint="remediation", helpful=True, submitted_at=datetime.now(timezone.utc)))
        db.add(LLMFeedback(endpoint="remediation", helpful=False, submitted_at=datetime.now(timezone.utc)))
        db.commit()

        result = apply_feedback(db)
        assert "remediation" in result
        assert result["remediation"]["helpful_rate"] > 0

    def test_calibration_data_persisted(self, db):
        """Calibration result is stored for future use."""
        from engine.learner import apply_feedback, get_calibration
        from db.models import LLMFeedback
        from datetime import datetime, timezone

        db.add(LLMFeedback(endpoint="classify", helpful=True, submitted_at=datetime.now(timezone.utc)))
        db.add(LLMFeedback(endpoint="classify", helpful=False, submitted_at=datetime.now(timezone.utc)))
        db.commit()

        apply_feedback(db)
        cal = get_calibration(db, "classify")
        assert cal is not None
        assert "helpful_rate" in cal


class TestPromptVersioning:
    def test_classify_call_has_version(self):
        """Classification LLM call includes prompt_version from YAML."""
        import inspect
        from api.routers import dashboard
        source = inspect.getsource(dashboard.propose_classification)
        assert "prompt_version" in source

    def test_remediation_call_has_version(self):
        """Remediation LLM call includes prompt_version from YAML."""
        import inspect
        from api.routers import dashboard
        source = inspect.getsource(dashboard.dashboard_remediation)
        assert "prompt_version" in source

    def test_executive_summary_call_has_version(self):
        """Executive summary LLM call includes prompt_version from YAML."""
        import inspect
        from api.routers import dashboard
        source = inspect.getsource(dashboard.dashboard_executive_summary)
        assert "prompt_version" in source


class TestSubstrateInPolicy:
    def test_policy_accepts_cluster_states_with_utilization(self):
        """Policy engine can handle cluster states with gaudi/xeon utilization."""
        from engine.policy import generate_recommendations
        result = generate_recommendations(
            labs=[], pools={}, sessions=[],
            cluster_states=[{
                "cluster": "test",
                "avg_cpu": 85,
                "vms_per_node": 90,
                "sandbox_active": 10,
                "gaudi_utilization": 95,
                "xeon6_utilization": 12,
            }],
        )
        types = [r["type"] for r in result["recommendations"]]
        assert "cluster_capacity" in types or "substrate_routing" in types


class TestScanCleanup:
    def test_cleanup_function_exists(self):
        """Scan cleanup function exists."""
        from api.app import _cleanup_scan_history
        assert callable(_cleanup_scan_history)
