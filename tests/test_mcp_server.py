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
            "get_proof_matrix", "get_recent_episodes",
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
            "get_proof_matrix", "get_recent_episodes",
        } <= names

    def test_other_paths_unaffected(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
