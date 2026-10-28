"""Chaos endpoint contracts use synthetic runner results, never live experiments."""

from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def chaos_runner(monkeypatch):
    from engine import chaos_scenarios

    def synthetic_result(scenario, kubeconfig, db=None):
        return {
            "scenario": scenario.name,
            "passed": True,
            "evidence_source": "synthetic-unit-test",
            "steps": {
                "deploy": {"success": True},
                "evaluate_before": {"outcome": "fail", "match": True},
                "evaluate_after": {"outcome": "pass", "match": True},
            },
        }

    runner = Mock(side_effect=synthetic_result)
    monkeypatch.setattr(chaos_scenarios, "run_chaos_scenario", runner)
    return runner


class TestChaosScenarios:
    """Chaos test framework must exist and have proper structure."""

    def test_chaos_endpoint_exists(self, client, chaos_runner, unit_external_effects_guard):
        from engine.chaos_scenarios import CHAOS_SCENARIOS

        resp = client.post("/admin/run-chaos-test")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "receipt" in data
        assert chaos_runner.call_count == len(CHAOS_SCENARIOS)
        assert [call.args[0].name for call in chaos_runner.call_args_list] == [
            scenario.name for scenario in CHAOS_SCENARIOS
        ]
        assert all(r["evidence_source"] == "synthetic-unit-test" for r in data["results"])
        assert data["receipt"]["passed"] == len(CHAOS_SCENARIOS)
        assert unit_external_effects_guard == []

    def test_chaos_scenarios_defined(self):
        from engine.chaos_scenarios import CHAOS_SCENARIOS
        assert len(CHAOS_SCENARIOS) >= 7

    def test_each_scenario_has_required_fields(self):
        from engine.chaos_scenarios import CHAOS_SCENARIOS
        for s in CHAOS_SCENARIOS:
            assert hasattr(s, "name")
            assert hasattr(s, "deploy_commands")
            assert hasattr(s, "expected_failure_class")
            assert hasattr(s, "fix_commands")
            assert hasattr(s, "cleanup_commands")
            assert hasattr(s, "rubric_stage")

    def test_collect_real_evidence_function(self):
        from engine.chaos_scenarios import collect_real_evidence
        assert callable(collect_real_evidence)

    def test_chaos_result_has_lifecycle_steps(self, client):
        resp = client.post("/admin/run-chaos-test")
        data = resp.json()
        assert data["results"]
        result = data["results"][0]
        assert "steps" in result
        steps = result["steps"]
        for expected_step in ["deploy", "evaluate_before", "evaluate_after"]:
            assert expected_step in steps, f"Missing step: {expected_step}"

    def test_receipt_generated(self, client):
        resp = client.post("/admin/run-chaos-test")
        data = resp.json()
        receipt = data.get("receipt", {})
        assert receipt.get("type") == "chaos-test-remediation"
        assert receipt.get("phase") == "D"
        assert "scenarios" in receipt

    def test_mixed_results_are_counted_and_persisted(self, client, chaos_runner):
        from engine.chaos_scenarios import CHAOS_SCENARIOS

        def mixed_result(scenario, kubeconfig, db=None):
            return {"scenario": scenario.name, "passed": scenario is not CHAOS_SCENARIOS[0],
                    "evidence_source": "synthetic-unit-test", "steps": {}}

        chaos_runner.side_effect = mixed_result
        response = client.post("/admin/run-chaos-test")
        assert response.status_code == 200
        receipt = response.json()["receipt"]
        assert receipt["scenarios"] == len(CHAOS_SCENARIOS)
        assert receipt["failed"] == 1
        assert receipt["passed"] == len(CHAOS_SCENARIOS) - 1
        saved = client.get("/admin/receipts?receipt_type=chaos-test-remediation")
        assert saved.status_code == 200
        assert saved.json()["receipts"]
