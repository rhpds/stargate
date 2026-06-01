"""EDD tests — Auth gates: every protected endpoint rejects without auth."""

from unittest.mock import patch

import pytest


class TestRequireAdmin:

    def test_rejects_without_key_or_header(self):
        from api.routers._shared import require_admin
        from fastapi import HTTPException
        with patch("api.routers._shared.ADMIN_API_KEY", "test-key"):
            with pytest.raises(HTTPException) as exc:
                require_admin(request=None, api_key="")
            assert exc.value.status_code == 403

    def test_accepts_valid_api_key(self):
        from api.routers._shared import require_admin
        with patch("api.routers._shared.ADMIN_API_KEY", "test-key"):
            require_admin(request=None, api_key="test-key")

    def test_accepts_oauth_user_header(self):
        from api.routers._shared import require_admin
        from unittest.mock import MagicMock
        with patch("api.routers._shared.ADMIN_API_KEY", "test-key"):
            mock_request = MagicMock()
            mock_request.headers = {"x-forwarded-user": "jkershaw@redhat.com"}
            require_admin(request=mock_request, api_key="")

    def test_503_when_no_admin_key_configured(self):
        from api.routers._shared import require_admin
        from fastapi import HTTPException
        with patch("api.routers._shared.ADMIN_API_KEY", ""):
            with pytest.raises(HTTPException) as exc:
                require_admin(request=None, api_key="anything")
            assert exc.value.status_code == 503

    def test_rejects_without_oauth_user(self):
        from api.routers._shared import require_admin
        from fastapi import HTTPException
        with patch("api.routers._shared.ADMIN_API_KEY", "test-key"):
            with pytest.raises(HTTPException) as exc:
                require_admin(request=None, api_key="wrong-key")
            assert exc.value.status_code == 403


class TestValidExecutionModes:

    def test_valid_modes_constant(self):
        from api.routers.admin import VALID_EXECUTION_MODES
        assert "recommend_only" in VALID_EXECUTION_MODES
        assert "low_risk_auto" in VALID_EXECUTION_MODES
        assert "full_auto" in VALID_EXECUTION_MODES
        assert len(VALID_EXECUTION_MODES) == 3
