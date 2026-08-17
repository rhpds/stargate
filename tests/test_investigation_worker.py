"""Tests for the investigation queue worker (Celery task)."""

import pytest
from unittest.mock import patch, MagicMock


class TestRunSingleInvestigation:
    def test_complete_lifecycle(self, db):
        from db.repository import create_investigation, get_investigation
        create_investigation(
            db, job_id="inv-worker01", lab_code="sandbox-ab12c-ocp4",
            cluster="east", failure_class="pods_crashlooping",
            trigger_type="auto",
        )

        mock_result = {
            "analysis": "Root cause: showroom container image pull failure",
            "tool_calls": [{"tool": "oc_read", "args": {"command": "get pods"}, "result_preview": "...", "iteration": 0}],
            "iterations": 3,
            "error": None,
            "fallback": False,
        }

        with patch("engine.investigation_agent.run_investigation", return_value=mock_result), \
             patch.dict("os.environ", {"STARGATE_AGENT_MODEL": "claude-sonnet-4-6"}), \
             patch("api.routers._shared._event_bus", MagicMock()):
            from tasks.maintenance import _run_single_investigation
            rec = get_investigation(db, "inv-worker01")
            _run_single_investigation(rec, db)

        result = get_investigation(db, "inv-worker01")
        assert result.status == "complete"
        assert "image pull failure" in result.analysis
        assert result.iterations == 3
        assert result.model_used == "claude-sonnet-4-6"

    def test_error_lifecycle(self, db):
        from db.repository import create_investigation, get_investigation, fail_investigation
        create_investigation(
            db, job_id="inv-worker02", lab_code="sandbox-ab12c-ocp4",
            cluster="east", failure_class="pods_crashlooping",
        )

        with patch("engine.investigation_agent.run_investigation", side_effect=RuntimeError("LLM connection refused")):
            from tasks.maintenance import _run_single_investigation
            rec = get_investigation(db, "inv-worker02")
            try:
                _run_single_investigation(rec, db)
            except RuntimeError:
                fail_investigation(db, "inv-worker02", "LLM connection refused")

        result = get_investigation(db, "inv-worker02")
        assert result.status == "error"
        assert "connection refused" in result.error
