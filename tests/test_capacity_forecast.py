"""TDD tests — LLM capacity forecast prompt + capacity analysis endpoint."""

import yaml
from pathlib import Path


class TestCapacityForecastPrompt:
    def test_prompt_file_exists(self):
        prompt_path = Path(__file__).parent.parent / "prompts" / "capacity-forecast.yaml"
        assert prompt_path.exists()

    def test_prompt_has_required_fields(self):
        prompt_path = Path(__file__).parent.parent / "prompts" / "capacity-forecast.yaml"
        data = yaml.safe_load(prompt_path.read_text())
        assert data["id"] == "capacity-forecast"
        assert "version" in data
        assert "system" in data
        assert "user_template" in data
        assert data["max_tokens"] >= 1000

    def test_prompt_template_has_evidence_placeholder(self):
        prompt_path = Path(__file__).parent.parent / "prompts" / "capacity-forecast.yaml"
        data = yaml.safe_load(prompt_path.read_text())
        assert "{evidence}" in data["user_template"]

    def test_prompt_mentions_capacity(self):
        prompt_path = Path(__file__).parent.parent / "prompts" / "capacity-forecast.yaml"
        data = yaml.safe_load(prompt_path.read_text())
        assert "capacity" in data["system"].lower()


class TestCapacityAnalysisEndpoint:
    def test_endpoint_exists(self, client):
        resp = client.post("/dashboard/capacity-analysis")
        assert resp.status_code == 200

    def test_response_structure(self, client):
        resp = client.post("/dashboard/capacity-analysis")
        data = resp.json()
        assert "pool_velocities" in data
        assert "workload_complexities" in data
        assert "evidence_summary" in data


class TestPolicyRulesComplete:
    def test_all_provisioning_rules_exist(self):
        rules_path = Path(__file__).parent.parent / "policies" / "rules.yaml"
        data = yaml.safe_load(rules_path.read_text())
        rule_ids = [r["id"] for r in data["rules"]]
        assert "pool_exhaustion" in rule_ids
        assert "provision_blocked_lab" in rule_ids
        assert "pool_depletion_predicted" in rule_ids
        assert "workload_exceeds_capacity" in rule_ids
        assert "sandbox_api_degraded" in rule_ids
        assert "aap_sli_breach" in rule_ids

    def test_pool_depletion_has_thresholds(self):
        rules_path = Path(__file__).parent.parent / "policies" / "rules.yaml"
        data = yaml.safe_load(rules_path.read_text())
        rule = next(r for r in data["rules"] if r["id"] == "pool_depletion_predicted")
        assert "thresholds" in rule
        assert rule["thresholds"]["velocity_warn"] == -0.5
