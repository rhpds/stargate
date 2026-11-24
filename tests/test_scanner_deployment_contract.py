import re
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
    """Tier 3 has to refresh a namespace inside the investigation window, and
    it has to be on its own thread or the interval is not the cadence: inside
    the tick, `tick + tier1` dominates and 600 s bought a 2.5 h sweep."""
    values = (ROOT / "deploy/helm/stargate/values-infra01.yaml").read_text()

    tier3 = int(re.search(r"^\s*tier3:\s*(\d+)", values, re.M).group(1))
    assert tier3 <= 600, "namespace refresh must fit inside the investigation window"
    assert "tier3Independent: true" in values, "the interval is not the cadence without this"
    assert "batch: 25" in values


def test_default_values_match_the_production_cadence():
    """values.yaml is what a plain `helm install` gets; it must not be the
    slower configuration that `values-infra01.yaml` had to override."""
    values = (ROOT / "deploy/helm/stargate/values.yaml").read_text()

    tier3 = int(re.search(r"^\s*tier3:\s*(\d+)", values, re.M).group(1))
    assert tier3 <= 600
    assert "tier3Independent: true" in values
    assert 'cpu: "5"' in values
