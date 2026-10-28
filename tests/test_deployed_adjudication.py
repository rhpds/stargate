"""Contracts for the deployed v2.2 baseline, not undeployed v2.5 behavior."""
import json




def test_truncated_complete_json_and_missing_judge_slot_still_rejected():
    import pytest
    from engine.adjudication import _parse
    with pytest.raises(ValueError, match="model_failed_or_truncated"):
        _parse({**response(), "finish_reason": "length"}, {"initial": "evidence"})
    value = json.loads(response(judge=True)["content"])
    value["reviewer_verdicts"] = ["TRANSIENT"]
    with pytest.raises(ValueError, match="invalid_judge_comparison"):
        _parse({**response(judge=True), "content": json.dumps(value)}, {"initial": "evidence"}, judge=True)


def test_judge_malformed_json_and_string_boolean_not_repaired():
    import pytest
    from engine.adjudication import _parse
    value = json.loads(response(judge=True)["content"])
    value["verdict_agreement"] = "false"
    with pytest.raises(ValueError, match="invalid_judge_comparison"):
        _parse({**response(judge=True), "content": json.dumps(value)}, {"initial": "evidence"}, judge=True)
    malformed = json.dumps(value).replace('], "decision"', ', "decision"')
    with pytest.raises(ValueError):
        _parse({**response(judge=True), "content": malformed}, {"initial": "evidence"}, judge=True)





from db.repository import create_investigation


def setup_case(db, monkeypatch, job="adjudication-test"):
    monkeypatch.setenv("STARGATE_ADJUDICATION_ENABLED", "true")
    monkeypatch.setenv("STARGATE_ADJUDICATION_REVIEWERS", "reviewer-a,reviewer-b")
    monkeypatch.setenv("STARGATE_ADJUDICATION_JUDGE", "judge-c")
    return create_investigation(db, job_id=job, lab_code="sandbox-test", cluster="infra01", failure_class="test")


def response(judge=False):
    data = {"verdict": "TRANSIENT", "diagnosis": "Startup failure cleared", "root_cause": "Startup delay",
            "remediation": "Human review", "confidence": 20, "evidence_ids": ["initial"]}
    data["claims"] = [{"id": name, "status": "supported", "evidence_ids": ["initial"],
                       "explanation": "Observed in the evidence", "missing_evidence": ""}
                      for name in ("observation", "root_cause", "remediation")]
    if judge:
        data.update(decision="supported", rationale="Both reviews match the evidence",
                    reviewer_verdicts=["TRANSIENT", "TRANSIENT"], verdict_agreement=True)
    return {"success": True, "content": json.dumps(data), "finish_reason": "stop",
            "usage": {"total_tokens": 50}}


def test_blind_reviews_judge_and_idempotency(db, monkeypatch):
    from engine.adjudication import adjudicate
    from api import llm
    inv = setup_case(db, monkeypatch)
    calls = []

    def call(**kwargs):
        calls.append(kwargs)
        return response(judge=len(calls) == 3)

    monkeypatch.setattr(llm, "call_llm", call)
    result = adjudicate(db, inv.job_id, "PRIMARY-ANALYSIS", "initial evidence", ["full tool evidence"])
    assert result["status"] == "model_supported"
    assert len(calls) == 3
    for call in calls[:2]:
        prompt = json.dumps(call["messages"])
        assert "PRIMARY-ANALYSIS" not in prompt
        assert "full tool evidence" in prompt
        assert "reviews" not in json.loads(call["messages"][1]["content"])
    judge_input = json.loads(calls[2]["messages"][1]["content"])
    assert len(judge_input["reviews"]) == 2
    assert all(r["validated"] for r in judge_input["reviews"])
    assert judge_input["original_diagnosis"] == "PRIMARY-ANALYSIS"
    assert adjudicate(db, inv.job_id, "PRIMARY-ANALYSIS", "initial evidence", ["full tool evidence"])["id"] == result["id"]
    assert len(calls) == 3
    assert inv.review_state == "unreviewed"


def test_budget_and_excluded_cluster_make_no_model_calls(db, monkeypatch):
    from engine.adjudication import adjudicate
    from api import llm
    inv = setup_case(db, monkeypatch)
    monkeypatch.setenv("STARGATE_ADJUDICATION_DAILY_LIMIT", "0")
    monkeypatch.setattr(llm, "call_llm", lambda **kw: (_ for _ in ()).throw(AssertionError()))
    assert adjudicate(db, inv.job_id, "analysis", "evidence", [])["status"] == "budget_exhausted"
    inv.cluster = "ocpv06"
    db.commit()
    assert adjudicate(db, inv.job_id, "analysis", "evidence", [])["status"] == "excluded"


