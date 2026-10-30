"""RED/GREEN TDD — Auto LLM analysis wired into MV refresh loop."""

from datetime import datetime, timezone

from db.models import EvaluationRecord, ProposedClassification


class TestAutoLLM:
    """Auto-LLM analysis must find and classify unclassified failures."""

    def test_auto_llm_module_exists(self):
        from engine.auto_llm import run_auto_analysis
        assert callable(run_auto_analysis)

    def test_no_failures_returns_zero(self, db):
        from engine.auto_llm import run_auto_analysis
        result = run_auto_analysis(db)
        assert result["classified"] == 0

    def test_already_classified_skipped(self, db):
        from engine.auto_llm import run_auto_analysis
        db.add(EvaluationRecord(
            run_id="run-1", stage_id="deployment-ready", outcome="fail",
            failure_class="pods_not_ready", message="test failure",
            evaluated_at=datetime.now(timezone.utc),
        ))
        db.add(ProposedClassification(
            run_id="run-1", stage_id="deployment-ready",
            proposed_class="pods_not_ready", confidence=0.9,
            proposed_at=datetime.now(timezone.utc),
        ))
        db.commit()

        result = run_auto_analysis(db)
        assert result["classified"] == 0

    def test_auto_llm_in_mv_refresh(self):
        """auto_llm must be called in the MV refresh loop."""
        from pathlib import Path
        src = Path(__file__).parent.parent / "api" / "app.py"
        text = src.read_text()
        assert "run_auto_analysis" in text

    def test_max_calls_per_cycle_enforced(self):
        from engine.auto_llm import MAX_CALLS_PER_CYCLE
        assert MAX_CALLS_PER_CYCLE <= 20


class TestAutoClassifyPromptContract:
    """The auto pipeline must send the classify prompt's task/format template.

    Regression for the 2026-10-29 production failure: _classify_failure sent
    evidence-only user content, so the model invented its own JSON schema
    ({"failure_classification": ...}), failed the quality gate on every call,
    and classified nothing ("classified 0, errors 20").
    """

    def test_classify_sends_prompt_template_and_taxonomy(self, db):
        from unittest.mock import patch
        from engine import auto_llm

        class _Ev:
            run_id = "r1"
            stage_id = "s1"
            message = "pod crashed with OOMKilled"
            lab_code = "lab-x"
            cluster_name = "c1"
            failure_class = None
            criteria_results = None

        captured = {}

        def fake_call_llm(**kwargs):
            captured.update(kwargs)
            return {
                "success": True,
                "content": '{"proposed_class": "oom_killed", "conditions": ["pod restart detected"], "confidence": 0.9, "reasoning": "exit 137"}',
                "metric_id": None, "usage": {}, "latency_ms": 1,
                "finish_reason": "stop", "error": None,
            }

        with patch("api.llm.call_llm", fake_call_llm):
            auto_llm._classify_failure(db, _Ev())

        user_content = captured["messages"][1]["content"]
        assert "## Task" in user_content, "must include the prompt's task template"
        assert '"proposed_class"' in user_content, "must include the JSON format contract"
        assert "## Known Failure Classes" in user_content
        # The taxonomy list (what the flywheel qualified), not a hardcoded
        # sandbox-only list.
        assert "teardown_stuck" in user_content or "ceph_health_warning" in user_content

    def test_persisted_proposal_quality_details_are_json_serializable(self, db):
        """Regression for the 2026-10-29 production crash: quality_details
        carried a datetime from model_dump(), so every quality-passing
        classify crashed the proposal INSERT (no proposal since June 2)."""
        import json as _json
        from datetime import datetime, timezone
        from unittest.mock import patch
        from db.models import ProposedClassification
        from engine import auto_llm

        class _Ev:
            run_id = "r-json"
            stage_id = "s1"
            message = "pod crashed with OOMKilled exit 137"
            lab_code = "lab-json"
            cluster_name = "c1"
            failure_class = None
            criteria_results = None

        def fake_call_llm(**kwargs):
            return {
                "success": True,
                "content": '{"proposed_class": "oom_killed", "conditions": ["exit code 137"], "confidence": 0.9, "reasoning": "OOMKilled exit 137"}',
                "metric_id": None, "usage": {}, "latency_ms": 1,
                "finish_reason": "stop", "error": None,
            }

        with patch("api.llm.call_llm", fake_call_llm):
            auto_llm._classify_failure(db, _Ev())

        proposal = db.query(ProposedClassification).filter(
            ProposedClassification.run_id == "r-json").one()
        if proposal.quality_details is not None:
            # Must round-trip through the JSON serializer used by the DB.
            _json.dumps(proposal.quality_details)
            assert "timestamp" not in proposal.quality_details or isinstance(
                proposal.quality_details.get("timestamp"), str)
