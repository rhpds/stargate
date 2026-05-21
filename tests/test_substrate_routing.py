"""Substrate Routing Tests — Gaudi vs Xeon6 workload routing decisions.

RED/GREEN TDD: tests written FIRST. engine/substrate_router.py doesn't exist yet.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "stargate-synthetic-client-emulator"))

from engine.substrate_router import route_workload, SubstrateDecision
from emulator.scenarios import get_scenario


ROUTING_MATRIX = [
    ("healthy-baseline", "gaudi_preferred"),
    ("gaudi-saturation", "xeon6_fallback"),
    ("xeon-underutil", "rebalance_to_xeon6"),
    ("memory-pressure", "gaudi_preferred"),
    ("node-failure", "xeon6_fallback"),
    ("mixed-contention", "isolate"),
    ("provision-blocked", "no_change"),
]


class TestSubstrateRouting:
    @pytest.mark.parametrize("scenario_name,expected_decision", ROUTING_MATRIX,
                             ids=[s for s, _ in ROUTING_MATRIX])
    def test_routing_decision(self, scenario_name, expected_decision):
        """Each scenario produces correct Gaudi/Xeon6 routing decision."""
        scenario = get_scenario(scenario_name)
        state = scenario.generate_state()
        decision = route_workload(state)
        assert isinstance(decision, SubstrateDecision)
        assert decision.routing == expected_decision, (
            f"Scenario {scenario_name}: expected {expected_decision}, got {decision.routing}. "
            f"Gaudi={decision.gaudi_util}%, Xeon6={decision.xeon6_util}%"
        )

    def test_gaudi_saturation_routes_inference_to_xeon(self):
        """When Gaudi >90%, inference workloads route to Xeon6."""
        state = get_scenario("gaudi-saturation").generate_state()
        decision = route_workload(state)
        assert decision.inference_target == "xeon6"
        assert decision.gaudi_util > 90

    def test_xeon_underutil_rebalances_compute(self):
        """When Xeon6 <20% and Gaudi >70%, recommend compute migration."""
        state = get_scenario("xeon-underutil").generate_state()
        decision = route_workload(state)
        assert decision.compute_target == "xeon6"
        assert decision.xeon6_util < 20

    def test_healthy_routes_inference_to_gaudi(self):
        """When both healthy, inference prefers Gaudi."""
        state = get_scenario("healthy-baseline").generate_state()
        decision = route_workload(state)
        assert decision.inference_target == "gaudi"

    def test_node_failure_avoids_failed_substrate(self):
        """When Gaudi node fails, route away from it."""
        state = get_scenario("node-failure").generate_state()
        decision = route_workload(state)
        assert decision.routing in ("xeon6_fallback", "gaudi_preferred")

    def test_decision_has_reason(self):
        """Every routing decision includes a human-readable reason."""
        for name in ["healthy-baseline", "gaudi-saturation", "xeon-underutil"]:
            state = get_scenario(name).generate_state()
            decision = route_workload(state)
            assert decision.reason, f"No reason for {name}"
            assert len(decision.reason) > 10

    def test_decision_has_utilization_data(self):
        """Every decision records Gaudi and Xeon6 utilization."""
        state = get_scenario("gaudi-saturation").generate_state()
        decision = route_workload(state)
        assert decision.gaudi_util is not None
        assert decision.xeon6_util is not None

    def test_decision_serializable(self):
        """Decision can be serialized to dict for receipts."""
        state = get_scenario("healthy-baseline").generate_state()
        decision = route_workload(state)
        d = decision.to_dict()
        assert "routing" in d
        assert "inference_target" in d
        assert "compute_target" in d
        assert "reason" in d