def test_failed_reviewer_requires_human_and_is_not_retried(db, monkeypatch):
    from engine.adjudication import adjudicate
    from api import llm
    inv = setup_case(db, monkeypatch)
    calls = []

    def fail(**kwargs):
        calls.append(kwargs)
        return {"success": False, "error": "unavailable"}

    monkeypatch.setattr(llm, "call_llm", fail)
    result = adjudicate(db, inv.job_id, "analysis", "evidence", [])
    assert result["status"] == "needs_human_review"
    assert len(calls) == 2
    adjudicate(db, inv.job_id, "analysis", "evidence", [])
    assert len(calls) == 2


def test_oversized_evidence_not_silently_truncated(db, monkeypatch):
    from engine.adjudication import adjudicate
    from api import llm
    inv = setup_case(db, monkeypatch)
    monkeypatch.setattr(llm, "call_llm", lambda **kw: (_ for _ in ()).throw(AssertionError()))
    result = adjudicate(db, inv.job_id, "analysis", "evidence", ["x" * 70000])
    assert result["status"] == "needs_human_review"
    assert result["reason"] == "evidence_over_budget"


def test_daily_budget_counts_failed_cases(db, monkeypatch):
    from engine.adjudication import adjudicate
    from api import llm
    first = setup_case(db, monkeypatch)
    monkeypatch.setenv("STARGATE_ADJUDICATION_DAILY_LIMIT", "1")
    monkeypatch.setattr(llm, "call_llm", lambda **kw: {"success": False})
    assert adjudicate(db, first.job_id, "analysis", "evidence", [])["status"] == "needs_human_review"
    second = create_investigation(db, job_id="second", lab_code="sandbox-other", cluster="infra01", failure_class="test")
    assert adjudicate(db, second.job_id, "analysis", "evidence", [])["status"] == "budget_exhausted"


def test_disagreeing_reviews_go_to_human(db, monkeypatch):
    from engine.adjudication import adjudicate
    from api import llm
    inv = setup_case(db, monkeypatch)
    calls = []

    def call(**kwargs):
        calls.append(kwargs)
        result = response(judge=len(calls) == 3)
        if len(calls) == 2:
            value = json.loads(result["content"])
            value["verdict"] = "ACTIONABLE"
            result["content"] = json.dumps(value)
        return result

    monkeypatch.setattr(llm, "call_llm", call)
    assert adjudicate(db, inv.job_id, "analysis", "evidence", [])["status"] == "needs_human_review"
    assert len(calls) == 3


def test_agent_hook_preserves_full_tool_results_and_does_not_execute(db, monkeypatch):
    from engine import investigation_agent as agent
    from engine import adjudication
    inv = setup_case(db, monkeypatch)

    def investigate(*args, **kwargs):
        kwargs["evidence_sink"].append("full evidence beyond the UI preview")
        return {"analysis": "Original diagnosis", "error": None}

    def review(db, job_id, analysis, initial, tools, **kwargs):
        assert analysis == "Original diagnosis"
        assert tools == ["full evidence beyond the UI preview"]
        return {"status": "needs_human_review", "reason": "disagreement"}

    monkeypatch.setattr(agent, "_run_investigation", investigate)
    monkeypatch.setattr(adjudication, "adjudicate", review)
    result = agent.run_investigation("sandbox-test", "infra01", "test", "evidence", db=db, job_id=inv.job_id)
    assert "Original diagnosis" in result["analysis"]
    assert "needs_human_review" in result["analysis"]
    assert "No remediation was executed" in result["analysis"]
    assert inv.review_state == "unreviewed"


def test_adjudication_queue_api(client, db, monkeypatch):
    from engine.adjudication import adjudicate
    from api import llm
    inv = setup_case(db, monkeypatch)
    monkeypatch.setattr(llm, "call_llm", lambda **kw: {"success": False})
    adjudicate(db, inv.job_id, "analysis", "evidence", [])
    result = client.get("/admin/functional/adjudications?status=needs_human_review")
    assert result.status_code == 200
    assert result.json()["items"][0]["investigation_id"] == inv.id
    assert result.json()["auto_remediation"] is False
    assert client.get("/admin/functional/adjudications", headers={"X-API-Key": "invalid"}).status_code in (401, 403)


def test_insufficient_wall_budget_does_not_start_models(db, monkeypatch):
    from engine.adjudication import adjudicate
    from api import llm
    inv = setup_case(db, monkeypatch)
    monkeypatch.setattr(llm, "call_llm", lambda **kw: (_ for _ in ()).throw(AssertionError()))
    result = adjudicate(db, inv.job_id, "analysis", "evidence", [], wall_budget=30)
    assert result["status"] == "needs_human_review"
    assert result["reason"] == "review_time_budget_unavailable"


