"""Tests for the extended dependency-health probe set.

The defaults cover the documented Oct-21 incident dependencies; the
extension adds env-derived ecosystem services (Labagator, Demolition,
the MaaS gateway, Sandbox API when configured) and a configurable
extras list — so the probe set can grow with the ecosystem's actual
external surface without code changes.
"""

import json

import pytest

from collectors import dependency_health as dh


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in (
        "STARGATE_DEPENDENCY_HEALTH_TARGETS",
        "STARGATE_DEPENDENCY_HEALTH_EXTRA_TARGETS",
        "STARGATE_LABAGATOR_URL",
        "STARGATE_DEMOLITION_URL",
        "STARGATE_LITELLM_URL",
        "STARGATE_SANDBOX_API_URL",
        "STARGATE_SANDBOX_API_METRICS_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


class TestEnvDerivedTargets:
    def test_defaults_when_nothing_configured(self):
        names = [t["name"] for t in dh._targets()]
        assert names == ["sso.redhat.com", "api.openshift.com", "registry.redhat.io"]

    def test_labagator_and_demolition_appear_when_configured(self, monkeypatch):
        monkeypatch.setenv("STARGATE_LABAGATOR_URL", "http://labagator.svc:8080/api/v1")
        monkeypatch.setenv("STARGATE_DEMOLITION_URL", "http://demolition.svc:8000/api/v1")
        names = [t["name"] for t in dh._targets()]
        assert "labagator" in names and "demolition" in names
        assert names.count("labagator") == 1

    def test_maas_gateway_derived_from_litellm_origin(self, monkeypatch):
        monkeypatch.setenv(
            "STARGATE_LITELLM_URL",
            "https://maas-rhdp.apps.maas.redhatworkshops.io/v1/chat/completions")
        targets = {t["name"]: t["url"] for t in dh._targets()}
        assert targets["maas-gateway"] == "https://maas-rhdp.apps.maas.redhatworkshops.io/"

    def test_sandbox_api_metrics_fallback(self, monkeypatch):
        monkeypatch.setenv("STARGATE_SANDBOX_API_METRICS_URL", "http://sandbox/metrics")
        names = [t["name"] for t in dh._targets()]
        assert "sandbox-api-metrics" in names and "sandbox-api" not in names

    def test_sandbox_api_url_wins_over_metrics(self, monkeypatch):
        monkeypatch.setenv("STARGATE_SANDBOX_API_URL", "http://sandbox/api")
        monkeypatch.setenv("STARGATE_SANDBOX_API_METRICS_URL", "http://sandbox/metrics")
        names = [t["name"] for t in dh._targets()]
        assert "sandbox-api" in names and "sandbox-api-metrics" not in names


class TestExtraTargets:
    def test_extras_appended(self, monkeypatch):
        monkeypatch.setenv("STARGATE_DEPENDENCY_HEALTH_EXTRA_TARGETS", json.dumps([
            {"name": "sumologic", "url": "https://collectors.sumologic.com"},
            {"name": "sales-cloud", "url": "https://login.salesforce.com/"},
        ]))
        names = [t["name"] for t in dh._targets()]
        assert "sumologic" in names and "sales-cloud" in names
        assert "sso.redhat.com" in names  # defaults still present

    def test_extra_overrides_default_by_name(self, monkeypatch):
        monkeypatch.setenv("STARGATE_DEPENDENCY_HEALTH_EXTRA_TARGETS", json.dumps([
            {"name": "sso.redhat.com", "url": "https://sso-proxy.example.com/"},
        ]))
        targets = {t["name"]: t["url"] for t in dh._targets()}
        assert targets["sso.redhat.com"] == "https://sso-proxy.example.com/"
        assert len(targets) == 3

    def test_invalid_extra_json_ignored(self, monkeypatch):
        monkeypatch.setenv("STARGATE_DEPENDENCY_HEALTH_EXTRA_TARGETS", "{not json")
        assert len(dh._targets()) == 3

    def test_explicit_targets_var_still_replaces_everything(self, monkeypatch):
        monkeypatch.setenv("STARGATE_LABAGATOR_URL", "http://labagator.svc")
        monkeypatch.setenv("STARGATE_DEPENDENCY_HEALTH_TARGETS", json.dumps(
            [{"name": "only", "url": "https://only.example.com/"}]))
        names = [t["name"] for t in dh._targets()]
        assert names == ["only"]

    def test_entries_without_url_dropped(self, monkeypatch):
        monkeypatch.setenv("STARGATE_DEPENDENCY_HEALTH_EXTRA_TARGETS", json.dumps([
            {"name": "no-url"},
            {"name": "real", "url": "https://real.example.com/"},
        ]))
        names = [t["name"] for t in dh._targets()]
        assert "real" in names and "no-url" not in names
