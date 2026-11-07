"""Tests for the MCP server layer.

Any MCP-compatible agent can hit /mcp (Streamable HTTP, stateless) with the
platform API key and query the platform's intelligence surfaces. Read-only.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def episodes_db():
    from db import models  # noqa: F401
    from db.database import Base
    from db.models import EvaluationRecord
    from tests.conftest import TestSession, test_engine

    Base.metadata.create_all(bind=test_engine)
    session = TestSession()
    now = datetime.now(timezone.utc)
    session.add_all([
        EvaluationRecord(run_id="gap-reclaim-mcp1", stage_id="destroy-complete",
                         lab_code="sandbox-mcp", cluster_name="ocpv05", outcome="pass",
                         failure_class=None, message="AAP destroy job 5 succeeded (reclamation-outcome/v1: reclaimed)",
                         evaluated_at=now - timedelta(hours=1)),
        EvaluationRecord(run_id="gap-teardown-mcp2", stage_id="destroy-complete",
                         lab_code="sandbox-mcp", cluster_name="ocpv05", outcome="fail",
                         failure_class="teardown_stuck", message="AnarchySubject s stuck in destroying for 5h",
                         evaluated_at=now - timedelta(minutes=30)),
    ])
    session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


class TestMCPServerTools:
    def test_server_defines_the_expected_tools(self):
        import asyncio
        from api.mcp_server import mcp
        tools = asyncio.run(mcp.list_tools())
        names = {t.name for t in tools}
        expected = {
            "query_lifecycle_outcomes", "list_reclamation_artifacts",
            "get_causal_chain", "query_evaluations", "get_failure_classes",
            "get_proof_matrix", "get_recent_episodes", "get_known_issues",
        }
        assert expected <= names, f"missing tools: {expected - names}"

    def test_get_recent_episodes_tool(self, episodes_db, monkeypatch):
        from tests.conftest import TestSession
        monkeypatch.setattr("db.database.get_session_factory", lambda: TestSession)
        from api.mcp_server import get_recent_episodes
        result = get_recent_episodes(hours=2, stage="destroy-complete")
        assert "sandbox-mcp" in result or "teardown_stuck" in result
        assert "destroy-complete" in result

    def test_get_failure_classes_tool_includes_lifecycle(self):
        from api.mcp_server import get_failure_classes
        result = get_failure_classes()
        classes = json.loads(result)
        names = {c["name"] for c in classes}
        assert "teardown_stuck" in names
        assert "workshop_provision_failed" in names

    def test_get_causal_chain_requires_a_key(self):
        from api.mcp_server import get_causal_chain
        result = get_causal_chain()
        assert result.startswith("ERROR")


class TestMCPEndpointAuth:
    """The MCP endpoint serves the Streamable HTTP protocol at /mcp/ with
    the platform API key; without it, 401.

    These tests share ONE client: the mounted MCP session manager starts
    with the app lifecycle and does not re-run across client restarts (in
    production the app starts once; the restart concern is test-only).
    """

    HEADERS = {"Accept": "application/json, text/event-stream"}
    INIT = {"jsonrpc": "2.0", "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "0"}},
            "id": 1}

    @pytest.fixture(scope="class")
    def mcp_client(self):
        from fastapi.testclient import TestClient
        from api.app import app
        with TestClient(app, headers={"X-API-Key": "test-key-for-ci"}) as c:
            yield c

    def test_mcp_without_key_is_401(self, mcp_client):
        resp = mcp_client.post("/mcp/", json=self.INIT,
                               headers={**self.HEADERS, "X-API-Key": ""})
        assert resp.status_code == 401

    def test_mcp_with_key_serves_protocol(self, mcp_client):
        resp = mcp_client.post("/mcp/", json=self.INIT, headers=self.HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("id") == 1
        assert "serverInfo" in body.get("result", {})

    def test_mcp_tools_list(self, mcp_client):
        init = mcp_client.post("/mcp/", json=self.INIT, headers=self.HEADERS)
        session_id = init.headers.get("mcp-session-id", "")
        resp = mcp_client.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 2},
            headers={**self.HEADERS, "Mcp-Session-Id": session_id},
        )
        assert resp.status_code == 200
        names = {t["name"] for t in resp.json().get("result", {}).get("tools", [])}
        assert {
            "query_lifecycle_outcomes", "list_reclamation_artifacts",
            "get_causal_chain", "query_evaluations", "get_failure_classes",
            "get_proof_matrix", "get_recent_episodes", "get_known_issues",
        } <= names

    def test_other_paths_unaffected(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200


class TestMCPServerReviewTools:
    """Review tools: opinions only, zero execution."""

    def test_review_and_comment_are_registered(self):
        import asyncio
        from api.mcp_server import mcp
        tools = asyncio.run(mcp.list_tools())
        names = {t.name for t in tools}
        assert "review_diagnosis" in names
        assert "comment_action" in names

    def test_review_nonexistent_investigation(self, db, monkeypatch):
        from api.mcp_server import review_diagnosis
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        result = review_diagnosis(99999, True, "test")
        assert "ERROR" in result
        assert "not found" in result

    def test_comment_nonexistent_action(self, db, monkeypatch):
        from api.mcp_server import comment_action
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        result = comment_action(99999, "test comment")
        assert "ERROR" in result

    def test_comment_empty_rejected(self):
        from api.mcp_server import comment_action
        result = comment_action(1, "")
        assert "ERROR" in result

    def test_review_creates_knowledge_entry(self, db, monkeypatch):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        from datetime import datetime, timezone
        from db.models import InvestigationRecord, KnowledgeEntry
        from api.mcp_server import review_diagnosis

        inv = InvestigationRecord(
            job_id="job-review-test", lab_code="sandbox-review",
            cluster="ocpv06", namespace="sandbox-review",
            failure_class="pods_crashlooping", trigger_type="auto_anomalous",
            status="complete", triggering_eval_id=None,
            created_at=datetime.now(timezone.utc),
            root_cause="database dependency unreachable",
            remediation_suggestion="restart the deployment",
        )
        db.add(inv)
        db.commit()

        result = review_diagnosis(inv.id, True, "confirmed by ops")
        assert "APPROVED" in result
        assert "knowledge base" in result

        entry = db.query(KnowledgeEntry).filter(
            KnowledgeEntry.investigation_id == inv.id).one()
        assert entry.root_cause == "database dependency unreachable"
        assert entry.remediation == "restart the deployment"
        assert entry.active is True
        assert entry.reviewed_by.startswith("mcp:")

    def test_review_rejected_no_knowledge(self, db, monkeypatch):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        from datetime import datetime, timezone
        from db.models import InvestigationRecord, KnowledgeEntry
        from api.mcp_server import review_diagnosis

        inv = InvestigationRecord(
            job_id="job-review-reject", lab_code="sandbox-reject",
            cluster="ocpv06", namespace="sandbox-reject",
            failure_class="oom_killed", trigger_type="auto_anomalous",
            status="complete", triggering_eval_id=None,
            created_at=datetime.now(timezone.utc),
            root_cause="memory limit too low",
            remediation_suggestion="increase memory limit",
        )
        db.add(inv)
        db.commit()

        result = review_diagnosis(inv.id, False, "wrong diagnosis")
        assert "REJECTED" in result
        assert "not be used" in result

        entries = db.query(KnowledgeEntry).filter(
            KnowledgeEntry.investigation_id == inv.id).count()
        assert entries == 0

    def test_review_idempotent(self, db, monkeypatch):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        from datetime import datetime, timezone
        from db.models import InvestigationRecord, KnowledgeEntry
        from api.mcp_server import review_diagnosis

        inv = InvestigationRecord(
            job_id="job-review-idem", lab_code="sandbox-idem",
            cluster="ocpv06", namespace="sandbox-idem",
            failure_class="pods_crashlooping", trigger_type="auto_anomalous",
            status="complete", triggering_eval_id=None,
            created_at=datetime.now(timezone.utc),
            root_cause="bad image tag",
            remediation_suggestion="fix the image tag",
            review_state="reviewed",
        )
        db.add(inv)
        db.flush()

        # Create the published knowledge entry (as if already reviewed)
        entry = KnowledgeEntry(
            signature="sandbox-idem:pods_crashlooping", version=1, active=True,
            root_cause="bad image tag", remediation="fix the image tag",
            provenance={"investigation_id": inv.id},
            investigation_id=inv.id,
            reviewed_by="mcp:test", reviewed_at=datetime.now(timezone.utc),
        )
        db.add(entry)
        db.commit()

        # Second review of already-reviewed + published investigation
        result = review_diagnosis(inv.id, True, "confirming again")
        assert "already reviewed" in result


def _known_issues_report():
    """Canned two-issue report matching the engine.known_issues contract
    (one platform_self, one lab_family). Tests patch the engine with this
    so they pin the MCP surface, not the detection logic."""
    return {
        "window_hours": 24,
        "generated_at": "2026-11-06T20:00:00Z",
        "issues": [
            {
                "signature": "showroom_not_ready|artifact:evaluator",
                "bucket": "platform_self",
                "title": "StarGate self-issue: showroom_not_ready across 4 namespaces",
                "failure_class": "showroom_not_ready",
                "cluster": None,
                "artifact_refs": ["evaluator"],
                "namespace_count": 4,
                "investigation_count": 4,
                "investigation_ids": [2422, 2425, 2431, 2435],
                "representative_investigation_id": 2422,
                "top_root_cause_excerpt": "StarGate evaluation race during normal namespace teardown",
                "remediation_excerpt": "fix the evaluator's namespace-existence probe",
                "first_seen": "2026-11-06T15:00:00Z",
                "last_seen": "2026-11-06T19:00:00Z",
                "verdict_counts": {"ACTIONABLE": 4, "TRANSIENT": 0, "other": 0},
            },
            {
                "signature": "showroom_not_ready|artifact:zerotouch-1.10.2",
                "bucket": "lab_family",
                "title": "showroom_not_ready across 10 namespaces — zerotouch-1.10.2",
                "failure_class": "showroom_not_ready",
                "cluster": None,
                "artifact_refs": ["zerotouch-1.10.2"],
                "namespace_count": 10,
                "investigation_count": 10,
                "investigation_ids": [2439, 2440, 2441],
                "representative_investigation_id": 2439,
                "top_root_cause_excerpt": "Helm chart bug: nginx/proxy port and SCC config",
                "remediation_excerpt": "fix the chart's proxy container ports and the SCC",
                "first_seen": "2026-11-06T02:00:00Z",
                "last_seen": "2026-11-06T18:00:00Z",
                "verdict_counts": {"ACTIONABLE": 9, "TRANSIENT": 1, "other": 0},
            },
        ],
        "summary": {
            "issues": 2,
            "platform": 0,
            "platform_self": 1,
            "lab_family": 1,
            "unknown": 0,
            "investigations_covered": 14,
            "namespaces_covered": 14,
        },
    }


class TestMCPKnownIssuesTool:
    """get_known_issues: formats the fleet rollup from
    engine.known_issues.detect_known_issues. The engine is patched —
    these tests never depend on the real detection logic."""

    @pytest.fixture
    def patched_engine(self, monkeypatch):
        report = _known_issues_report()
        captured = {}

        def fake_detect(db, window_hours=24, min_namespaces=3):
            captured["window_hours"] = window_hours
            return {**report, "window_hours": window_hours}

        monkeypatch.setattr("engine.known_issues.detect_known_issues", fake_detect)
        return report, captured

    def test_formats_both_issues_and_guidance(self, db, monkeypatch, patched_engine):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        from api.mcp_server import get_known_issues

        result = get_known_issues()

        assert "StarGate self-issue: showroom_not_ready across 4 namespaces" in result
        assert "showroom_not_ready across 10 namespaces — zerotouch-1.10.2" in result
        assert "[platform_self]" in result
        assert "[lab_family]" in result
        assert "Buckets: 1 platform_self, 1 lab_family" in result
        assert "14 investigations across 14 namespaces" in result
        assert "representative investigation: #2422" in result
        assert "Guidance:" in result

    def test_bucket_filter_returns_only_that_bucket(self, db, monkeypatch, patched_engine):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        from api.mcp_server import get_known_issues

        result = get_known_issues(bucket="lab_family")

        assert "[lab_family]" in result
        assert "zerotouch-1.10.2" in result
        assert "10 investigations across 10 namespaces" in result
        assert "StarGate self-issue" not in result
        assert "[platform_self]" not in result

    def test_empty_report_says_no_known_issues(self, db, monkeypatch):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        monkeypatch.setattr(
            "engine.known_issues.detect_known_issues",
            lambda db, window_hours=24, min_namespaces=3: {
                "window_hours": window_hours,
                "generated_at": "2026-11-06T20:00:00Z",
                "issues": [],
                "summary": {"issues": 0, "platform": 0, "platform_self": 0,
                            "lab_family": 0, "unknown": 0,
                            "investigations_covered": 0, "namespaces_covered": 0},
            },
        )
        from api.mcp_server import get_known_issues

        result = get_known_issues()
        assert "No known issues in the last 24h" in result
        assert "shared root cause" in result

    def test_window_hours_is_clamped_not_crashed(self, db, monkeypatch, patched_engine):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        from api.mcp_server import get_known_issues

        result = get_known_issues(window_hours=99999)

        _, captured = patched_engine
        assert captured["window_hours"] == 168  # clamped, not passed through
        assert "Known issues (last 168h)" in result

    def test_invalid_bucket_is_rejected(self, db, monkeypatch, patched_engine):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        from api.mcp_server import get_known_issues

        result = get_known_issues(bucket="bogus")
        assert result.startswith("ERROR")
        assert "platform_self" in result  # the message names the valid buckets


def test_mcp_audit_log_emits():
    """The /mcp audit emission must actually emit — it was silently dead
    (TWO NameErrors on unimported names, _logging and json, each hidden
    by except: pass) until a real client connected Nov 3 2026 and left
    no trace. Unit-tests the extracted pure function directly: no app,
    no client, no subprocess (the suite's effects guard blocks those),
    no ordering dependence.
    """
    import logging

    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture()
    mcp_log = logging.getLogger("stargate.mcp")
    mcp_log.disabled = False  # order-independent: alembic's fileConfig may have disabled it
    mcp_log.addHandler(handler)
    mcp_log.setLevel(logging.INFO)
    try:
        from api.app import emit_mcp_audit
        emit_mcp_audit("test-key-for-ci", "initialize", "", "/mcp/")
    finally:
        mcp_log.removeHandler(handler)

    msgs = [r.getMessage() for r in records]
    assert msgs, "the mcp audit line must emit"
    assert "method=initialize" in msgs[0]
    assert "key_id=" in msgs[0]  # attribution present
    import hashlib
    expected = hashlib.sha256(b"test-key-for-ci").hexdigest()[:8]
    assert expected in msgs[0]  # correct key_id derivation