def test_additive_migration_and_rollback_in_isolated_database():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from db.models import InvestigationRecord
    path = Path(__file__).resolve().parents[1] / "alembic/versions/f6a7b8c9d0e1_adjudication_ledger.py"
    spec = importlib.util.spec_from_file_location("adjudication_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        InvestigationRecord.__table__.create(conn)
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert "adjudications" in inspect(conn).get_table_names()
            assert inspect(conn).get_unique_constraints("adjudications")[0]["column_names"] == ["investigation_id", "diagnosis_version", "evidence_hash"]
            migration.downgrade()
            assert "adjudications" not in inspect(conn).get_table_names()
            assert "investigations" in inspect(conn).get_table_names()
    engine.dispose()


def test_json_wrapped_in_prose_is_schema_checked():
    from engine.adjudication import _parse
    value = response(judge=True)
    value["content"] = "Review follows:\n```json\n" + value["content"] + "\n```"
    assert _parse(value, {"initial": "evidence"}, judge=True)["decision"] == "supported"


def test_allowed_ids_are_explicit_and_nested_keys_are_rejected():
    import pytest
    from engine.adjudication import _parse
    bad = response()
    value = json.loads(bad["content"])
    value["evidence_ids"] = ["historical_evaluations"]
    bad["content"] = json.dumps(value)
    with pytest.raises(ValueError, match="invalid_evidence_citations"):
        _parse(bad, {"initial": "historical_evaluations are nested data, not an ID"})


def test_judge_cannot_claim_agreement_when_verdicts_differ(db, monkeypatch):
    from engine.adjudication import adjudicate
    from api import llm
    inv = setup_case(db, monkeypatch)
    calls = []
    def call(**kwargs):
        calls.append(kwargs)
        assert json.loads(kwargs["messages"][1]["content"])["allowed_evidence_ids"] == ["initial"]
        result = response(judge=len(calls) == 3)
        value = json.loads(result["content"])
        if len(calls) < 3:
            value["verdict"] = "ACTIONABLE"
        else:
            value["reviewer_verdicts"] = ["ACTIONABLE", "ACTIONABLE"]
            value["verdict_agreement"] = True
        result["content"] = json.dumps(value)
        return result
    monkeypatch.setattr(llm, "call_llm", call)
    result = adjudicate(db, inv.job_id, "analysis", "evidence", [])
    assert result["status"] == "needs_human_review"
    assert "judge_agreement_mismatch" in result["judge"]["consistency_checks"]


def test_unknown_causal_claim_prevents_model_supported(db, monkeypatch):
    from engine.adjudication import adjudicate
    from api import llm
    inv = setup_case(db, monkeypatch)
    calls = []
    def call(**kwargs):
        calls.append(kwargs)
        result = response(judge=len(calls) == 3)
        value = json.loads(result["content"])
        value["claims"][1].update(status="unknown", evidence_ids=[], missing_evidence="Need a time-correlated failing probe")
        result["content"] = json.dumps(value)
        return result
    monkeypatch.setattr(llm, "call_llm", call)
    result = adjudicate(db, inv.job_id, "analysis", "evidence", [])
    assert result["status"] == "needs_human_review"
    assert "unsupported_original_claims" in result["judge"]["consistency_checks"]


def test_invalid_reviewer_can_inform_judge_but_never_passes_gate(db, monkeypatch):
    from engine.adjudication import adjudicate
    from api import llm
    inv = setup_case(db, monkeypatch)
    calls = []
    def call(**kwargs):
        calls.append(kwargs)
        value = json.loads(response(judge=len(calls) == 3)["content"])
        if len(calls) == 1:
            value["claims"][2]["evidence_ids"] = []
        if len(calls) == 3:
            packet = json.loads(kwargs["messages"][1]["content"])
            assert packet["reviews"][0]["validated"] is False
            value.update(reviewer_verdicts=["INVALID", "TRANSIENT"], verdict_agreement=False)
        return {"success": True, "content": json.dumps(value), "finish_reason": "stop", "usage": {"total_tokens": 10}}
    monkeypatch.setattr(llm, "call_llm", call)
    result = adjudicate(db, inv.job_id, "analysis", "evidence", [])
    assert len(calls) == 3
    assert result["status"] == "needs_human_review"
    assert "invalid_reviewer" in result["judge"]["consistency_checks"]


def test_supported_cannot_have_unresolved_evidence():
    import pytest
    from engine.adjudication import _parse
    value = json.loads(response()["content"])
    value["claims"][1]["missing_evidence"] = "Need the failing probe"
    with pytest.raises(ValueError, match="supported_claim_has_missing_evidence"):
        _parse({"success": True, "content": json.dumps(value)}, {"initial": "evidence"})


def test_judge_verdict_objects_normalize_without_changing_meaning():
    from engine.adjudication import _parse
    value = json.loads(response(judge=True)["content"])
    value["reviewer_verdicts"] = [{"verdict": "ACTIONABLE"}, {"verdict": "UNKNOWN"}]
    parsed = _parse({"success": True, "content": json.dumps(value)}, {"initial": "evidence"}, judge=True)
    assert parsed["reviewer_verdicts"] == ["ACTIONABLE", "UNKNOWN"]
    assert parsed["reviewer_verdicts_raw"] == value["reviewer_verdicts"]
