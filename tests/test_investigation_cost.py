"""Per-investigation cost and evidence sufficiency.

Both fields were written on only some paths: `cost_estimate` was accepted by
`complete_investigation()` but never passed by either caller, and
`evidence_sufficient` was set only on the usage-canary early return, so every
normal investigation reported `false`. These tests pin the return contract of
the agent loop, which is what both callers read.
"""

import pytest


def _tool_call(name: str) -> dict:
    return {
        "id": f"call-{name}",
        "type": "function",
        "function": {"name": name, "arguments": "{}"},
    }


def test_accumulates_cost_across_tool_and_final_calls(monkeypatch):
    import api.llm
    import engine.investigation_agent as agent

    monkeypatch.setattr(api.llm, "LLM_URL", "http://litellm.invalid/v1/chat/completions")
    monkeypatch.setattr(agent, "_usage_optimization_enabled", lambda job_id: False)
    monkeypatch.setattr(agent, "_dispatch_tool", lambda *args, **kwargs: "ok")

    replies = [
        {
            "success": True,
            "usage": {"cost_estimate": 0.011},
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    _tool_call(name) for name in (
                        "oc_read",
                        "query_evaluations",
                        "get_lab_identity",
                        "get_resolution_history",
                        "query_lifecycle_outcomes",
                    )
                ],
            },
        },
        {
            "success": True,
            "usage": {"cost_estimate": 0.024},
            "message": {
                "role": "assistant",
                "content": "### 6. Verdict\n\n> **ACTIONABLE**",
            },
        },
    ]
    monkeypatch.setattr(agent, "_call_llm_with_tools", lambda **kwargs: replies.pop(0))

    result = agent._run_investigation(
        namespace="sandbox-ab12c-ocp4",
        cluster="ocpv03",
        failure_class="pods_crashlooping",
        initial_evidence="evidence",
    )

    assert result["cost_estimate"] == pytest.approx(0.035)
    assert result["iterations"] == 2
    assert result["error"] is None


def test_unpriced_calls_leave_cost_null_rather_than_zero(monkeypatch):
    """A provider that reports no usage must not look like a free investigation."""
    import api.llm
    import engine.investigation_agent as agent

    monkeypatch.setattr(api.llm, "LLM_URL", "http://litellm.invalid/v1/chat/completions")
    monkeypatch.setattr(agent, "_usage_optimization_enabled", lambda job_id: False)
    monkeypatch.setattr(agent, "_dispatch_tool", lambda *args, **kwargs: "ok")
    monkeypatch.setattr(agent, "_call_llm_with_tools", lambda **kwargs: {
        "success": True,
        "message": {"role": "assistant", "content": "done"},
        "usage": {},
    })

    result = agent._run_investigation(
        namespace="sandbox-ab12c-ocp4",
        cluster="ocpv03",
        failure_class="pods_crashlooping",
        initial_evidence="evidence",
    )

    assert result["cost_estimate"] is None


def test_evidence_sufficiency_is_reported_on_the_normal_path(monkeypatch):
    """The non-canary return used to omit the key entirely, so callers saw False."""
    import api.llm
    import engine.investigation_agent as agent

    monkeypatch.setattr(api.llm, "LLM_URL", "http://litellm.invalid/v1/chat/completions")
    monkeypatch.setattr(agent, "_usage_optimization_enabled", lambda job_id: False)
    monkeypatch.setattr(agent, "_dispatch_tool", lambda *args, **kwargs: "ok")
    monkeypatch.setattr(agent, "_call_llm_with_tools", lambda **kwargs: {
        "success": True,
        "message": {"role": "assistant", "content": "done"},
        "usage": {"cost_estimate": 0.001},
    })

    thin = agent._run_investigation(
        namespace="sandbox-ab12c-ocp4",
        cluster="ocpv03",
        failure_class="pods_crashlooping",
        initial_evidence="evidence",
    )

    assert thin["evidence_sufficient"] is False


def test_agent_wall_budget_stays_inside_the_sweeper_deadline():
    """A budget above the 300 s sweeper can never be reached: the row is failed first."""
    from engine.investigation_agent import MAX_WALL_SECONDS

    assert MAX_WALL_SECONDS < 300
