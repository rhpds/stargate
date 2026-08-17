"""Tests for InvestigationRecord CRUD and query operations."""

import pytest
from datetime import datetime, timedelta, timezone


class TestInvestigationCRUD:
    def test_create_investigation(self, db):
        from db.repository import create_investigation
        rec = create_investigation(
            db, job_id="inv-test001", lab_code="sandbox-ab12c-ocp4",
            cluster="ocp-east", failure_class="pods_crashlooping",
        )
        assert rec.job_id == "inv-test001"
        assert rec.status == "queued"
        assert rec.trigger_type == "manual"
        assert rec.created_at is not None

    def test_create_auto_investigation(self, db):
        from db.repository import create_investigation
        rec = create_investigation(
            db, job_id="auto-abc123", lab_code="sandbox-xy99z-zt-rhel",
            cluster="ocp-west", failure_class="route_missing",
            trigger_type="auto",
        )
        assert rec.trigger_type == "auto"
        assert rec.status == "queued"

    def test_start_investigation(self, db):
        from db.repository import create_investigation, start_investigation, get_investigation
        create_investigation(db, job_id="inv-start01", lab_code="ns1", cluster="c1", failure_class="fc1")
        start_investigation(db, "inv-start01")
        rec = get_investigation(db, "inv-start01")
        assert rec.status == "running"
        assert rec.started_at is not None

    def test_complete_investigation(self, db):
        from db.repository import create_investigation, start_investigation, complete_investigation, get_investigation
        create_investigation(db, job_id="inv-done01", lab_code="ns1", cluster="c1", failure_class="fc1")
        start_investigation(db, "inv-done01")
        complete_investigation(
            db, "inv-done01",
            analysis="Root cause: image pull failure",
            tool_calls=[{"tool": "oc_read", "args": {}, "result_preview": "ok", "iteration": 0}],
            iterations=3,
            model_used="claude-sonnet-4-6",
            cost_estimate=0.015,
            root_cause="image pull failure",
            remediation_suggestion="Fix image tag in AgnosticV config",
            codebase_link="rhpds/agnosticv/published/ocp4/prod.yaml",
        )
        rec = get_investigation(db, "inv-done01")
        assert rec.status == "complete"
        assert rec.completed_at is not None
        assert rec.analysis == "Root cause: image pull failure"
        assert rec.iterations == 3
        assert len(rec.tool_calls) == 1
        assert rec.root_cause == "image pull failure"

    def test_fail_investigation(self, db):
        from db.repository import create_investigation, fail_investigation, get_investigation
        create_investigation(db, job_id="inv-fail01", lab_code="ns1", cluster="c1", failure_class="fc1")
        fail_investigation(db, "inv-fail01", "LLM timeout after 120s")
        rec = get_investigation(db, "inv-fail01")
        assert rec.status == "error"
        assert "LLM timeout" in rec.error
        assert rec.completed_at is not None

    def test_get_investigation_not_found(self, db):
        from db.repository import get_investigation
        assert get_investigation(db, "nonexistent") is None


class TestInvestigationQueries:
    def test_get_recent_investigation_found(self, db):
        from db.repository import create_investigation, complete_investigation, get_recent_investigation
        create_investigation(db, job_id="inv-recent01", lab_code="sandbox-ab12c-ocp4", cluster="c1", failure_class="pods_crashlooping")
        complete_investigation(db, "inv-recent01", analysis="done")
        result = get_recent_investigation(db, "sandbox-ab12c-ocp4", "pods_crashlooping", hours=4)
        assert result is not None
        assert result.job_id == "inv-recent01"

    def test_get_recent_investigation_different_failure_class(self, db):
        from db.repository import create_investigation, get_recent_investigation
        create_investigation(db, job_id="inv-diff01", lab_code="sandbox-ab12c-ocp4", cluster="c1", failure_class="route_missing")
        result = get_recent_investigation(db, "sandbox-ab12c-ocp4", "pods_crashlooping", hours=4)
        assert result is None

    def test_count_investigations_for_catalog_item(self, db):
        from db.repository import create_investigation, count_investigations_for_catalog_item
        create_investigation(db, job_id="inv-cat01", lab_code="sandbox-ab12c-ocp4", cluster="c1", failure_class="fc1")
        create_investigation(db, job_id="inv-cat02", lab_code="sandbox-xy99z-ocp4", cluster="c1", failure_class="fc2")
        count = count_investigations_for_catalog_item(db, "ocp4", hours=1)
        assert count == 2

    def test_count_investigations_today(self, db):
        from db.repository import create_investigation, count_investigations_today
        create_investigation(db, job_id="inv-today01", lab_code="ns1", cluster="c1", failure_class="fc1")
        create_investigation(db, job_id="inv-today02", lab_code="ns2", cluster="c1", failure_class="fc2")
        assert count_investigations_today(db) == 2

    def test_get_queued_investigations(self, db):
        from db.repository import create_investigation, start_investigation, get_queued_investigations
        create_investigation(db, job_id="inv-q1", lab_code="ns1", cluster="c1", failure_class="fc1")
        create_investigation(db, job_id="inv-q2", lab_code="ns2", cluster="c1", failure_class="fc2")
        create_investigation(db, job_id="inv-q3", lab_code="ns3", cluster="c1", failure_class="fc3")
        start_investigation(db, "inv-q2")  # no longer queued
        queued = get_queued_investigations(db, limit=5)
        assert len(queued) == 2
        assert queued[0].job_id == "inv-q1"  # oldest first

    def test_list_investigations_with_filters(self, db):
        from db.repository import create_investigation, list_investigations
        create_investigation(db, job_id="inv-list01", lab_code="ns1", cluster="east", failure_class="fc1")
        create_investigation(db, job_id="inv-list02", lab_code="ns2", cluster="west", failure_class="fc2")
        create_investigation(db, job_id="inv-list03", lab_code="ns1", cluster="east", failure_class="fc3")

        all_results = list_investigations(db)
        assert len(all_results) == 3

        by_lab = list_investigations(db, lab_code="ns1")
        assert len(by_lab) == 2

        by_cluster = list_investigations(db, cluster="west")
        assert len(by_cluster) == 1

    def test_link_investigation_to_resolution(self, db):
        from db.repository import create_investigation, complete_investigation, link_investigation_to_resolution, get_investigation
        create_investigation(db, job_id="inv-link01", lab_code="ns1", cluster="c1", failure_class="fc1")
        complete_investigation(db, "inv-link01", analysis="done")
        link_investigation_to_resolution(db, investigation_id=1, resolution_id=42)
        rec = get_investigation(db, "inv-link01")
        assert rec.resolved_by_id == 42
