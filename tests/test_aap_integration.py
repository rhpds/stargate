"""RED/GREEN TDD — AAP provisioning job data integration."""

import re
import textwrap


class TestAAPCollector:
    """AAP collector fetches provisioning job data from Tower controllers."""

    def test_collector_exists(self):
        from collectors.aap.collect_aap import collect_aap_jobs
        assert callable(collect_aap_jobs)

    def test_lab_code_extraction(self):
        from collectors.aap.collect_aap import extract_lab_code
        assert extract_lab_code("summit-2026.lb2144-agentops-ocp-cnv.event-jqphc-1-destroy") == "LB2144"
        assert extract_lab_code("summit-2026.lb1088-code-red-breach-challenge-cnv.dev-abc") == "LB1088"
        assert extract_lab_code("agd-v2.ocp-cluster-cnv-pools.event-xxx") is None

    def test_error_grouping(self):
        from collectors.aap.collect_aap import group_failures
        failures = [
            {"failing_task": "Task A", "error": "Error 1", "cluster": "ocpv05", "type": "provision"},
            {"failing_task": "Task A", "error": "Error 1", "cluster": "ocpv06", "type": "provision"},
            {"failing_task": "Task B", "error": "Error 2", "cluster": "ocpv05", "type": "destroy"},
        ]
        grouped = group_failures(failures)
        assert len(grouped) == 2
        assert grouped[0]["count"] == 2

    def test_production_inventory_prefers_bearer_tokens(self, tmp_path, monkeypatch):
        inventory = tmp_path / "controllers.yaml"
        inventory.write_text(textwrap.dedent("""
            controllers:
              - name: prod0
                scope: production
                url: https://prod0.example.test
                token: read-only-token
              - name: prod1
                scope: production
                url: https://prod1.example.test
                token: second-token
        """))
        monkeypatch.setenv("STARGATE_AAP_CONTROLLERS_FILE", str(inventory))
        from collectors.aap.collect_aap import load_aap_controllers, _authorization_header
        controllers = load_aap_controllers()
        assert [item["name"] for item in controllers] == ["prod0", "prod1"]
        assert all(item["scope"] == "production" for item in controllers)
        assert _authorization_header(controllers[0]) == "Bearer read-only-token"

    def test_inventory_failure_does_not_require_event_controllers(self, tmp_path, monkeypatch):
        inventory = tmp_path / "controllers.yaml"
        inventory.write_text("controllers: {}\n")
        monkeypatch.setenv("STARGATE_AAP_CONTROLLERS_FILE", str(inventory))
        monkeypatch.setenv("STARGATE_AAP_EVENT0_PASS", "legacy-password")
        from collectors.aap.collect_aap import load_aap_controllers
        assert load_aap_controllers() == []


class TestAAPDashboard:
    """AAP dashboard endpoint returns provisioning health."""

    def test_endpoint_exists(self, client):
        resp = client.get("/dashboard/aap")
        assert resp.status_code == 200

    def test_summary_has_sli(self, client):
        resp = client.get("/dashboard/aap")
        data = resp.json()
        assert "summary" in data
        assert "provision_sli_target" in data["summary"]

    def test_response_has_structure(self, client):
        resp = client.get("/dashboard/aap")
        data = resp.json()
        assert "top_errors" in data
        assert "by_cluster" in data
        assert "by_lab" in data


class TestAAPPrompt:
    """AAP failure analysis prompt exists for LLM."""

    def test_aap_prompt_exists(self):
        from pathlib import Path
        prompt = Path(__file__).parent.parent / "prompts" / "aap-failure.yaml"
        assert prompt.exists()

    def test_aap_prompt_has_version(self):
        import yaml
        from pathlib import Path
        prompt = Path(__file__).parent.parent / "prompts" / "aap-failure.yaml"
        data = yaml.safe_load(prompt.read_text())
        assert data.get("version") is not None


class TestAAPPolicyRules:
    """Policy rules for AAP failures."""

    def test_aap_rules_in_yaml(self):
        from pathlib import Path
        import yaml
        rules_file = Path(__file__).parent.parent / "policies" / "rules.yaml"
        data = yaml.safe_load(rules_file.read_text())
        rule_ids = [r["id"] for r in data.get("rules", [])]
        assert "aap_provision_failing" in rule_ids
