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
