"""API request models must resolve before any endpoint executes."""
import pytest


@pytest.mark.parametrize("path,method,model", [
    ("/admin/remediation/config/{lab_code}", "put", "RemediationConfigRequest"),
    ("/admin/remediation/preview", "post", "RemediationPreviewRequest"),
    ("/admin/remediation/execute", "post", "RemediationExecuteRequest"),
    ("/remediation/playbook", "post", "PlaybookRunRequest"),
    ("/integration/geolux-proposal", "post", "GeoluxProposalRequest"),
    ("/integration/deepfield-incident", "post", "DeepfieldIncidentRequest"),
])
def test_openapi_resolves_admin_request_models(path, method, model):
    from api.app import app

    schema = app.openapi()
    body = schema["paths"][path][method]["requestBody"]["content"]["application/json"]
    assert body["schema"]["$ref"] == f"#/components/schemas/{model}"
    assert model in schema["components"]["schemas"]


def test_recommend_only_config_records_typed_body_without_execution(client, db, monkeypatch):
    from unittest.mock import Mock
    from api import action_executor
    from db.models import AuditLog

    executor = Mock(side_effect=AssertionError("Configuration must not execute actions"))
    monkeypatch.setattr(action_executor, "execute_action", executor)
    response = client.put("/admin/remediation/config/synthetic-unit", json={
        "execution_mode": "recommend_only", "max_actions_per_hour": 3,
        "enabled_by": "unit-test",
    })
    assert response.status_code == 200
    assert response.json()["execution_mode"] == "recommend_only"
    audit = db.query(AuditLog).filter_by(action_type="remediation_config_change").one()
    assert audit.parameters == {"execution_mode": "recommend_only", "max_actions_per_hour": 3}
    assert audit.proposed_by == "unit-test"
    executor.assert_not_called()


@pytest.mark.parametrize("body,headers,status", [
    ({"execution_mode": "not-a-mode"}, {}, 400),
    ({"execution_mode": "recommend_only"}, {"X-API-Key": "invalid-unit-key"}, 403),
    ({"max_actions_per_hour": 0}, {}, 422),
])
def test_config_still_rejects_invalid_or_unauthorized_requests(client, db, body, headers, status):
    from db.models import AuditLog

    response = client.put("/admin/remediation/config/synthetic-unit", json=body, headers=headers)
    assert response.status_code == status
    assert db.query(AuditLog).filter_by(action_type="remediation_config_change").count() == 0
