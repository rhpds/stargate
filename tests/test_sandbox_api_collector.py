"""TDD tests — Sandbox-API collector: health observation + sandbox counts."""


class TestSandboxAPIHealth:
    def test_collect_sandbox_api_health_function_exists(self):
        from collectors.sandbox_api.collect_sandbox_api import collect_sandbox_api_health
        assert callable(collect_sandbox_api_health)

    def test_collect_sandbox_api_health_returns_required_fields(self):
        from collectors.sandbox_api.collect_sandbox_api import collect_sandbox_api_health
        result = collect_sandbox_api_health("")
        assert "api_healthy" in result
        assert "replicas_desired" in result
        assert "replicas_ready" in result
        assert "pod_statuses" in result
        assert "api_version" in result


class TestSandboxCounts:
    def test_collect_sandbox_counts_empty(self):
        from collectors.sandbox_api.collect_sandbox_api import collect_sandbox_counts
        result = collect_sandbox_counts([])
        assert result["total_sandboxes"] == 0
        assert result["active"] == 0
        assert result["failing"] == 0

    def test_collect_sandbox_counts_with_data(self):
        from collectors.sandbox_api.collect_sandbox_api import collect_sandbox_counts
        scanner_data = [
            {"cluster": "ocpv05", "sandbox_active": 10, "sandbox_failing": 2, "sandbox_crashloop": 1},
            {"cluster": "ocpv06", "sandbox_active": 15, "sandbox_failing": 0, "sandbox_crashloop": 0},
        ]
        result = collect_sandbox_counts(scanner_data)
        assert result["total_sandboxes"] == 27
        assert result["active"] == 25
        assert result["failing"] == 2
        assert result["crashloop"] == 1
        assert "ocpv05" in result["by_cluster"]
        assert "ocpv06" in result["by_cluster"]


class TestSummarizeSandboxAPI:
    def test_summarize_returns_combined_fields(self):
        from collectors.sandbox_api.collect_sandbox_api import summarize_sandbox_api, _cache
        _cache["data"] = None
        _cache["ts"] = 0
        result = summarize_sandbox_api("", scanner_data=[
            {"cluster": "test", "sandbox_active": 5, "sandbox_failing": 1, "sandbox_crashloop": 0},
        ])
        assert "api_healthy" in result
        assert "total_sandboxes" in result
        assert result["total_sandboxes"] == 6
        assert "timestamp" in result


class TestSandboxAPIDashboard:
    def test_sandbox_api_endpoint_exists(self, client):
        resp = client.get("/dashboard/sandbox-api")
        assert resp.status_code == 200
        data = resp.json()
        assert "api_healthy" in data
        assert "total_sandboxes" in data

    def test_freshness_includes_sandbox_api(self):
        from api.contracts import get_freshness
        freshness = get_freshness()
        assert "sandbox_api" in freshness


class TestSandboxAPIPolicy:
    def test_sandbox_api_degraded_rule_exists(self):
        import yaml
        from pathlib import Path
        rules_path = Path(__file__).parent.parent / "policies" / "rules.yaml"
        data = yaml.safe_load(rules_path.read_text())
        rule_ids = [r["id"] for r in data["rules"]]
        assert "sandbox_api_degraded" in rule_ids
