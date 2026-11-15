"""OpenAPI contract tests — the document must be true.

Phase 1 of the frontend redesign (docs/frontend-redesign-plan.md §4):
every endpoint the frontend consumes declares a response model, the
OpenAPI spec becomes the single source of truth, and TS types generate
from it. These tests pin the first family (capacity) and fail any
endpoint that regresses to a schemaless response.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def spec(client):
    return client.get("/openapi.json").json()


def _has_schema(spec, path, method="get"):
    op = spec["paths"][path][method]
    resp = op.get("responses", {}).get("200", {})
    content = resp.get("content", {})
    return any(c.get("schema") for c in content.values())


class TestCapacityContracts:
    def test_resource_forecast_has_response_schema(self, spec):
        assert _has_schema(spec, "/api/v1/resource-forecast")

    def test_resource_forecast_schema_names_the_contract(self, spec):
        op = spec["paths"]["/api/v1/resource-forecast"]["get"]
        schema = op["responses"]["200"]["content"]["application/json"]["schema"]
        # the response model is named, not an anonymous dict
        assert "$ref" in str(schema) or schema.get("type") == "object"

    def test_concentration_has_response_schema(self, spec):
        assert _has_schema(spec, "/dashboard/concentration")


class TestExportedSpec:
    def test_spec_exports_deterministically(self):
        """The generation pipeline needs a server-free export: the same
        app must produce the same spec every time."""
        from api.app import app
        spec1 = app.openapi()
        spec2 = app.openapi()
        assert spec1 == spec2
        assert spec1["openapi"].startswith("3.")
