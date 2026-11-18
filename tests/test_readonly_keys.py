"""Read-only API keys — authenticate, but cannot mutate.

A key handed to an agent for queries should not be able to approve a diagnosis
or reach admin endpoints.
"""

import pytest
from fastapi import HTTPException


def _arm(monkeypatch, readonly=("ro-key",)):
    from api.routers import _shared
    monkeypatch.setattr(_shared, "_READONLY_KEYS", list(readonly))
    monkeypatch.setattr(_shared, "_ALL_VALID_KEYS", ["admin-key", *readonly])


class TestReadonlyKeys:
    def test_readonly_key_is_a_valid_key(self, monkeypatch):
        _arm(monkeypatch)
        from api.routers import _shared
        assert _shared._is_valid_api_key("ro-key") is True

    def test_readonly_key_cannot_use_admin_endpoints(self, monkeypatch):
        _arm(monkeypatch)
        from api.routers import _shared
        with pytest.raises(HTTPException) as exc:
            _shared.require_admin(api_key="ro-key")
        assert exc.value.status_code == 403
        assert "read-only" in str(exc.value.detail).lower()

    def test_readonly_key_can_use_read_endpoints(self, monkeypatch):
        _arm(monkeypatch)
        from api.routers import _shared
        assert _shared.require_admin_read(api_key="ro-key") is None

    def test_write_key_still_works(self, monkeypatch):
        _arm(monkeypatch)
        from api.routers import _shared
        assert _shared.require_admin(api_key="admin-key") is None


class TestMcpReviewGuard:
    def test_readonly_caller_cannot_review(self, monkeypatch, db):
        from api import mcp_server
        from api.routers import _shared
        _arm(monkeypatch)
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        monkeypatch.setenv("_MCP_CALLER_KEY", "ro-key")

        result = mcp_server.review_diagnosis(1, True)

        assert "read-only" in result.lower()

    def test_write_caller_reaches_the_review_path(self, monkeypatch, db):
        from api import mcp_server
        _arm(monkeypatch)
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        monkeypatch.setenv("_MCP_CALLER_KEY", "admin-key")

        result = mcp_server.review_diagnosis(999999, True)

        assert "read-only" not in result.lower()
