"""Tests for per-lab auto-remediation config — DB model, repository, execution gate, catalog max_risk."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


class TestLabRemediationConfigModel:
    """LabRemediationConfig ORM model exists with required columns."""

    def test_model_importable(self):
        from db.models import LabRemediationConfig
        assert LabRemediationConfig.__tablename__ == "lab_remediation_config"

    def test_model_has_required_columns(self):
        from db.models import LabRemediationConfig
        cols = {c.name for c in LabRemediationConfig.__table__.columns}
        assert "lab_code" in cols
        assert "execution_mode" in cols
        assert "max_actions_per_hour" in cols
        assert "enabled_by" in cols
        assert "enabled_at" in cols
        assert "notes" in cols

    def test_default_execution_mode(self):
        from db.models import LabRemediationConfig
        col = LabRemediationConfig.__table__.columns["execution_mode"]
        assert col.default.arg == "recommend_only"

    def test_default_max_actions(self):
        from db.models import LabRemediationConfig
        col = LabRemediationConfig.__table__.columns["max_actions_per_hour"]
        assert col.default.arg == 5


class TestCatalogMaxRiskFilter:
    """get_commands_for_action respects max_risk parameter."""

    def test_max_risk_parameter_accepted(self):
        from engine.catalog_loader import get_commands_for_action
        from engine.models import RemediationRisk
        result = get_commands_for_action("cleanup_stuck", "test-ns", {}, max_risk=RemediationRisk.LOW)
        assert isinstance(result, list)

    def test_max_risk_none_returns_all_non_recommend(self):
        from engine.catalog_loader import get_commands_for_action
        all_cmds = get_commands_for_action("pool_exhaustion", "test-ns", {"pool": "p"})
        assert isinstance(all_cmds, list)

    def test_max_risk_low_filters_medium(self):
        from engine.catalog_loader import get_commands_for_action
        from engine.models import RemediationRisk
        low_cmds = get_commands_for_action("pool_exhaustion", "test-ns", {"pool": "p"}, max_risk=RemediationRisk.LOW)
        all_cmds = get_commands_for_action("pool_exhaustion", "test-ns", {"pool": "p"})
        assert len(low_cmds) <= len(all_cmds)

    def test_risk_order_correct(self):
        from engine.catalog_loader import RISK_ORDER
        from engine.models import RemediationRisk
        assert RISK_ORDER[RemediationRisk.LOW] < RISK_ORDER[RemediationRisk.MEDIUM]
        assert RISK_ORDER[RemediationRisk.MEDIUM] < RISK_ORDER[RemediationRisk.HIGH]
        assert RISK_ORDER[RemediationRisk.HIGH] < RISK_ORDER[RemediationRisk.CRITICAL]


class TestExecutionGate:
    """execute_action respects per-lab execution mode (Gate 0)."""

    def test_recommend_only_blocks_execution(self):
        from api.action_executor import execute_action
        with patch("api.action_executor._get_lab_execution_mode", return_value="recommend_only"):
            result = execute_action(
                action_type="cleanup_stuck",
                target="some-namespace",
                parameters={},
                lab_code="test-lab",
            )
        assert result["executed"] is False
        assert result["reason"] == "recommend_only"

    def test_test_namespace_always_passes_gate0(self):
        from api.action_executor import execute_action
        with patch("api.routers._shared.TEST_NAMESPACE", "stargate-test"), \
             patch("api.routers._shared._dry_run_enabled", True):
            result = execute_action(
                action_type="cleanup_stuck",
                target="stargate-test",
                parameters={},
                lab_code="test-lab",
            )
        assert result["reason"] == "dry_run"

    def test_no_lab_code_defaults_recommend_only(self):
        from api.action_executor import _get_lab_execution_mode
        mode = _get_lab_execution_mode(None, None)
        assert mode == "recommend_only"

    def test_risk_too_high_blocks_execution(self):
        from api.action_executor import execute_action
        with patch("api.action_executor._get_lab_execution_mode", return_value="low_risk_auto"), \
             patch("engine.catalog_loader.get_commands_for_action", return_value=[]):
            result = execute_action(
                action_type="pool_exhaustion",
                target="some-ns",
                parameters={},
                lab_code="my-lab",
            )
        assert result["executed"] is False
        assert result["reason"] == "risk_too_high"

    def test_rate_limit_blocks_execution(self):
        from api.action_executor import execute_action
        mock_db = MagicMock()
        with patch("api.action_executor._get_lab_execution_mode", return_value="full_auto"), \
             patch("engine.catalog_loader.get_commands_for_action", return_value=["oc get pods"]), \
             patch("api.action_executor._check_rate_limit", return_value=True):
            result = execute_action(
                action_type="cleanup_stuck",
                target="some-ns",
                parameters={},
                lab_code="my-lab",
                db=mock_db,
            )
        assert result["executed"] is False
        assert result["reason"] == "rate_limited"


class TestValidExecutionModes:
    """API endpoint validates execution modes."""

    def test_valid_modes(self):
        from api.routers.admin import VALID_EXECUTION_MODES
        assert "recommend_only" in VALID_EXECUTION_MODES
        assert "low_risk_auto" in VALID_EXECUTION_MODES
        assert "full_auto" in VALID_EXECUTION_MODES
        assert len(VALID_EXECUTION_MODES) == 3
