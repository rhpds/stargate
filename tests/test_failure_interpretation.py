"""TDD tests — Failure interpretation LLM prompt and endpoint."""

import yaml
from pathlib import Path


class TestFailureInterpretationPrompt:
    def test_prompt_file_exists(self):
        prompt_path = Path(__file__).parent.parent / "prompts" / "failure-interpretation.yaml"
        assert prompt_path.exists()

    def test_prompt_has_required_fields(self):
        prompt_path = Path(__file__).parent.parent / "prompts" / "failure-interpretation.yaml"
        data = yaml.safe_load(prompt_path.read_text())
        assert data["id"] == "failure-interpretation"
        assert "version" in data
        assert "system" in data
        assert "user_template" in data

    def test_prompt_template_has_evidence_placeholder(self):
        prompt_path = Path(__file__).parent.parent / "prompts" / "failure-interpretation.yaml"
        data = yaml.safe_load(prompt_path.read_text())
        assert "{evidence}" in data["user_template"]


class TestFailureInterpretationEndpoint:
    def test_endpoint_exists(self, client):
        resp = client.post("/dashboard/failure-interpretation", json={"run_id": "test", "stage_id": "test"})
        assert resp.status_code == 200

    def test_response_has_interpretation(self, client):
        resp = client.post("/dashboard/failure-interpretation", json={"run_id": "test", "stage_id": "test"})
        data = resp.json()
        assert "interpretation" in data
        assert "failure_class" in data
        assert "stage_id" in data
