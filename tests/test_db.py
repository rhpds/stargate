"""Database persistence tests — evidence survives across sessions."""

from datetime import datetime, timezone

import pytest

from db import repository
from engine.models import (
    Evidence,
    Run,
    RunStatus,
    Stage,
    StageOutcome,
    StageResult,
    StageStatus,
)


class TestRunPersistence:
    def test_create_and_retrieve_run(self, db):
        run = Run(
            run_id="test-run-001",
            demo_id="demo-simple-container",
            namespace="summit-demo-001",
            requested_by="test-user",
            status=RunStatus.PENDING,
            rubric_version="v0.1.0",
        )
        repository.create_run(db, run)
        retrieved = repository.get_run(db, "test-run-001")
        assert retrieved is not None
        assert retrieved.run_id == "test-run-001"
        assert retrieved.demo_id == "demo-simple-container"

    def test_run_not_found(self, db):
        assert repository.get_run(db, "nonexistent") is None

    def test_list_runs(self, db):
        for i in range(3):
            run = Run(
                run_id=f"test-run-{i}",
                demo_id="demo",
                namespace="ns",
                requested_by="user",
                status=RunStatus.PENDING,
                rubric_version="v0.1.0",
            )
            repository.create_run(db, run)
        runs = repository.list_runs(db)
        assert len(runs) == 3

    def test_update_run_status(self, db):
        run = Run(
            run_id="test-run-status",
            demo_id="demo",
            namespace="ns",
            requested_by="user",
            status=RunStatus.PENDING,
            rubric_version="v0.1.0",
        )
        repository.create_run(db, run)
        repository.update_run_status(db, "test-run-status", RunStatus.RUNNING)
        updated = repository.get_run(db, "test-run-status")
        assert updated.status == RunStatus.RUNNING
        assert updated.started_at is not None


class TestStagePersistence:
    def _create_run(self, db):
        run = Run(
            run_id="test-run",
            demo_id="demo",
            namespace="ns",
            requested_by="user",
            status=RunStatus.RUNNING,
            rubric_version="v0.1.0",
        )
        repository.create_run(db, run)

    def test_create_and_retrieve_stage(self, db):
        self._create_run(db)
        stage = Stage(
            run_id="test-run",
            stage_id="namespace-ready",
            status=StageStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        repository.create_stage(db, stage)
        retrieved = repository.get_stage(db, "test-run", "namespace-ready")
        assert retrieved is not None
        assert retrieved.stage_id == "namespace-ready"

    def test_update_stage_with_result(self, db):
        self._create_run(db)
        stage = Stage(
            run_id="test-run",
            stage_id="deployment-ready",
            status=StageStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        repository.create_stage(db, stage)
        result = StageResult(
            outcome=StageOutcome.FAIL,
            failure_class="pods_crashlooping",
            message="Pods are crashing",
        )
        repository.update_stage(db, "test-run", "deployment-ready",
                                status=StageStatus.FAILED, result=result)
        updated = repository.get_stage(db, "test-run", "deployment-ready")
        assert updated.status == StageStatus.FAILED
        assert updated.result.failure_class == "pods_crashlooping"


class TestEvidencePersistence:
    def _setup(self, db):
        run = Run(
            run_id="test-run",
            demo_id="demo",
            namespace="ns",
            requested_by="user",
            status=RunStatus.RUNNING,
            rubric_version="v0.1.0",
        )
        repository.create_run(db, run)
        stage = Stage(
            run_id="test-run",
            stage_id="namespace-ready",
            status=StageStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )
        repository.create_stage(db, stage)

    def test_create_and_retrieve_evidence(self, db):
        self._setup(db)
        evidence = Evidence(
            evidence_id="ev-001",
            run_id="test-run",
            stage_id="namespace-ready",
            type="resource_state",
            source="oc",
            observed={"namespace_exists": True},
            result=StageOutcome.PASS,
            timestamp=datetime.now(timezone.utc),
        )
        repository.create_evidence(db, evidence)
        results = repository.list_evidence_for_stage(db, "test-run", "namespace-ready")
        assert len(results) == 1
        assert results[0].observed["namespace_exists"] is True

    def test_evidence_persists_observed_jsonb(self, db):
        self._setup(db)
        observed = {
            "deployment_exists": True,
            "desired_replicas_ready": True,
            "no_crashloop_pods": False,
            "pod_details": [{"name": "app-1", "ready": False, "crashloop": True}],
        }
        evidence = Evidence(
            evidence_id="ev-002",
            run_id="test-run",
            stage_id="namespace-ready",
            type="resource_state",
            source="oc",
            observed=observed,
            result=StageOutcome.FAIL,
            timestamp=datetime.now(timezone.utc),
        )
        repository.create_evidence(db, evidence)
        results = repository.list_evidence_for_stage(db, "test-run", "namespace-ready")
        assert results[0].observed["no_crashloop_pods"] is False
        assert results[0].observed["pod_details"][0]["crashloop"] is True


class TestEvaluationPersistence:
    def test_create_evaluation(self, db):
        record = repository.create_evaluation(
            db,
            run_id="test-run",
            stage_id="deployment-ready",
            outcome="fail",
            failure_class="pods_crashlooping",
            message="Pods are crashing",
            criteria_results=[
                {"name": "no_crashloop_pods", "required": True, "passed": False},
            ],
            lab_code="LB1088",
            cluster_name="cnv-us-east-ocp-1",
        )
        assert record.id is not None
        assert record.failure_class == "pods_crashlooping"
        assert record.lab_code == "LB1088"

    def test_list_evaluations_by_lab(self, db):
        for i in range(3):
            repository.create_evaluation(
                db,
                run_id=f"run-{i}",
                stage_id="deployment-ready",
                outcome="fail",
                failure_class="pods_crashlooping",
                message="crash",
                criteria_results=[],
                lab_code="LB1088",
            )
        repository.create_evaluation(
            db,
            run_id="run-other",
            stage_id="deployment-ready",
            outcome="pass",
            failure_class=None,
            message="ok",
            criteria_results=[],
            lab_code="LB9999",
        )
        results = repository.list_evaluations(db, lab_code="LB1088")
        assert len(results) == 3
