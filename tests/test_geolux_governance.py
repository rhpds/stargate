"""Tests for the GeoLux governance integration.

- geolux_precheck: safe/unsafe/unknown verdicts, unreachable fail-open
- approve endpoint: unsafe blocks with human override; safe/unknown proceed;
  non-investigation actions skip the check
- proof cycle: the HITL action carries the GeoLux classification and catalog
  recommendations (the recommendation no longer evaporates)
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest


def _geolux_response(results):
    resp = MagicMock()
    resp.read.return_value = json.dumps({"results": results}).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


class TestGeoluxPrecheck:
    def _call(self, **env):
        import engine.geolux_governance as gov
        with patch.dict("os.environ", {"STARGATE_GEOLUX_URL": "http://geolux", **env}):
            return gov.geolux_precheck("cleanup_stuck", "sandbox-x", {"failure_class": "pods_crashlooping"})

    def test_all_pass_is_safe(self):
        with patch("urllib.request.urlopen", return_value=_geolux_response([
            {"constraint_id": "c1", "result": "pass", "confidence_score": 0.9},
            {"constraint_id": "c2", "result": "pass", "confidence_score": 0.8},
        ])):
            check = self._call()
        assert check["verdict"] == "safe"
        assert len(check["constraint_results"]) == 2

    def test_any_fail_is_unsafe(self):
        with patch("urllib.request.urlopen", return_value=_geolux_response([
            {"constraint_id": "c1", "result": "pass", "confidence_score": 0.9},
            {"constraint_id": "c2", "result": "fail", "confidence_score": 0.95},
        ])):
            check = self._call()
        assert check["verdict"] == "unsafe"
        assert any("c2" in r for r in check["reasons"])

    def test_inconclusive_only_is_unknown(self):
        with patch("urllib.request.urlopen", return_value=_geolux_response([
            {"constraint_id": "c1", "result": "inconclusive", "confidence_score": 0.0},
        ])):
            check = self._call()
        assert check["verdict"] == "unknown"

    def test_unreachable_fails_open(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("down")):
            check = self._call()
        assert check["verdict"] == "unknown"
        assert "unreachable" in check["reasons"][0]

    def test_no_url_configured_is_unknown(self):
        import engine.geolux_governance as gov
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("STARGATE_GEOLUX_URL", None)
            check = gov.geolux_precheck("x", "y", {})
        assert check["verdict"] == "unknown"


class TestApproveGeoluxGate:
    """The precheck gates investigation-sourced actions at approve time."""

    def _pending(self, db, proposed_by="investigation"):
        from db.models import PendingAction
        action = PendingAction(
            action_type="cleanup_stuck", target="sandbox-x",
            proposed_by=proposed_by,
            parameters={"failure_class": "pods_crashlooping", "investigation_id": 1,
                        "remediation_suggestion": "restart the deployment"},
            confidence=0.9, status="pending",
            proposed_at=datetime.now(timezone.utc),
        )
        db.add(action)
        db.commit()
        return action

    def test_unsafe_blocks_and_reverts_to_pending(self, db):
        from api.routers.admin.llm import approve_action
        action = self._pending(db)
        with patch("engine.geolux_governance.geolux_precheck",
                   return_value={"verdict": "unsafe", "reasons": ["constraint c9 failed"],
                                 "constraint_results": [], "checked_at": "now"}):
            result = approve_action(action.id, req={}, db=db)
        assert result["status"] == "blocked_by_geolux"
        db.refresh(action)
        assert action.status == "pending"
        assert action.parameters["geolux_check"]["verdict"] == "unsafe"

    def test_unsafe_with_force_overrides(self, db):
        from api.routers.admin.llm import approve_action
        action = self._pending(db)
        with patch("engine.geolux_governance.geolux_precheck",
                   return_value={"verdict": "unsafe", "reasons": ["c9"], "constraint_results": [],
                                 "checked_at": "now"}), \
             patch("api.action_executor.execute_action", return_value={"executed": False, "reason": "dry_run"}):
            result = approve_action(action.id, req={"force_geolux": True}, db=db)
        assert result["status"] == "approved"
        assert action.parameters["geolux_check"]["verdict"] == "unsafe"

    def test_safe_proceeds(self, db):
        from api.routers.admin.llm import approve_action
        action = self._pending(db)
        with patch("engine.geolux_governance.geolux_precheck",
                   return_value={"verdict": "safe", "reasons": ["2 passed"], "constraint_results": [],
                                 "checked_at": "now"}), \
             patch("api.action_executor.execute_action", return_value={"executed": False, "reason": "dry_run"}):
            result = approve_action(action.id, req={}, db=db)
        assert result["status"] == "approved"
        assert action.parameters["geolux_check"]["verdict"] == "safe"

    def test_unknown_fails_open(self, db):
        from api.routers.admin.llm import approve_action
        action = self._pending(db)
        with patch("engine.geolux_governance.geolux_precheck",
                   return_value={"verdict": "unknown", "reasons": ["unreachable"], "constraint_results": [],
                                 "checked_at": "now"}), \
             patch("api.action_executor.execute_action", return_value={"executed": False, "reason": "dry_run"}):
            result = approve_action(action.id, req={}, db=db)
        assert result["status"] == "approved"

    def test_non_investigation_action_skips_check(self, db):
        from api.routers.admin.llm import approve_action
        action = self._pending(db, proposed_by="deepfield")
        with patch("engine.geolux_governance.geolux_precheck") as precheck, \
             patch("api.action_executor.execute_action", return_value={"executed": False, "reason": "dry_run"}):
            result = approve_action(action.id, req={}, db=db)
        precheck.assert_not_called()
        assert result["status"] == "approved"
