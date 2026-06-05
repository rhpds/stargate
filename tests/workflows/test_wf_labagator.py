"""Workflow tests — Labagator: session schedule collection."""

from unittest.mock import patch


class TestLabagatorCollection:

    def test_summarize_returns_dict(self):
        from collectors.labagator.collect_labagator import summarize_labs
        with patch("collectors.labagator.collect_labagator._get") as mock_get:
            mock_get.return_value = []
            result = summarize_labs()
        assert isinstance(result, dict)
        assert "total_labs" in result

    def test_empty_api_returns_zero_labs(self):
        from collectors.labagator.collect_labagator import summarize_labs
        with patch("collectors.labagator.collect_labagator._get") as mock_get:
            mock_get.return_value = []
            result = summarize_labs()
        assert result["total_labs"] == 0
