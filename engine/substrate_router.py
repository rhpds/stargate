"""Substrate router — decides workload placement across configurable hardware types.

Given cluster state (node utilization, node types, failures),
determines optimal routing for inference and compute workloads.
Thresholds and hardware type names are loaded from policies/substrate.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from engine.substrate_config import SubstrateConfig, load_substrate_config


@dataclass
class SubstrateDecision:
    routing: str
    inference_target: str
    compute_target: str
    gaudi_util: Optional[float] = None
    xeon6_util: Optional[float] = None
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "routing": self.routing,
            "inference_target": self.inference_target,
            "compute_target": self.compute_target,
            "gaudi_util": self.gaudi_util,
            "xeon6_util": self.xeon6_util,
            "reason": self.reason,
        }


def route_workload(state: Dict[str, Any], config: Optional[SubstrateConfig] = None) -> SubstrateDecision:
    """Determine workload routing based on cluster state and configurable thresholds."""
    if config is None:
        config = load_substrate_config()

    t = config.thresholds
    hw = config.hardware_types

    nodes_data = state.get("nodes", {})
    pods_data = state.get("pods", {})

    gaudi_count = nodes_data.get("gaudi_count", nodes_data.get("gaudi_nodes", 0))
    xeon6_count = nodes_data.get("xeon6_count", nodes_data.get("xeon6_nodes", 0))
    avg_cpu = nodes_data.get("avg_cpu", 30)
    avg_mem = nodes_data.get("avg_mem", 50)
    failed_nodes = nodes_data.get("failed_nodes", 0)
    hot_nodes = nodes_data.get("hot_nodes", 0)

    gaudi_util = state.get("gaudi_utilization") or _estimate_gaudi_util(nodes_data, gaudi_count)
    xeon6_util = state.get("xeon6_utilization") or _estimate_xeon6_util(nodes_data, xeon6_count)

    crashloops = pods_data.get("crashloops", 0)
    failing = pods_data.get("sandbox_failing", 0)

    provision_blocked = state.get("state_is_started") is False or state.get("anarchysubject_exists") is False
    if provision_blocked and not nodes_data.get("failed_nodes", 0):
        return SubstrateDecision(
            routing="no_change",
            inference_target=hw.inference if gaudi_count > 0 else hw.compute,
            compute_target=hw.compute,
            gaudi_util=gaudi_util,
            xeon6_util=xeon6_util,
            reason="Provisioning issue — no substrate routing change needed",
        )

    if gaudi_util > t.gaudi_saturated:
        return SubstrateDecision(
            routing="xeon6_fallback",
            inference_target=hw.compute,
            compute_target=hw.compute,
            gaudi_util=gaudi_util,
            xeon6_util=xeon6_util,
            reason=f"{hw.inference.capitalize()} saturated at {gaudi_util:.0f}%, routing inference to {hw.compute} fallback",
        )

    if failed_nodes > 0:
        return SubstrateDecision(
            routing="xeon6_fallback",
            inference_target=hw.compute,
            compute_target=hw.compute,
            gaudi_util=gaudi_util,
            xeon6_util=xeon6_util,
            reason=f"{failed_nodes} node(s) failed, routing to healthy {hw.compute} substrate",
        )

    if crashloops > 0 and failing > 0:
        return SubstrateDecision(
            routing="isolate",
            inference_target=hw.inference,
            compute_target=hw.compute,
            gaudi_util=gaudi_util,
            xeon6_util=xeon6_util,
            reason=f"Workload contention detected — isolating inference ({hw.inference}) from compute ({hw.compute})",
        )

    if xeon6_util < t.xeon6_underutil and gaudi_util > t.gaudi_busy:
        return SubstrateDecision(
            routing="rebalance_to_xeon6",
            inference_target=hw.inference,
            compute_target=hw.compute,
            gaudi_util=gaudi_util,
            xeon6_util=xeon6_util,
            reason=f"{hw.compute.capitalize()} underutilized ({xeon6_util:.0f}%) while {hw.inference} at {gaudi_util:.0f}% — rebalance compute to {hw.compute}",
        )

    if avg_mem > t.memory_pressure:
        return SubstrateDecision(
            routing="gaudi_preferred",
            inference_target=hw.inference,
            compute_target=hw.inference,
            gaudi_util=gaudi_util,
            xeon6_util=xeon6_util,
            reason=f"Memory pressure on compute nodes ({avg_mem:.0f}%), preferring {hw.inference} for new workloads",
        )

    return SubstrateDecision(
        routing="gaudi_preferred",
        inference_target=hw.inference,
        compute_target=hw.compute,
        gaudi_util=gaudi_util,
        xeon6_util=xeon6_util,
        reason=f"Normal operation — inference on {hw.inference}, compute on {hw.compute}",
    )


def _estimate_gaudi_util(nodes_data: Dict, gaudi_count: int) -> float:
    if gaudi_count == 0:
        return 0.0
    avg_cpu = nodes_data.get("avg_cpu", 30)
    hot = nodes_data.get("hot_nodes", 0)
    if hot >= gaudi_count:
        return 95.0
    return min(avg_cpu * 1.2, 100.0)


def _estimate_xeon6_util(nodes_data: Dict, xeon6_count: int) -> float:
    if xeon6_count == 0:
        return 0.0
    avg_cpu = nodes_data.get("avg_cpu", 30)
    hot = nodes_data.get("hot_nodes", 0)
    if xeon6_count > 0 and hot == 0:
        return max(avg_cpu * 0.8, 5.0)
    return avg_cpu
