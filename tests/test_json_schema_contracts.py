"""Contract tests — validate sample data against JSON schemas in evidence-schemas/.

These tests prove the JSON schemas are not dead artifacts. Every schema gets:
- A valid sample that passes validation
- An invalid sample missing a required field (rejected)
- An invalid sample with wrong type (rejected)
"""

import json
from pathlib import Path

import jsonschema
import pytest

SCHEMA_DIR = Path(__file__).parent.parent / "evidence-schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text())


# --- Run schema ---

class TestRunSchemaContract:
    SCHEMA = _load_schema("run.schema.json")

    def test_valid_run(self):
        data = {
            "run_id": "test-001",
            "demo_id": "demo-simple-container",
            "namespace": "ns-001",
            "requested_by": "user",
            "status": "pending",
            "rubric_version": "v0.1.0",
        }
        jsonschema.validate(data, self.SCHEMA)

    def test_valid_run_with_optionals(self):
        data = {
            "run_id": "test-001",
            "demo_id": "demo-simple-container",
            "namespace": "ns-001",
            "requested_by": "user",
            "status": "running",
            "rubric_version": "v0.1.0",
            "git_sha": "abc123",
            "started_at": "2026-05-05T14:30:00Z",
            "completed_at": None,
        }
        jsonschema.validate(data, self.SCHEMA)

    def test_missing_required_field(self):
        data = {
            "run_id": "test-001",
            "demo_id": "demo-simple-container",
            "namespace": "ns-001",
            "status": "pending",
            "rubric_version": "v0.1.0",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, self.SCHEMA)

    def test_invalid_status_enum(self):
        data = {
            "run_id": "test-001",
            "demo_id": "demo-simple-container",
            "namespace": "ns-001",
            "requested_by": "user",
            "status": "invalid",
            "rubric_version": "v0.1.0",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, self.SCHEMA)

    def test_empty_run_id_rejected(self):
        data = {
            "run_id": "",
            "demo_id": "demo-simple-container",
            "namespace": "ns-001",
            "requested_by": "user",
            "status": "pending",
            "rubric_version": "v0.1.0",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, self.SCHEMA)


# --- Stage schema ---

class TestStageSchemaContract:
    SCHEMA = _load_schema("stage.schema.json")

    def test_valid_stage(self):
        data = {
            "run_id": "test-001",
            "stage_id": "namespace-ready",
            "status": "passed",
        }
        jsonschema.validate(data, self.SCHEMA)

    def test_valid_stage_with_result(self):
        data = {
            "run_id": "test-001",
            "stage_id": "route-ready",
            "status": "failed",
            "result": {
                "outcome": "fail",
                "failure_class": "service_has_no_endpoints",
                "message": "No ready endpoints",
            },
        }
        jsonschema.validate(data, self.SCHEMA)

    def test_missing_stage_id(self):
        data = {"run_id": "test-001", "status": "pending"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, self.SCHEMA)

    def test_invalid_status_enum(self):
        data = {"run_id": "test-001", "stage_id": "x", "status": "bogus"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, self.SCHEMA)


# --- Evidence schema ---

class TestEvidenceSchemaContract:
    SCHEMA = _load_schema("evidence.schema.json")

    def test_valid_evidence(self):
        data = {
            "evidence_id": "ev-001",
            "run_id": "test-001",
            "stage_id": "namespace-ready",
            "type": "fixture",
            "source": "test",
            "observed": {"namespace_exists": True},
            "result": "pass",
            "timestamp": "2026-05-05T14:35:00Z",
        }
        jsonschema.validate(data, self.SCHEMA)

    def test_valid_evidence_with_resource(self):
        data = {
            "evidence_id": "ev-002",
            "run_id": "test-001",
            "stage_id": "route-ready",
            "type": "openshift_resource_state",
            "source": "oc",
            "resource": {"kind": "Endpoints", "namespace": "ns-001", "name": "demo-app"},
            "observed": {"ready_endpoint_count": 0},
            "result": "fail",
            "timestamp": "2026-05-05T14:35:00Z",
            "raw_ref": None,
        }
        jsonschema.validate(data, self.SCHEMA)

    def test_missing_required_result(self):
        data = {
            "evidence_id": "ev-001",
            "run_id": "test-001",
            "stage_id": "ns",
            "type": "fixture",
            "source": "test",
            "observed": {},
            "timestamp": "2026-05-05T14:35:00Z",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, self.SCHEMA)

    def test_invalid_result_enum(self):
        data = {
            "evidence_id": "ev-001",
            "run_id": "test-001",
            "stage_id": "ns",
            "type": "fixture",
            "source": "test",
            "observed": {},
            "result": "invalid",
            "timestamp": "2026-05-05T14:35:00Z",
        }
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, self.SCHEMA)


