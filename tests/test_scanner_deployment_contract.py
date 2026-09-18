from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dedicated_scheduler_persists_without_duplicate_babylon_owner():
    template = (ROOT / "deploy/helm/stargate/templates/scanner.yaml").read_text()

    assert '"--api-url"' in template
    assert '"--no-babylon"' in template
    assert "STARGATE_ADMIN_API_KEY" in template
    assert "key: admin-api-key" in template


def test_scheduler_credentials_are_secret_references():
    template = (ROOT / "deploy/helm/stargate/templates/scanner.yaml").read_text()

    assert "STARGATE_SANDBOX_API_TOKEN" in template
    assert "key: sandbox-api-token" in template
    assert "STARGATE_SANDBOX_API_TOKEN\n              value:" not in template
    assert template.count("key: admin-api-key") == 2


def test_infra01_namespace_refresh_fits_in_investigation_window():
    values = (ROOT / "deploy/helm/stargate/values-infra01.yaml").read_text()

    assert "tier3: 600" in values
    assert "batch: 25" in values
