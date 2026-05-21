"""TDD tests — Trend analysis LLM prompt and endpoint."""

import yaml
from pathlib import Path


class TestTrendAnalysisPrompt:
    def test_prompt_file_exists(self):
        prompt_path = Path(__file__).parent.parent / "prompts" / "trend-analysis.yaml"
        assert prompt_path.exists()

    def test_prompt_has_required_fields(self):
        prompt_path = Path(__file__).parent.parent / "prompts" / "trend-analysis.yaml"
        data = yaml.safe_load(prompt_path.read_text())
        assert data["id"] == "trend-analysis"
        assert "version" in data
        assert "system" in data
        assert "user_template" in data

    def test_prompt_mentions_patterns(self):
        prompt_path = Path(__file__).parent.parent / "prompts" / "trend-analysis.yaml"
        data = yaml.safe_load(prompt_path.read_text())
        assert "pattern" in data["system"].lower() or "trend" in data["system"].lower()


class TestTrendAnalysisEndpoint:
    def test_endpoint_exists(self, client):
        resp = client.post("/dashboard/trend-analysis")
        assert resp.status_code == 200

    def test_response_structure(self, client):
        resp = client.post("/dashboard/trend-analysis")
        data = resp.json()
        assert "analysis" in data
        assert "evidence_summary" in data