# --- Rubric schema ---

class TestRubricSchemaContract:
    SCHEMA = _load_schema("rubric.schema.json")

    def test_valid_rubric(self):
        data = {
            "id": "namespace-ready",
            "version": "v0.1.0",
            "stage": "namespace-ready",
            "exit_criteria": [{"name": "namespace_exists", "required": True}],
        }
        jsonschema.validate(data, self.SCHEMA)

    def test_valid_rubric_full(self):
        data = {
            "id": "route-ready",
            "version": "v0.1.0",
            "stage": "route-ready",
            "entry_criteria": [{"name": "service_exists"}],
            "exit_criteria": [
                {"name": "route_exists", "required": True},
                {"name": "service_has_ready_endpoints", "required": True},
            ],
            "outcomes": {
                "pass": {"when": "all_required_exit_criteria_pass"},
                "fail": {"when": "any_required_exit_criteria_fail"},
            },
            "failure_classes": {
                "service_has_no_endpoints": {
                    "when": ["service_exists == true", "ready_endpoint_count == 0"],
                    "recommended_action": "inspect_service_selector_and_pod_labels",
                },
            },
            "allowed_remediations": ["collect_service_and_pod_labels"],
            "forbidden_remediations": ["delete_namespace"],
        }
        jsonschema.validate(data, self.SCHEMA)

    def test_missing_exit_criteria(self):
        data = {"id": "test", "version": "v0.1.0", "stage": "test"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, self.SCHEMA)

    def test_empty_exit_criteria(self):
        data = {"id": "test", "version": "v0.1.0", "stage": "test", "exit_criteria": []}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, self.SCHEMA)


# --- Remediation schema ---

class TestRemediationSchemaContract:
    SCHEMA = _load_schema("remediation.schema.json")

    def test_valid_remediation(self):
        data = {
            "id": "inspect_pod_status",
            "risk": "low",
            "mode": "recommend_only",
            "scope": "namespace",
        }
        jsonschema.validate(data, self.SCHEMA)

    def test_valid_remediation_full(self):
        data = {
            "id": "inspect_pod_status",
            "risk": "low",
            "mode": "recommend_only",
            "scope": "namespace",
            "requires_approval": False,
            "allowed_when": ["failure_class == pods_not_ready"],
            "commands": ["oc get pods -n {namespace}"],
            "forbidden_when": ["namespace == openshift-*"],
        }
        jsonschema.validate(data, self.SCHEMA)

    def test_missing_required_risk(self):
        data = {"id": "test", "mode": "recommend_only", "scope": "namespace"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, self.SCHEMA)

    def test_invalid_risk_enum(self):
        data = {"id": "test", "risk": "extreme", "mode": "recommend_only", "scope": "namespace"}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(data, self.SCHEMA)


# --- Schema validator utility tests ---

class TestSchemaValidatorUtility:
    def test_validate_evidence_valid(self):
        from engine.schema_validator import validate_evidence
        data = {
            "evidence_id": "ev-001",
            "run_id": "test-001",
            "stage_id": "ns",
            "type": "fixture",
            "source": "test",
            "observed": {},
            "result": "pass",
            "timestamp": "2026-05-05T14:35:00Z",
        }
        validate_evidence(data)

    def test_validate_evidence_invalid(self):
        from engine.schema_validator import validate_evidence, SchemaValidationError
        data = {"evidence_id": "ev-001"}
        with pytest.raises(SchemaValidationError):
            validate_evidence(data)

    def test_validate_run_valid(self):
        from engine.schema_validator import validate_run
        data = {
            "run_id": "test-001",
            "demo_id": "demo",
            "namespace": "ns",
            "requested_by": "user",
            "status": "pending",
            "rubric_version": "v0.1.0",
        }
        validate_run(data)

    def test_validate_against_schema_generic(self):
        from engine.schema_validator import validate_against_schema, SchemaValidationError
        data = {"id": "test", "risk": "low", "mode": "recommend_only", "scope": "ns"}
        validate_against_schema("remediation.schema.json", data)

        with pytest.raises(SchemaValidationError):
            validate_against_schema("remediation.schema.json", {"id": "test"})

    def test_validate_missing_schema_file(self):
        from engine.schema_validator import validate_against_schema, SchemaValidationError
        with pytest.raises(SchemaValidationError, match="not found"):
            validate_against_schema("nonexistent.schema.json", {})
