"""RED/GREEN TDD — Phase 3: BYOP — Configurable substrate router thresholds."""

import sys
from pathlib import Path

import pytest


class TestSubstrateConfig:
    """Substrate router thresholds and hardware types must be YAML-configurable."""

    def test_config_yaml_exists(self):
        config = Path(__file__).parent.parent / "policies" / "substrate.yaml"
        assert config.exists(), f"Missing {config}"

    def test_config_loads_with_pydantic(self):
        from engine.substrate_config import load_substrate_config
        config = load_substrate_config()
        assert config is not None
        assert hasattr(config, "thresholds")
        assert hasattr(config, "hardware_types")

    def test_default_thresholds_match_current(self):
        """Default YAML thresholds must match the values previously hardcoded."""
        from engine.substrate_config import load_substrate_config
        config = load_substrate_config()
        assert config.thresholds.gaudi_saturated == 90
        assert config.thresholds.xeon6_underutil == 20
        assert config.thresholds.gaudi_busy == 70
        assert config.thresholds.memory_pressure == 80

    def test_default_hardware_types(self):
        from engine.substrate_config import load_substrate_config
        config = load_substrate_config()
        assert config.hardware_types.inference == "gaudi"
        assert config.hardware_types.compute == "xeon6"

    def test_custom_thresholds_change_routing(self, tmp_path):
        """Lowering gaudi_saturated threshold should trigger fallback sooner."""
        import yaml
        from engine.substrate_config import load_substrate_config, SubstrateConfig
        from engine.substrate_router import route_workload

        custom_yaml = tmp_path / "substrate.yaml"
        custom_yaml.write_text(yaml.dump({
            "version": "1.0",
            "thresholds": {
                "gaudi_saturated": 50,
                "xeon6_underutil": 20,
                "gaudi_busy": 70,
                "memory_pressure": 80,
            },
            "hardware_types": {"inference": "gaudi", "compute": "xeon6"},
        }))
        config = load_substrate_config(path=custom_yaml)

        state = {
            "nodes": {"avg_cpu": 60, "avg_mem": 50, "gaudi_count": 4, "xeon6_count": 4,
                       "hot_nodes": 4, "failed_nodes": 0, "total_nodes": 8},
            "pods": {"crashloops": 0, "sandbox_failing": 0},
            "gaudi_utilization": 60.0,
            "xeon6_utilization": 30.0,
        }
        decision = route_workload(state, config=config)
        assert decision.routing == "xeon6_fallback", (
            f"gaudi_util=60 with threshold=50 should trigger fallback, got {decision.routing}"
        )

    def test_default_config_produces_identical_routing(self):
        """All 7 emulator scenarios must produce the same routing with default YAML config."""
        emu_path = Path(__file__).parent.parent.parent / "stargate-synthetic-client-emulator"
        if not emu_path.exists():
            pytest.skip("Emulator not found")
        if str(emu_path) not in sys.path:
            sys.path.insert(0, str(emu_path))

        from emulator.scenarios import get_all_scenarios
        from engine.substrate_router import route_workload
        from engine.substrate_config import load_substrate_config

        config = load_substrate_config()
        scenarios = get_all_scenarios()

        for name, scenario in scenarios.items():
            state = scenario.generate_state()
            cluster_state = {
                "nodes": state.get("nodes", {}),
                "pods": state.get("pods", {}),
            }
            decision_with_config = route_workload(cluster_state, config=config)
            decision_without_config = route_workload(cluster_state)
            assert decision_with_config.routing == decision_without_config.routing, (
                f"Scenario {name}: config routing={decision_with_config.routing} "
                f"differs from default routing={decision_without_config.routing}"
            )

    def test_custom_hardware_names_in_decision(self, tmp_path):
        """Custom hardware type names should appear in routing decisions."""
        import yaml
        from engine.substrate_config import load_substrate_config
        from engine.substrate_router import route_workload

        custom_yaml = tmp_path / "substrate.yaml"
        custom_yaml.write_text(yaml.dump({
            "version": "1.0",
            "thresholds": {
                "gaudi_saturated": 90,
                "xeon6_underutil": 20,
                "gaudi_busy": 70,
                "memory_pressure": 80,
            },
            "hardware_types": {"inference": "h100", "compute": "epyc"},
        }))
        config = load_substrate_config(path=custom_yaml)

        state = {
            "nodes": {"avg_cpu": 30, "avg_mem": 50, "gaudi_count": 4, "xeon6_count": 4,
                       "hot_nodes": 0, "failed_nodes": 0, "total_nodes": 8},
            "pods": {"crashloops": 0, "sandbox_failing": 0},
        }
        decision = route_workload(state, config=config)
        assert "h100" in decision.inference_target or "epyc" in decision.compute_target, (
            f"Expected custom hardware names, got inference={decision.inference_target}, compute={decision.compute_target}"
        )
