"""Database persistence tests — verify runs/stages/evidence are stored and queryable."""

import asyncio
from datetime import datetime, timezone

import pytest

from api.app.models import (
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


def run_async(coro):
    """Helper to run async repository functions in sync tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestRunPersistence:
    def test_create_and_get_run(self):
        run = Run(
            run_id="db-test-001",
            demo_id="demo-simple-container",
            namespace="ns-001",
            requested_by="tester",
            rubric_version="v0.1.0",
        )
        created = run_async(repository.create_run(run))
        assert created.run_id == "db-test-001"

        fetched = run_async(repository.get_run("db-test-001"))
        assert fetched is not None
        assert fetched.demo_id == "demo-simple-container"
        assert fetched.status == RunStatus.PENDING

    def test_get_run_not_found(self):
        assert run_async(repository.get_run("nonexistent")) is None

    def test_list_runs(self):
        for i in range(3):
            run_async(repository.create_run(Run(
                run_id=f"list-{i}",
                demo_id="demo",
                namespace="ns",
                requested_by="user",
                rubric_version="v0.1.0",
            )))
        runs = run_async(repository.list_runs())
        assert len(runs) == 3

    def test_update_run_status(self):
        run_async(repository.create_run(Run(
            run_id="status-test",
            demo_id="demo",
            namespace="ns",
            requested_by="user",
            rubric_version="v0.1.0",
        )))
        updated = run_async(repository.update_run_status("status-test", RunStatus.RUNNING))
        assert updated.status == RunStatus.RUNNING
        assert updated.started_at is not None

    def test_update_run_completed(self):
        run_async(repository.create_run(Run(
            run_id="complete-test",
            demo_id="demo",
            namespace="ns",
            requested_by="user",
            rubric_version="v0.1.0",
        )))
        run_async(repository.update_run_status("complete-test", RunStatus.RUNNING))
        updated = run_async(repository.update_run_status("complete-test", RunStatus.COMPLETED))
        assert updated.status == RunStatus.COMPLETED
        assert updated.completed_at is not None


class TestStagePersistence:
    def test_create_and_get_stage(self):
        stage = Stage(
            run_id="run-001",
            stage_id="namespace-ready",
            status=StageStatus.RUNNING,
            started_at=datetime(2026, 5, 5, 14, 30, tzinfo=timezone.utc),
        )
        created = run_async(repository.create_stage(stage))
        assert created.stage_id == "namespace-ready"

        fetched = run_async(repository.get_stage("run-001", "namespace-ready"))
        assert fetched is not None
        assert fetched.status == StageStatus.RUNNING

    def test_list_stages(self):
        for sid in ["namespace-ready", "deployment-ready", "route-ready"]:
            run_async(repository.create_stage(Stage(
                run_id="run-001", stage_id=sid, status=StageStatus.PENDING,
            )))
        stages = run_async(repository.list_stages("run-001"))
        assert len(stages) == 3

    def test_update_stage_with_result(self):
        run_async(repository.create_stage(Stage(
            run_id="run-001",
            stage_id="route-ready",
            status=StageStatus.RUNNING,
        )))
        result = StageResult(
            outcome=StageOutcome.FAIL,
            failure_class="service_has_no_endpoints",
            message="No ready endpoints",
        )
        updated = run_async(repository.update_stage(
            "run-001", "route-ready",
            status=StageStatus.FAILED,
            result=result,
            duration_seconds=82.5,
        ))
        assert updated.status == StageStatus.FAILED
        assert updated.result.outcome == StageOutcome.FAIL
        assert updated.result.failure_class == "service_has_no_endpoints"
        assert updated.duration_seconds == 82.5


class TestEvidencePersistence:
    def test_create_and_get_evidence(self):
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
        created = run_async(repository.create_evidence(ev))
        assert created.evidence_id == "ev-db-001"

        fetched = run_async(repository.get_evidence("ev-db-001"))
        assert fetched is not None
        assert fetched.observed["namespace_exists"] is True
        assert fetched.result == StageOutcome.PASS

    def test_create_evidence_with_resource(self):
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
        run_async(repository.create_evidence(ev))
        fetched = run_async(repository.get_evidence("ev-db-002"))
        assert fetched.resource is not None
        assert fetched.resource.kind == "Endpoints"

    def test_list_evidence_for_stage(self):
        for i in range(3):
            run_async(repository.create_evidence(Evidence(
                evidence_id=f"ev-list-{i}",
                run_id="run-001",
                stage_id="namespace-ready",
                type="fixture",
                source="test",
                observed={"check": i},
                result=StageOutcome.PASS,
                timestamp=datetime(2026, 5, 5, 14, 35, tzinfo=timezone.utc),
            )))
        evidence_list = run_async(repository.list_evidence_for_stage("run-001", "namespace-ready"))
        assert len(evidence_list) == 3
