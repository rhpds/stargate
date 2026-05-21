"""TDD tests — LLM recommendation reasoning endpoint."""

import yaml
from pathlib import Path


class TestRecommendationReasoningPrompt:
    def test_prompt_exists(self):
        p = Path(__file__).parent.parent / "prompts" / "recommendation-reasoning.yaml"
        assert p.exists()

    def test_prompt_fields(self):
        p = Path(__file__).parent.parent / "prompts" / "recommendation-reasoning.yaml"
        data = yaml.safe_load(p.read_text())
        assert data["id"] == "recommendation-reasoning"
        assert "{evidence}" in data["user_template"]


class TestRecommendationReasoningEndpoint:
    def test_endpoint_exists(self, client):
        resp = client.post("/dashboard/recommendation-reasoning")
        assert resp.status_code == 200

    def test_response_structure(self, client):
        resp = client.post("/dashboard/recommendation-reasoning")
        data = resp.json()
        assert "prioritized" in data
        assert "summary" in data
        assert "llm_used" in data
