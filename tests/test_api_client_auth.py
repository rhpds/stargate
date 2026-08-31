from cli.api_client import StarGateClient


def test_api_client_uses_admin_api_key(monkeypatch):
    monkeypatch.setenv("STARGATE_ADMIN_API_KEY", "test-secret")

    headers = StarGateClient("http://stargate-api:8090")._headers()

    assert headers["X-API-Key"] == "test-secret"


def test_api_client_uses_safe_internal_timeout(monkeypatch):
    monkeypatch.delenv("STARGATE_API_CLIENT_TIMEOUT", raising=False)

    assert StarGateClient("http://stargate-api:8090").timeout == 60
