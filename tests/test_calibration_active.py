"""RED/GREEN TDD — Item 1: Confidence calibration must be actively applied."""

from datetime import datetime, timezone
from unittest.mock import patch

from db.models import LLMFeedback, LLMMetric


class TestCalibrationApplied:
    """Calibration factors from human feedback must adjust LLM confidence."""

    def test_apply_feedback_produces_calibration(self, db):
        """apply_feedback() should produce calibration factors from feedback data."""
        from engine.learner import apply_feedback

        db.add(LLMFeedback(endpoint="classify", helpful=True, submitted_at=datetime.now(timezone.utc)))
        db.add(LLMFeedback(endpoint="classify", helpful=True, submitted_at=datetime.now(timezone.utc)))
        db.add(LLMFeedback(endpoint="classify", helpful=False, submitted_at=datetime.now(timezone.utc)))
        db.commit()

        result = apply_feedback(db)
        assert "classify" in result
        assert result["classify"]["calibration_factor"] == round(2 / 3, 3)

    def test_get_calibration_retrieves_factor(self, db):
        """get_calibration() should return the factor stored by apply_feedback()."""
        from engine.learner import apply_feedback, get_calibration

        db.add(LLMFeedback(endpoint="remediation", helpful=True, submitted_at=datetime.now(timezone.utc)))
        db.add(LLMFeedback(endpoint="remediation", helpful=True, submitted_at=datetime.now(timezone.utc)))
        db.commit()

        apply_feedback(db)
        cal = get_calibration(db, "remediation")
        assert cal is not None
        assert cal["calibration_factor"] == 1.0

    def test_no_calibration_returns_none(self, db):
        """With no feedback, get_calibration() returns None."""
        from engine.learner import get_calibration
        cal = get_calibration(db, "classify")
        assert cal is None

    def test_adjusted_confidence_column_exists(self):
        """LLMMetric model must have adjusted_confidence column."""
        assert hasattr(LLMMetric, "adjusted_confidence"), (
            "LLMMetric must have adjusted_confidence column"
        )

    def test_calibration_in_mv_refresh(self):
        """apply_feedback() must be called in the MV refresh loop."""
        from pathlib import Path
        src = Path(__file__).parent.parent / "api" / "app.py"
        text = src.read_text()
        assert "apply_feedback" in text, (
            "api/app.py must call apply_feedback() in the MV refresh loop"
        )

    def test_apply_calibration_function_exists(self):
        """A function to apply calibration to a confidence score must exist."""
        from engine.learner import apply_calibration
        assert callable(apply_calibration)

    def test_apply_calibration_adjusts_score(self, db):
        """apply_calibration should multiply base confidence by calibration factor."""
        from engine.learner import apply_feedback, apply_calibration

        db.add(LLMFeedback(endpoint="classify", helpful=True, submitted_at=datetime.now(timezone.utc)))
        db.add(LLMFeedback(endpoint="classify", helpful=False, submitted_at=datetime.now(timezone.utc)))
        db.commit()
        apply_feedback(db)

        adjusted = apply_calibration(db, "classify", 0.9)
        expected = 0.9 * 0.5
        assert abs(adjusted - expected) < 0.01, f"Expected ~{expected}, got {adjusted}"

    def test_apply_calibration_no_feedback_returns_raw(self, db):
        """With no calibration data, apply_calibration returns the raw score."""
        from engine.learner import apply_calibration
        adjusted = apply_calibration(db, "classify", 0.85)
        assert adjusted == 0.85
