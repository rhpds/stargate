"""Database persistence tests — verify runs/stages/evidence are stored and queryable."""

from datetime import datetime, timezone

import pytest

from engine.models import (
    Evidence,
    EvidenceResource,
    Run,
    RunStatus,
    Stage,
    StageOutcome,
    StageResult,
    StageStatus,
)
from api.app import repository


class TestRunPersistence:
    def test_create_and_get_run(self, db_session):
        run = Run(
            run_id="db-test-001",
            demo_id="demo-simple-container",
            namespace="ns-001",
            requested_by="tester",
            rubric_version="v0.1.0",
        )
        created = repository.create_run(db_session, run)
        assert created.run_id == "db-test-001"

        fetched = repository.get_run(db_session, "db-test-001")
        assert fetched is not None
        assert fetched.demo_id == "demo-simple-container"
        assert fetched.status == RunStatus.PENDING

    def test_get_run_not_found(self, db_session):
        assert repository.get_run(db_session, "nonexistent") is None

    def test_list_runs(self, db_session):
        for i in range(3):
            repository.create_run(db_session, Run(
                run_id=f"list-{i}",
                demo_id="demo",
                namespace="ns",
                requested_by="user",
                rubric_version="v0.1.0",
            ))
        runs = repository.list_runs(db_session)
        assert len(runs) == 3

    def test_update_run_status(self, db_session):
        repository.create_run(db_session, Run(
            run_id="status-test",
            demo_id="demo",
            namespace="ns",
            requested_by="user",
            rubric_version="v0.1.0",
        ))
        updated = repository.update_run_status(db_session, "status-test", RunStatus.RUNNING)
        assert updated.status == RunStatus.RUNNING
        assert updated.started_at is not None

    def test_update_run_completed(self, db_session):
        repository.create_run(db_session, Run(
            run_id="complete-test",
            demo_id="demo",
            namespace="ns",
            requested_by="user",
            rubric_version="v0.1.0",
        ))
        repository.update_run_status(db_session, "complete-test", RunStatus.RUNNING)
        updated = repository.update_run_status(db_session, "complete-test", RunStatus.COMPLETED)
        assert updated.status == RunStatus.COMPLETED
        assert updated.completed_at is not None


class TestStagePersistence:
    def test_create_and_get_stage(self, db_session):
        stage = Stage(
            run_id="run-001",
            stage_id="namespace-ready",
            status=StageStatus.RUNNING,
            started_at=datetime(2026, 5, 5, 14, 30, tzinfo=timezone.utc),
        )
        created = repository.create_stage(db_session, stage)
        assert created.stage_id == "namespace-ready"

        fetched = repository.get_stage(db_session, "run-001", "namespace-ready")
        assert fetched is not None
        assert fetched.status == StageStatus.RUNNING

    def test_list_stages(self, db_session):
        for sid in ["namespace-ready", "deployment-ready", "route-ready"]:
            repository.create_stage(db_session, Stage(
                run_id="run-001", stage_id=sid, status=StageStatus.PENDING,
            ))
        stages = repository.list_stages(db_session, "run-001")
        assert len(stages) == 3

    def test_update_stage_with_result(self, db_session):
        repository.create_stage(db_session, Stage(
            run_id="run-001",
            stage_id="route-ready",
            status=StageStatus.RUNNING,
        ))
        result = StageResult(
            outcome=StageOutcome.FAIL,
            failure_class="service_has_no_endpoints",
            message="No ready endpoints",
        )
        updated = repository.update_stage(
            db_session, "run-001", "route-ready",
            status=StageStatus.FAILED,
            result=result,
            duration_seconds=82.5,
        )
        assert updated.status == StageStatus.FAILED
        assert updated.result.outcome == StageOutcome.FAIL
        assert updated.result.failure_class == "service_has_no_endpoints"
        assert updated.duration_seconds == 82.5


class TestEvidencePersistence:
    def test_create_and_get_evidence(self, db_session):
        ev = Evidence(
            evidence_id="ev-db-001",
            run_id="run-001",
            stage_id="namespace-ready",
            type="fixture",
            source="test",
            observed={"namespace_exists": True},
            result=StageOutcome.PASS,
            timestamp=datetime(2026, 5, 5, 14, 35, tzinfo=timezone.utc),
        )
        created = repository.create_evidence(db_session, ev)
        assert created.evidence_id == "ev-db-001"

        fetched = repository.get_evidence(db_session, "ev-db-001")
        assert fetched is not None
        assert fetched.observed["namespace_exists"] is True
        assert fetched.result == StageOutcome.PASS

    def test_create_evidence_with_resource(self, db_session):
        ev = Evidence(
            evidence_id="ev-db-002",
            run_id="run-001",
            stage_id="route-ready",
            type="openshift_resource_state",
            source="oc",
            resource=EvidenceResource(kind="Endpoints", namespace="ns-001", name="demo-app"),
            observed={"ready_endpoint_count": 0},
            result=StageOutcome.FAIL,
            timestamp=datetime(2026, 5, 5, 14, 35, tzinfo=timezone.utc),
        )
        created = repository.create_evidence(db_session, ev)
        fetched = repository.get_evidence(db_session, "ev-db-002")
        assert fetched.resource is not None
        assert fetched.resource.kind == "Endpoints"

    def test_list_evidence_for_stage(self, db_session):
        for i in range(3):
            repository.create_evidence(db_session, Evidence(
                evidence_id=f"ev-list-{i}",
                run_id="run-001",
                stage_id="namespace-ready",
                type="fixture",
                source="test",
                observed={"check": i},
                result=StageOutcome.PASS,
                timestamp=datetime(2026, 5, 5, 14, 35, tzinfo=timezone.utc),
            ))
        evidence_list = repository.list_evidence_for_stage(db_session, "run-001", "namespace-ready")
        assert len(evidence_list) == 3
