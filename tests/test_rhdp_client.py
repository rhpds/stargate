"""EDD tests — RHDP client (engine/rhdp_client.py)."""

from unittest.mock import patch, MagicMock

import pytest


class TestRHDPClientImports:

    def test_module_importable(self):
        from engine.rhdp_client import execute_rhdp_action, retry_provision, destroy_gracefully, request_pool_scaling, sandbox_api_action
        assert callable(execute_rhdp_action)

    def test_get_anarchy_state(self):
        from engine.rhdp_client import get_anarchy_state
        assert callable(get_anarchy_state)


class TestExecuteRHDPAction:

    def test_routes_anarchy_retry(self):
        from engine.rhdp_client import execute_rhdp_action
        with patch("engine.rhdp_client._run_oc_patch") as mock:
            mock.return_value = {"success": True}
            result = execute_rhdp_action("retry", "ns", {"command": "anarchy:retry:my-subject"})
        assert mock.called
        assert result["success"]

    def test_routes_anarchy_destroy(self):
        from engine.rhdp_client import execute_rhdp_action
        with patch("engine.rhdp_client._run_oc_patch") as mock:
            mock.return_value = {"success": True}
            result = execute_rhdp_action("destroy", "ns", {"command": "anarchy:destroy:my-subject"})
        assert mock.called

    def test_routes_sandbox_api_delete(self):
        from engine.rhdp_client import execute_rhdp_action
        with patch("engine.rhdp_client.sandbox_api_action") as mock:
            mock.return_value = {"success": True}
            result = execute_rhdp_action("reclaim", "ns", {"command": "sandbox-api:delete:uuid-123"})
        mock.assert_called_once_with("uuid-123", action="delete")

    def test_routes_poolboy_scale(self):
        from engine.rhdp_client import execute_rhdp_action
        with patch("engine.rhdp_client._run_oc_patch") as mock:
            mock.return_value = {"success": True}
            result = execute_rhdp_action("scale", "ns", {"command": "poolboy:scale:my-pool:10"})
        assert mock.called

    def test_unknown_action_returns_error(self):
        from engine.rhdp_client import execute_rhdp_action
        result = execute_rhdp_action("unknown", "ns", {"command": "invalid:action"})
        assert not result["success"]
        assert "Unknown" in result["error"]


class TestRetryProvision:

    def test_patches_desired_state(self):
        from engine.rhdp_client import retry_provision
        with patch("engine.rhdp_client._run_oc_patch") as mock:
            mock.return_value = {"success": True}
            retry_provision("my-subject")
        args = mock.call_args
        assert args[0][1] == "my-subject"
        assert "started" in str(args[0][3])


class TestSandboxAPIAction:

    def test_no_url_returns_error(self):
        from engine.rhdp_client import sandbox_api_action
        with patch("engine.rhdp_client.SANDBOX_API_URL", ""):
            result = sandbox_api_action("uuid-123")
        assert not result["success"]
        assert "not configured" in result["error"]
