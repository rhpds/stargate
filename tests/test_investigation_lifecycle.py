"""Tests for the investigation agent's lifecycle-outcome integration.

Pins the phase-5 wiring: the query_lifecycle_outcomes tool, the
outcome-conditional TRANSIENT rule in the system prompt, dispatcher routing,
and metering of the previously-invisible tool-loop LLM calls.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import TestSession, test_engine


@pytest.fixture
def seeded_db():
    """Session with lifecycle episodes the tool can query (its own factory)."""
    from db import models  # noqa: F401
    from db.database import Base
    from db.models import EvaluationRecord

    Base.metadata.create_all(bind=test_engine)
    session = TestSession()
    now = datetime.now(timezone.utc)
    records = [
        EvaluationRecord(run_id="gap-reclaim-abc123", stage_id="destroy-complete",
                         lab_code="sandbox-xyz", cluster_name="ocpv05", outcome="pass",
                         failure_class=None, message="AAP destroy job 99 for sandbox-xyz succeeded (reclamation-outcome/v1: reclaimed)",
                         evaluated_at=now - timedelta(hours=2)),
        EvaluationRecord(run_id="gap-teardown-def456", stage_id="destroy-complete",
                         lab_code="sandbox-xyz", cluster_name="ocpv05", outcome="fail",
                         failure_class="teardown_stuck",
                         message="AnarchySubject subj-1 stuck in destroying for 5.2h",
                         evaluated_at=now - timedelta(hours=1)),
        EvaluationRecord(run_id="gap-wp-789abc", stage_id="provisioning",
                         lab_code="sandbox-abc", cluster_name="babylon", outcome="fail",
                         failure_class="workshop_provision_stalled",
                         message="WorkshopProvision sandbox-abc stalled", evaluated_at=now),
    ]
    session.add_all(records)
    session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=test_engine)


def _patch_factory(monkeypatch):
    monkeypatch.setattr("db.database.get_session_factory", lambda: TestSession)


class TestLifecycleOutcomesTool:
    def test_returns_episodes_with_interpretation(self, seeded_db, monkeypatch):
        from engine.investigation_agent import tool_query_lifecycle_outcomes

        _patch_factory(monkeypatch)
        result = tool_query_lifecycle_outcomes("sandbox-xyz")
        assert "destroy-complete" in result
        assert "teardown_stuck" in result
        assert "Summary: 2 episodes — 1 pass, 1 fail" in result
        # The interpretation guidance is the point of the tool.
        assert "reclaimed" in result
        assert "not staleness" in result

    def test_no_episodes_does_not_infer_an_outcome(self, seeded_db, monkeypatch):
        from engine.investigation_agent import tool_query_lifecycle_outcomes

        _patch_factory(monkeypatch)
        result = tool_query_lifecycle_outcomes("sandbox-does-not-exist")
        assert "No lifecycle outcome episodes found" in result
        assert "do not infer" in result

    def test_db_error_returns_error_string(self, monkeypatch):
        from engine.investigation_agent import tool_query_lifecycle_outcomes

        def boom():
            raise RuntimeError("db down")

        monkeypatch.setattr("db.database.get_session_factory", boom)
        result = tool_query_lifecycle_outcomes("anywhere")
        assert result.startswith("ERROR querying lifecycle outcomes")

    def test_dispatcher_routes_the_tool(self):
        from engine.investigation_agent import _dispatch_tool

        result = _dispatch_tool("query_lifecycle_outcomes", {"namespace": "x"}, "c", "")
        assert not result.startswith("Unknown tool")

    def test_tool_is_registered_with_guidance(self):
        from engine.investigation_agent import TOOLS

        tool = next(t for t in TOOLS if t["function"]["name"] == "query_lifecycle_outcomes")
        assert "deleted namespace" in tool["function"]["description"]


class TestTransientRuleContract:
    def test_system_prompt_is_outcome_conditional(self):
        """The TRANSIENT rule must consult lifecycle outcomes before treating
        a deleted namespace as stale — a failed teardown is the finding."""
        from engine.investigation_agent import AGENT_SYSTEM_PROMPT

        assert "query_lifecycle_outcomes" in AGENT_SYSTEM_PROMPT
        assert "FAIL destroy-complete episode" in AGENT_SYSTEM_PROMPT
        assert "is itself the finding" in AGENT_SYSTEM_PROMPT
        # The safety floor survives: never ACTIONABLE solely from deletion.
        assert "never ACTIONABLE solely from a deleted namespace" in AGENT_SYSTEM_PROMPT


class TestToolCallMetering:
    def test_tool_loop_calls_are_metered(self, db, monkeypatch):
        """The tool-loop LLM calls were invisible to llm_metrics despite
        being the bulk of agent spend; they must now be recorded."""
        from db.models import LLMMetric
        from engine import investigation_agent

        fake_response = MagicMock()
        fake_response.read.return_value = __import__("json").dumps({
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        }).encode()
        fake_response.__enter__ = lambda s: s
        fake_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=fake_response), \
             patch("api.llm.LLM_URL", "http://fake"), \
             patch("api.llm.LLM_API_KEY", "k"):
            result = investigation_agent._call_llm_with_tools(
                messages=[{"role": "user", "content": "x"}],
                tools=[],
                model="claude-sonnet-4-6",
                db=db,
            )
        assert result["success"] is True
        metric = db.query(LLMMetric).filter(
            LLMMetric.endpoint == "agent-investigation-tools").one()
        assert metric.model == "claude-sonnet-4-6"
        assert metric.success is True
        assert metric.total_tokens == 120

    def test_failed_tool_call_is_metered_with_error(self, db, monkeypatch):
        from db.models import LLMMetric
        from engine import investigation_agent

        with patch("urllib.request.urlopen", side_effect=TimeoutError("boom")), \
             patch("api.llm.LLM_URL", "http://fake"), \
             patch("api.llm.LLM_API_KEY", "k"):
            result = investigation_agent._call_llm_with_tools(
                messages=[], tools=[], db=db)
        assert result["success"] is False
        metric = db.query(LLMMetric).filter(
            LLMMetric.endpoint == "agent-investigation-tools").one()
        assert metric.success is False
        assert metric.error_type == "tool_call_error"
