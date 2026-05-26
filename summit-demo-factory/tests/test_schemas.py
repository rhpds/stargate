"""Tests for Pydantic model validation — valid accepted, invalid rejected."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from api.app.models import (
    BuildReport,
    BuildStageReport,
    BuildStageResult,
    DemoDefinition,
    DemoStageDefinition,
    Evidence,
    Remediation,
    RemediationMode,
    RemediationRisk,
    Rubric,
    RubricCriterion,
    Run,
    RunStatus,
    Stage,
    StageOutcome,
    StageResult,
    StageStatus,
)


# --- Run ---

class TestRunModel:
    def test_valid_run(self):
        run = Run(
            run_id="summit-demo-001-20260505-143000",
            demo_id="demo-simple-container",
            namespace="summit-demo-001",
            requested_by="platform-user",
            status=RunStatus.RUNNING,
            rubric_version="v0.1.0",
            git_sha="abc123",
            started_at=datetime(2026, 5, 5, 14, 30, tzinfo=timezone.utc),
        )
        assert run.run_id == "summit-demo-001-20260505-143000"
        assert run.status == RunStatus.RUNNING
        assert run.completed_at is None

    def test_run_defaults(self):
        run = Run(
            run_id="test-001",
            demo_id="demo-simple",
            namespace="ns-001",
            requested_by="user",
            rubric_version="v0.1.0",
        )
        assert run.status == RunStatus.PENDING
        assert run.git_sha is None
        assert run.started_at is None

    def test_run_missing_required_field(self):
        with pytest.raises(ValidationError):
            Run(
                run_id="test-001",
                demo_id="demo-simple",
                namespace="ns-001",
                rubric_version="v0.1.0",
            )

    def test_run_empty_run_id(self):
        with pytest.raises(ValidationError):
            Run(
                run_id="",
                demo_id="demo-simple",
                namespace="ns-001",
                requested_by="user",
                rubric_version="v0.1.0",
            )

    def test_run_invalid_status(self):
        with pytest.raises(ValidationError):
            Run(
                run_id="test-001",
                demo_id="demo-simple",
                namespace="ns-001",
                requested_by="user",
                status="invalid-status",
                rubric_version="v0.1.0",
            )


# --- Stage ---

class TestStageModel:
    def test_valid_stage(self):
        stage = Stage(
            run_id="test-001",
            stage_id="route-ready",
            status=StageStatus.FAILED,
            started_at=datetime(2026, 5, 5, 14, 34, tzinfo=timezone.utc),
            completed_at=datetime(2026, 5, 5, 14, 35, 22, tzinfo=timezone.utc),
            duration_seconds=82,
            result=StageResult(
                outcome=StageOutcome.FAIL,
                failure_class="service_has_no_endpoints",
                message="Route exists but service has no ready endpoints.",
            ),
        )
        assert stage.result.outcome == StageOutcome.FAIL
        assert stage.result.failure_class == "service_has_no_endpoints"

    def test_stage_defaults(self):
        stage = Stage(run_id="test-001", stage_id="namespace-ready")
        assert stage.status == StageStatus.PENDING
        assert stage.result is None

    def test_stage_missing_stage_id(self):
        with pytest.raises(ValidationError):
            Stage(run_id="test-001")


# --- Evidence ---

class TestEvidenceModel:
    def test_valid_evidence(self):
        ev = Evidence(
            evidence_id="ev-000001",
            run_id="test-001",
            stage_id="route-ready",
            type="openshift_resource_state",
            source="oc",
            observed={"ready_endpoint_count": 0},
            result=StageOutcome.FAIL,
            timestamp=datetime(2026, 5, 5, 14, 35, tzinfo=timezone.utc),
        )
        assert ev.observed["ready_endpoint_count"] == 0
        assert ev.result == StageOutcome.FAIL

    def test_evidence_missing_required(self):
        with pytest.raises(ValidationError):
            Evidence(
                evidence_id="ev-000001",
                run_id="test-001",
                stage_id="route-ready",
                type="openshift_resource_state",
                source="oc",
                timestamp=datetime(2026, 5, 5, 14, 35, tzinfo=timezone.utc),
            )


# --- Rubric ---

class TestRubricModel:
    def test_valid_rubric(self):
        rubric = Rubric(
            id="route-ready",
            version="v0.1.0",
            stage="route-ready",
            entry_criteria=[RubricCriterion(name="service_exists", required=True)],
            exit_criteria=[
                RubricCriterion(name="route_exists", required=True),
                RubricCriterion(name="service_has_ready_endpoints", required=True),
            ],
        )
        assert rubric.id == "route-ready"
        assert len(rubric.exit_criteria) == 2

    def test_rubric_missing_id(self):
        with pytest.raises(ValidationError):
            Rubric(
                version="v0.1.0",
                stage="route-ready",
                exit_criteria=[RubricCriterion(name="test", required=True)],
            )

    def test_rubric_empty_id(self):
        with pytest.raises(ValidationError):
            Rubric(
                id="",
                version="v0.1.0",
                stage="route-ready",
                exit_criteria=[RubricCriterion(name="test", required=True)],
            )


# --- Remediation ---

class TestRemediationModel:
    def test_valid_remediation(self):
        rem = Remediation(
            id="inspect_service_selector_and_pod_labels",
            risk=RemediationRisk.LOW,
            mode=RemediationMode.RECOMMEND_ONLY,
            scope="namespace",
            requires_approval=False,
            commands=["oc get svc {service} -n {namespace} -o yaml"],
        )
        assert rem.risk == RemediationRisk.LOW
        assert rem.mode == RemediationMode.RECOMMEND_ONLY

    def test_remediation_defaults(self):
        rem = Remediation(
            id="test-rem",
            risk=RemediationRisk.LOW,
            scope="namespace",
        )
        assert rem.mode == RemediationMode.RECOMMEND_ONLY
        assert rem.requires_approval is True
        assert rem.commands == []


# --- Demo Definition ---

class TestDemoDefinitionModel:
    def test_valid_demo(self):
        demo = DemoDefinition(
            demo_id="demo-simple-container",
            name="Simple Container Demo",
            namespace_prefix="summit-demo",
            rubric_version="v0.1.0",
            stages=[
                DemoStageDefinition(stage_id="namespace-ready"),
                DemoStageDefinition(stage_id="deployment-ready"),
            ],
        )
        assert len(demo.stages) == 2

    def test_demo_empty_stages(self):
        with pytest.raises(ValidationError):
            DemoDefinition(
                demo_id="demo-simple-container",
                name="Simple Container Demo",
                namespace_prefix="summit-demo",
                rubric_version="v0.1.0",
                stages=[],
            )


# --- Build Report ---

class TestBuildReportModel:
    def test_valid_build_report(self):
        report = BuildReport(
            build_run_id="local-20260505-150000",
            git_sha="abc123",
            status=BuildStageResult.GREEN,
            stages=[
                BuildStageReport(name="schema_models", result=BuildStageResult.GREEN, tests=24, failures=0),
                BuildStageReport(name="rubric_evaluator", result=BuildStageResult.GREEN, tests=18, failures=0),
            ],
        )
        assert report.status == BuildStageResult.GREEN
        assert len(report.stages) == 2

    def test_build_report_with_blocking(self):
        report = BuildReport(
            build_run_id="local-20260505-150000",
            status=BuildStageResult.RED,
            stages=[
                BuildStageReport(name="schema_models", result=BuildStageResult.GREEN, tests=24, failures=0),
                BuildStageReport(name="simulated_e2e", result=BuildStageResult.RED, tests=3, failures=1),
            ],
            blocking=["simulated_e2e"],
        )
        assert report.status == BuildStageResult.RED
        assert "simulated_e2e" in report.blocking
