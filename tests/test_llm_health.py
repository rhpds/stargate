"""Tests for LLM gateway health monitoring (collectors/llm_health.py).

Network mocked throughout. The native LiteLLM /health shape was captured
live from the racmaas gateway (Oct 30 2026): healthy_endpoints,
unhealthy_endpoints, healthy_count, unhealthy_count — with model ids like
'openai/granite-2b-cpu' and per-endpoint api_base + error.
"""

import json
from unittest.mock import patch

import pytest
from sqlalchemy import text

from collectors.llm_health import (
    _gateway_via_native_health,
    _strip_prefix,
    probe_gateways,
    record_probe_evaluations,
)
from tests.conftest import TestSession, test_engine


NATIVE_HEALTH = {
    "healthy_endpoints": [
        {"model": "openai/granite-2b-cpu", "api_base": "http://granite-predictor.llm-hosting.svc/v1"},
        {"model": "openai/qwen3-14b", "api_base": "http://qwen3-predictor.llm-hosting.svc/v1"},
    ],
    "unhealthy_endpoints": [
        {"model": "openai/gpt-oss-120b", "api_base": "http://gaudi-predictor.llm-hosting.svc/v1",
         "error": "litellm.InternalServerError: Connection error"},
        {"model": "openai/qwen3-14b-ny-08", "api_base": "http://old-node.llm-hosting.svc/v1",
         "error": "litellm.NotFoundError: The model was not found"},
    ],
    "healthy_count": 2,
    "unhealthy_count": 2,
}

ADVERTISED_MODELS = {
    "object": "list",
    "data": [
        {"id": "granite-2b-cpu"},
        {"id": "qwen3-14b"},
        {"id": "gpt-oss-120b"},
        {"id": "ghost-model"},  # advertised but absent from /health
    ],
}


def test_strip_prefix():
    assert _strip_prefix("openai/granite-2b-cpu") == "granite-2b-cpu"
    assert _strip_prefix("qwen3-14b") == "qwen3-14b"


def test_native_health_parsing():
    """healthy/unhealthy endpoints parsed; model prefixes stripped."""
    target = {"name": "racmaas", "url": "https://gw.example.com", "api_key": "k"}

    def fake_api(t, path, payload=None, timeout=45):
        if path == "/health":
            return 200, NATIVE_HEALTH
        if path == "/v1/models":
            return 200, ADVERTISED_MODELS
        return 404, None

    with patch("collectors.llm_health._api", side_effect=fake_api):
        results = _gateway_via_native_health(target)

    models = {r["model"]: r for r in results}
    assert models["granite-2b-cpu"]["outcome"] == "pass"
    assert models["qwen3-14b"]["outcome"] == "pass"
    assert models["gpt-oss-120b"]["outcome"] == "fail"
    assert models["gpt-oss-120b"]["failure_class"] == "model_endpoint_error"
    assert "Connection error" in models["gpt-oss-120b"]["error"]
    # stale deployment with NotFound
    assert models["qwen3-14b-ny-08"]["outcome"] == "fail"
    # advertised but absent from /health → model_removed
    assert models["ghost-model"]["outcome"] == "fail"
    assert models["ghost-model"]["failure_class"] == "model_removed"
    # gateway itself reported healthy
    assert models["(gateway)"]["outcome"] == "pass"


def test_native_unavailable_falls_back_to_synthetic(monkeypatch):
    """Older LiteLLM without /health → synthetic per-model probes."""
    monkeypatch.setenv("STARGATE_LLM_HEALTH_TARGETS", json.dumps([
        {"name": "old-gw", "url": "https://old.example.com", "api_key": "k"},
    ]))
    monkeypatch.setenv("STARGATE_LITELLM_URL", "")
    monkeypatch.setenv("STARGATE_LITELLM_API_KEY", "")

    def fake_api(t, path, payload=None, timeout=45):
        if path == "/health":
            return 404, {"detail": "Not Found"}
        if path == "/v1/models":
            return 200, {"data": [{"id": "m1"}, {"id": "m2"}]}
        if path == "/v1/chat/completions":
            if payload and payload.get("model") == "m1":
                return 200, {"choices": [{"message": {"content": "OK"}}]}
            return 500, {"error": {"message": "boom"}}
        return 404, None

    with patch("collectors.llm_health._api", side_effect=fake_api):
        report = probe_gateways(force=True)

    assert report["gateways"] == {"old-gw": "synthetic"}
    by_model = {r["model"]: r for r in report["results"]}
    assert by_model["m1"]["outcome"] == "pass"
    assert by_model["m2"]["outcome"] == "fail"
    assert report["failing"] == 1
    assert "old-gw/m2" in report["failing_models"]


def test_record_probe_evaluations(client):
    """Probe results persist as model-endpoint-ready evaluations."""
    from db.database import Base
    from db.models import EvaluationRecord

    report = {
        "results": [
            {"gateway": "racmaas", "model": "qwen3-14b", "outcome": "pass",
             "failure_class": None, "message": "healthy", "probed_at": "2026-10-30T15:00:00+00:00"},
            {"gateway": "racmaas", "model": "gpt-oss-120b", "outcome": "fail",
             "failure_class": "model_endpoint_error", "message": "unhealthy: conn",
             "probed_at": "2026-10-30T15:00:00+00:00"},
        ]
    }
    db = TestSession()
    try:
        recorded = record_probe_evaluations(report, db)
        assert recorded == 2
        rows = db.query(EvaluationRecord).filter(
            EvaluationRecord.stage_id == "model-endpoint-ready"
        ).all()
        assert len(rows) == 2
        by_lab = {r.lab_code: r for r in rows}
        assert by_lab["qwen3-14b"].outcome == "pass"
        assert by_lab["qwen3-14b"].cluster_name == "racmaas"
        assert by_lab["gpt-oss-120b"].failure_class == "model_endpoint_error"
        # idempotent per run_id+model hour bucket
        assert record_probe_evaluations(report, db) == 0
    finally:
        db.rollback()
        db.close()


def test_dashboard_llm_health_endpoint(client, monkeypatch):
    """GET /dashboard/llm-health returns the report and records evaluations."""
    fake_report = {
        "gateways": {"racmaas": "native"},
        "models_probed": 3, "passing": 2, "warned": 0, "failing": 1,
        "failing_models": ["racmaas/gpt-oss-120b"], "slow_models": [],
        "results": [
            {"gateway": "racmaas", "model": "qwen3-14b", "outcome": "pass",
             "failure_class": None, "message": "healthy", "probed_at": "2026-10-30T15:00:00+00:00"},
            {"gateway": "racmaas", "model": "gpt-oss-120b", "outcome": "fail",
             "failure_class": "model_endpoint_error", "message": "unhealthy",
             "probed_at": "2026-10-30T15:00:00+00:00"},
        ],
        "probed_at": "2026-10-30T15:00:00+00:00",
    }
    monkeypatch.setattr("collectors.llm_health.probe_gateways",
                        lambda force=False: fake_report)
    resp = client.get("/dashboard/llm-health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["failing"] == 1
    assert "racmaas/gpt-oss-120b" in body["failing_models"]
    assert body["evaluations_recorded"] == 2
