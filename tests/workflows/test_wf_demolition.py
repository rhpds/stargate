"""Workflow tests — Demolition: smoke test result collection."""

from unittest.mock import patch, MagicMock


class TestDemolitionCollection:

    def test_summarize_returns_dict(self):
        from collectors.demolition.collect_demolition import summarize_sessions
        with patch("collectors.demolition.collect_demolition._get") as mock_get:
            mock_get.return_value = []
            result = summarize_sessions()
        assert isinstance(result, dict)
        assert "total_sessions" in result

    def test_find_tracked_returns_list(self):
        from collectors.demolition.collect_demolition import find_tracked_sessions
        with patch("collectors.demolition.collect_demolition._get") as mock_get:
            mock_get.return_value = []
            result = find_tracked_sessions()
        assert isinstance(result, list)
