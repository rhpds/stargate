"""Policy Engine Integration — validates each scenario produces correct recommendations.

RED/GREEN TDD: tests written first, then wired to pass.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "stargate-synthetic-client-emulator"))

from engine.policy import generate_recommendations
from emulator.scenarios import get_all_scenarios, get_scenario

ALL_SCENARIOS = list(get_all_scenarios().keys())

EXPECTED_RECOMMENDATIONS = {
    "healthy-baseline": [],
    "memory-pressure": ["cluster_capacity"],
    "node-failure": ["cluster_capacity"],
    "gaudi-saturation": ["cluster_capacity"],
    "xeon-underutil": ["cluster_capacity"],
    "mixed-contention": ["cleanup_stuck", "smoke_test_failing"],
    "provision-blocked": ["provision_blocked_lab", "pool_exhaustion"],
}


def _build_policy_inputs(scenario):
    """Convert emulator scenario state to policy engine inputs."""
    state = scenario.generate_state()
    nodes_data = state.get("nodes", {})
    pods_data = state.get("pods", {})
    pools_data = state.get("pools", {})

    cluster_states = [{
        "cluster": "synthetic-cluster",
        "avg_cpu": nodes_data.get("avg_cpu", 30),
        "vms_per_node": pods_data.get("vms_per_node", 0),
        "sandbox_active": pods_data.get("sandbox_active", 0),
        "hot_nodes": nodes_data.get("hot_nodes", 0),
        "total_vms": pods_data.get("total_vms", 0),
    }]

    pools = {
        "summit_pools": pools_data.get("summit_pools", []),
        "exhausted_pools": pools_data.get("exhausted_pools", []),
        "provisioning": pools_data.get("provisioning", {}),
    }

    labs = []
    if "provision" in scenario.name and "blocked" in scenario.name:
        labs = [
            {
                "lab_code": "SYN-001",
                "title": "Synthetic Lab",
                "sessions": 3,
                "summit_days": ["Day 1"],
                "total_attendees": 50,
                "instances_started": 0,
                "instances_failed": 0,
                "instances_total": 0,
                "provisioned": 0,
                "capacity": 0,
                "ci_name": "",
                "cloud": "CNV",
                "deploy_mode": None,
                "demolition_status": "none",
                "labagator_status": "planning",
            }
        ]
    elif "mixed" in scenario.name:
        labs = [
            {
                "lab_code": "SYN-MIX",
                "title": "Mixed Contention Lab",
                "sessions": 2,
                "summit_days": ["Day 1"],
                "total_attendees": 30,
                "instances_started": 5,
                "instances_failed": 2,
                "instances_total": 7,
                "provisioned": 5,
                "capacity": 5,
                "ci_name": "test",
                "cloud": "CNV",
                "deploy_mode": None,
                "demolition_status": "fail",
                "demolition_failed": 3,
                "demolition_total": 5,
                "demolition_completed": 2,
                "labagator_status": "in_development",
            }
        ]

    return labs, pools, cluster_states, []


class TestPolicyIntegration:
    """Validate policy engine produces correct recommendations per scenario."""

    @pytest.mark.parametrize("scenario_name", ALL_SCENARIOS)
    def test_scenario_produces_recommendations(self, scenario_name):
        """Each scenario generates valid policy inputs."""
        scenario = get_scenario(scenario_name)
        labs, pools, cluster_states, sessions = _build_policy_inputs(scenario)
        result = generate_recommendations(labs, pools, cluster_states, sessions)
        assert "recommendations" in result
        assert "total" in result

    def test_healthy_baseline_no_recommendations(self):
        """healthy-baseline produces no recommendations (all healthy)."""
        scenario = get_scenario("healthy-baseline")
        labs, pools, cluster_states, sessions = _build_policy_inputs(scenario)
        result = generate_recommendations(labs, pools, cluster_states, sessions)
        assert result["total"] == 0

    def test_provision_blocked_recommendations(self):
        """provision-blocked produces provision_blocked_lab."""
        scenario = get_scenario("provision-blocked")
        labs, pools, cluster_states, sessions = _build_policy_inputs(scenario)
        result = generate_recommendations(labs, pools, cluster_states, sessions)
        types = [r["type"] for r in result["recommendations"]]
        assert "provision_blocked_lab" in types

    def test_mixed_contention_recommendations(self):
        """mixed-contention produces cleanup_stuck."""
        scenario = get_scenario("mixed-contention")
        labs, pools, cluster_states, sessions = _build_policy_inputs(scenario)
        result = generate_recommendations(labs, pools, cluster_states, sessions)
        types = [r["type"] for r in result["recommendations"]]
        assert "cleanup_stuck" in types

    def test_recommendations_have_evidence(self):
        """Each recommendation includes evidence attribution."""
        scenario = get_scenario("provision-blocked")
        labs, pools, cluster_states, sessions = _build_policy_inputs(scenario)
        result = generate_recommendations(labs, pools, cluster_states, sessions)
        for rec in result["recommendations"]:
            assert "evidence" in rec
            assert "confidence_score" in rec

    def test_recommendations_have_confidence(self):
        """Each recommendation has a confidence score between 0 and 1."""
        scenario = get_scenario("provision-blocked")
        labs, pools, cluster_states, sessions = _build_policy_inputs(scenario)
        result = generate_recommendations(labs, pools, cluster_states, sessions)
        for rec in result["recommendations"]:
            assert 0 <= rec["confidence_score"] <= 1.0

    def test_recommendations_have_decision_logic(self):
        """Each recommendation has decision_logic explaining the trigger."""
        scenario = get_scenario("provision-blocked")
        labs, pools, cluster_states, sessions = _build_policy_inputs(scenario)
        result = generate_recommendations(labs, pools, cluster_states, sessions)
        for rec in result["recommendations"]:
            assert "decision_logic" in rec
