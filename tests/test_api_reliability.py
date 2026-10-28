"""API reliability: bounded metric labels and fully resolved request schemas."""
from types import SimpleNamespace


def test_openapi_resolves_all_request_models():
    from api.app import app
    app.openapi_schema = None
    schema = app.openapi()
    for path, method in [("/admin/remediation/preview", "post"),
                         ("/admin/remediation/execute", "post"),
                         ("/admin/remediation/config/{lab_code}", "put"),
                         ("/remediation/playbook", "post")]:
        operation = schema["paths"][path][method]
        assert "requestBody" in operation
        assert all(p["name"] not in {"request", "body", "req"} for p in operation.get("parameters", []))


def test_metric_labels_never_include_resource_ids_or_unmatched_paths():
    from api.metrics import request_metric_labels
    for i in range(2000):
        request = SimpleNamespace(method="GET", scope={"route": SimpleNamespace(path="/runs/{run_id}")},
                                  url=SimpleNamespace(path=f"/runs/resource-{i}"))
        assert request_metric_labels(request) == ("GET", "/runs/{run_id}")
        request.scope = {}
        assert request_metric_labels(request) == ("GET", "<unmatched>")
        request.method = f"UNTRUSTED-{i}"
        assert request_metric_labels(request) == ("OTHER", "<unmatched>")


def test_dynamic_route_requests_create_one_metric_series(client, monkeypatch):
    from prometheus_client import CollectorRegistry, Counter, Histogram
    from api import metrics
    registry = CollectorRegistry()
    counter = Counter("test_http", "test", ["method", "path", "status"], registry=registry)
    histogram = Histogram("test_duration", "test", ["method", "path"], registry=registry)
    monkeypatch.setattr(metrics, "http_requests_total", counter)
    monkeypatch.setattr(metrics, "http_request_duration", histogram)
    for i in range(100):
        assert client.get(f"/runs/missing-{i}").status_code == 404
    assert len(counter._metrics) == 1
    assert len(histogram._metrics) == 1
    assert next(iter(counter._metrics)) == ("GET", "/runs/{run_id}", "404")


def test_preview_accepts_json_body_and_never_executes(client, monkeypatch):
    from api import action_executor, llm
    from api.routers import _shared

    def forbidden(*args, **kwargs):
        raise AssertionError("A preview must not execute actions or call models")

    monkeypatch.setattr(action_executor, "execute_action", forbidden)
    monkeypatch.setattr(llm, "call_llm", forbidden)
    monkeypatch.setattr(_shared, "_dry_run_enabled", True)
    result = client.post("/admin/remediation/preview", json={
        "namespace": "stargate-test", "cluster": "infra01", "failure_class": "showroom_not_ready"})
    assert result.status_code == 200
    assert result.json()["would_execute"] is False
    assert any(g["gate"] == "Dry-Run Mode" and g["passed"] is False for g in result.json()["gates"])
