"""RED/GREEN TDD — AAP provisioning job data integration."""

import re
import textwrap
import json


def test_durable_collection_keeps_all_jobs_and_each_jobs_own_evidence(monkeypatch):
    from collectors.aap import collect_aap as collector

    monkeypatch.setattr(collector, "_cache", {"data": None, "ts": 0})
    monkeypatch.setattr(collector, "load_aap_controllers", lambda: [
        {"name": "prod0", "url": "https://aap.example", "scope": "production"},
    ])
    jobs = [{"id": n, "name": "catalog.same.prod-test-provision", "status": "failed",
             "finished": "2026-10-14T12:00:00Z"} for n in range(601)]
    monkeypatch.setattr(collector, "_fetch_jobs", lambda c, query: jobs if "status=failed" in query else [])
    monkeypatch.setattr(collector, "_fetch_job_events", lambda c, job: [
        {"id": job + 1000, "task": f"Task {job}", "event_data": {"res": {"msg": f"Error {job}"}}},
    ])
    monkeypatch.setattr(collector, "_fetch_job_counts", lambda *a: {"failed": 601, "total": 601})
    result = collector.collect_aap_jobs()
    assert len(result["recent_events"]) == 601
    assert len(result["recent_failures"]) == 50
    for event in result["recent_events"]:
        assert event["failing_task"] == f'Task {event["job_id"]}'
        assert event["error"] == f'Error {event["job_id"]}'


def test_job_pagination_does_not_stop_after_500(monkeypatch):
    from collectors.aap import collect_aap as collector

    class Response:
        def __init__(self, data):
            self.data = data

        def read(self):
            return json.dumps(self.data).encode()

    pages = iter([
        {"results": [{"id": n, "artifacts": {"large": "x" * 10000},
                       "extra_vars": '{"password":"do-not-retain","target_host":"host.example"}'}
                      for n in range(600)], "next": "/api/v2/jobs/?page=2"},
        {"results": [{"id": 600}], "next": None},
    ])
    monkeypatch.setattr(collector.urllib.request, "urlopen", lambda *a, **kw: Response(next(pages)))
    result = collector._fetch_jobs({"url": "https://aap.example", "token": "test"}, "page_size=200")
    assert [job["id"] for job in result] == list(range(601))
    assert all("artifacts" not in job for job in result)
    assert "do-not-retain" not in json.dumps(result)
    assert json.loads(result[0]["extra_vars"])["target_host"] == "host.example"


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
