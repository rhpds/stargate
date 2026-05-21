"""RED/GREEN TDD — Phase 4: BYOP — Policy rules in YAML."""

import sys
from pathlib import Path

import pytest
import yaml


class TestPolicyRulesSchema:
    """Policy rules YAML must exist and validate against the schema."""

    def test_rules_yaml_exists(self):
        rules = Path(__file__).parent.parent / "policies" / "rules.yaml"
        assert rules.exists(), f"Missing {rules}"

    def test_rules_yaml_validates_pydantic(self):
        from engine.policy_loader import load_policy_rules
        ruleset = load_policy_rules()
        assert ruleset is not None
        assert hasattr(ruleset, "rules")
        assert hasattr(ruleset, "constraint_to_stage")

    def test_all_six_rule_ids_present(self):
        from engine.policy_loader import load_policy_rules
        ruleset = load_policy_rules()
        ids = {r.id for r in ruleset.rules}
        expected = {
            "provision_blocked_lab",
            "cleanup_stuck",
            "pool_exhaustion",
            "cluster_capacity",
            "smoke_test_failing",
            "substrate_routing",
        }
        assert expected.issubset(ids), f"Missing rule IDs: {expected - ids}"

    @pytest.mark.parametrize("field_name", ["id", "scope", "condition", "evidence_sources"])
    def test_each_rule_has_required_fields(self, field_name):
        from engine.policy_loader import load_policy_rules
        ruleset = load_policy_rules()
        for rule in ruleset.rules:
            val = getattr(rule, field_name)
            assert val is not None and val != "", (
                f"Rule {rule.id} missing required field {field_name}"
            )

    def test_constraint_to_stage_mapping_present(self):
        from engine.policy_loader import load_policy_rules
        ruleset = load_policy_rules()
        expected = {
            "workload_not_deployed": "deployment-ready",
            "operator_version_drift": "deployment-ready",
            "showroom_wrong_content": "showroom-healthy",
            "resource_below_spec": "vm-runtime-ready",
            "showroom_wrong_ref": "showroom-healthy",
        }
        assert ruleset.constraint_to_stage == expected


class TestPolicyRuleLoader:
    """The loader must handle valid/invalid YAML and custom paths."""

    def test_load_function_exists(self):
        from engine.policy_loader import load_policy_rules
        assert callable(load_policy_rules)

    def test_load_returns_ruleset(self):
        from engine.policy_loader import load_policy_rules
        from engine.policy_models import PolicyRuleSet
        ruleset = load_policy_rules()
        assert isinstance(ruleset, PolicyRuleSet)

    def test_custom_path_loads(self, tmp_path):
        from engine.policy_loader import load_policy_rules
        custom = tmp_path / "rules.yaml"
        custom.write_text(yaml.dump({
            "version": "1.0",
            "constraint_to_stage": {},
            "rules": [{
                "id": "test_rule",
                "scope": "lab",
                "condition": "x > 0",
                "evidence_sources": ["test"],
            }],
        }))
        ruleset = load_policy_rules(path=custom)
        assert len(ruleset.rules) == 1
        assert ruleset.rules[0].id == "test_rule"

    def test_invalid_yaml_raises(self, tmp_path):
        from engine.policy_loader import load_policy_rules, PolicyLoadError
        bad = tmp_path / "rules.yaml"
        bad.write_text("{{{{invalid yaml")
        with pytest.raises(PolicyLoadError):
            load_policy_rules(path=bad)

    def test_missing_file_raises(self, tmp_path):
        from engine.policy_loader import load_policy_rules, PolicyLoadError
        with pytest.raises(PolicyLoadError):
            load_policy_rules(path=tmp_path / "nonexistent.yaml")


class TestPolicyBackwardCompatibility:
    """Policy engine output must be identical after YAML extraction."""

    def test_generate_recommendations_api_unchanged(self):
        """Function signature and return schema unchanged."""
        from engine.policy import generate_recommendations
        import inspect
        sig = inspect.signature(generate_recommendations)
        params = list(sig.parameters.keys())
        assert "labs" in params
        assert "pools" in params
        assert "cluster_states" in params
        assert "sessions" in params

    def test_constraint_to_stage_accessible(self):
        """CONSTRAINT_TO_STAGE is still importable from engine.policy."""
        from engine.policy import CONSTRAINT_TO_STAGE
        assert isinstance(CONSTRAINT_TO_STAGE, dict)
        assert "workload_not_deployed" in CONSTRAINT_TO_STAGE

    def test_yaml_thresholds_produce_identical_output(self):
        """Same inputs → same recommendations with YAML-driven thresholds."""
        from engine.policy import generate_recommendations

        labs = [{
            "lab_code": "LB1088",
            "title": "Test Lab",
            "sessions": 3,
            "instances_started": 0,
            "instances_failed": 0,
            "instances_total": 0,
            "instances_destroying": 0,
            "provisioned": 0,
            "capacity": 0,
            "ci_name": "summit-2026.lb1088-test",
            "cloud": "CNV",
            "total_attendees": 30,
            "summit_days": ["Day 1"],
        }]
        pools = {"summit_pools": [], "exhausted_pools": [], "provisioning": {}}
        cluster_states = [{"cluster": "ocpv05", "avg_cpu": 75, "vms_per_node": 50}]
        sessions = [{"lab_code": "LB1088", "session_date": "2026-06-01", "room": "A", "attendees": 10}]

        result = generate_recommendations(labs, pools, cluster_states, sessions)
        assert "recommendations" in result
        assert result["total"] >= 1

        types = [r["type"] for r in result["recommendations"]]
        assert "provision_blocked_lab" in types
        assert "cluster_capacity" in types

        for rec in result["recommendations"]:
            if rec["type"] == "provision_blocked_lab":
                assert rec["confidence_score"] == 0.95
                assert rec["urgency"] == "critical"
            if rec["type"] == "cluster_capacity":
                assert rec["confidence_score"] == 0.70
                assert rec["urgency"] == "medium"

    def test_all_scenarios_produce_recommendations(self):
        """Emulator scenarios still produce recommendations through YAML-driven policy."""
        emu_path = Path(__file__).parent.parent.parent / "stargate-synthetic-client-emulator"
        if not emu_path.exists():
            pytest.skip("Emulator not found")
        if str(emu_path) not in sys.path:
            sys.path.insert(0, str(emu_path))

        from emulator.scenarios import get_all_scenarios
        from engine.policy import generate_recommendations
        from engine.action_simulator import build_policy_inputs

        scenarios = get_all_scenarios()
        for name, scenario in scenarios.items():
            state = scenario.generate_state()
            labs, pools, cluster_states, sessions = build_policy_inputs(name, state)
            result = generate_recommendations(labs, pools, cluster_states, sessions)
            assert "recommendations" in result, f"Scenario {name} failed"
            assert "total" in result

    def test_rule_get_confidence_and_urgency(self):
        """Rules provide confidence and urgency via helper methods."""
        from engine.policy_loader import load_policy_rules
        ruleset = load_policy_rules()
        rules_by_id = {r.id: r for r in ruleset.rules}

        cap = rules_by_id["cluster_capacity"]
        assert cap.get_confidence(avg_cpu=85) == 0.85
        assert cap.get_confidence(avg_cpu=75) == 0.70
        assert cap.get_urgency(avg_cpu=85) == "high"
        assert cap.get_urgency(avg_cpu=75) == "medium"

        blocked = rules_by_id["provision_blocked_lab"]
        assert blocked.get_confidence() == 0.95
        assert blocked.get_urgency() == "critical"
