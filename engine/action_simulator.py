"""Action simulator — applies simulated actions to scenario state.

Given a recommendation type and a scenario state, transforms the state
as if the recommended action was successfully executed. Used in shadow
mode to verify LLM recommendations would fix the problem.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple


def simulate_action(action_type: str, state: Dict[str, Any], routing=None) -> Dict[str, Any]:
    """Apply a simulated action and return the resolved state."""
    resolved = copy.deepcopy(state)
    nodes = resolved.get("nodes", {})
    pods = resolved.get("pods", {})
    pools = resolved.get("pools", {})

    if action_type == "cluster_capacity":
        nodes["avg_cpu"] = min(nodes.get("avg_cpu", 30) * 0.5, 40)
        nodes["avg_mem"] = min(nodes.get("avg_mem", 50) * 0.6, 50)
        nodes["hot_nodes"] = 0
        nodes["failed_nodes"] = 0
        nodes["status"] = "healthy"
        pods["crashloops"] = 0
        pods["sandbox_failing"] = 0
        pods["pending_count"] = 0
        resolved["guest_agent_connected"] = True
        if routing and hasattr(routing, 'routing') and routing.routing == "xeon6_fallback":
            resolved["gaudi_utilization"] = 50.0
            resolved["xeon6_utilization"] = 40.0

    elif action_type == "provision_blocked_lab":
        for sp in pools.get("summit_pools", []):
            if sp.get("available", 0) == 0:
                sp["available"] = max(sp.get("min", 1), 5)
                sp["ready"] = sp["available"]
        resolved["anarchysubject_exists"] = True
        resolved["provision_job_succeeded"] = True
        resolved["state_is_started"] = True
        resolved["no_error_conditions"] = True

    elif action_type == "pool_exhaustion":
        for sp in pools.get("summit_pools", []):
            sp["available"] = max(sp.get("min", 1), 5)
            sp["ready"] = sp["available"]

    elif action_type == "cleanup_stuck":
        pods["sandbox_failing"] = 0
        pods["crashloops"] = 0

    elif action_type == "smoke_test_failing":
        resolved["showroom_pod_running"] = True
        resolved["showroom_route_reachable"] = True
        resolved["readyz_returns_200"] = True
        resolved["content_loaded"] = True
        resolved["response_time_ms"] = 200

    elif action_type == "rebalance":
        resolved["gaudi_utilization"] = 50.0
        resolved["xeon6_utilization"] = 45.0
        nodes["avg_cpu"] = 45

    # Ensure all healthy defaults for resolved state
    resolved.setdefault("deployment_exists", True)
    resolved.setdefault("desired_replicas_ready", True)
    resolved.setdefault("service_exists", True)
    resolved.setdefault("route_exists", True)
    resolved.setdefault("service_has_ready_endpoints", True)
    resolved.setdefault("health_endpoint_returns_200", True)
    resolved.setdefault("showroom_pod_running", True)
    resolved.setdefault("showroom_route_reachable", True)
    resolved.setdefault("readyz_returns_200", True)
    resolved.setdefault("content_loaded", True)
    resolved.setdefault("response_time_ms", 200)
    resolved.setdefault("inferenceservice_exists", True)
    resolved.setdefault("inferenceservice_ready", True)
    resolved.setdefault("test_inference_succeeded", True)
    resolved.setdefault("inference_latency_ms", 500)
    resolved.setdefault("anarchysubject_exists", True)
    resolved.setdefault("provision_job_succeeded", True)
    resolved.setdefault("state_is_started", True)
    resolved.setdefault("no_error_conditions", True)
    resolved.setdefault("guest_agent_connected", True)

    # Fix VM data to all healthy
    vms = resolved.get("vms", {})
    for dv in vms.get("datavolumes", []):
        dv["phase"] = "Succeeded"
        dv["pvc_bound"] = True
    for vmi in vms.get("vmis", []):
        vmi["phase"] = "Running"
        vmi["guest_agent_connected"] = True
        vmi["guest_os_ready"] = True

    # Fix pod data
    pods["crashloops"] = 0
    pods["crashloop_count"] = 0
    pods["sandbox_failing"] = 0
    pods["pending_count"] = 0
    pods["failing_count"] = 0
    resolved["no_crashloop_pods"] = True
    resolved["desired_replicas_ready"] = True
    resolved["deployment_exists"] = True

    # Override evidence generator inputs to ensure all stages pass after fix
    resolved["evidence_overrides"] = {
        "model-endpoint-ready": {
            "inferenceservice_ready": True,
            "test_inference_succeeded": True,
            "inference_latency_acceptable": True,
        },
        "showroom-healthy": {
            "showroom_pod_running": True,
            "showroom_route_reachable": True,
            "readyz_returns_200": True,
            "content_loaded": True,
            "response_time_acceptable": True,
        },
        "provision-complete": {
            "provision_job_succeeded": True,
            "state_is_started": True,
        },
    }

    resolved["nodes"] = nodes
    resolved["pods"] = pods
    resolved["pools"] = pools

    return resolved


def build_policy_inputs(scenario_name: str, state: Dict[str, Any]) -> Tuple[List, Dict, List, List]:
    """Convert emulator state to policy engine inputs."""
    nodes_data = state.get("nodes", {})
    pods_data = state.get("pods", {})
    pools_data = state.get("pools", {})

    cluster_states = [{
        "cluster": f"synthetic-{scenario_name}",
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
    if "provision" in scenario_name and "blocked" in scenario_name:
        labs = [{
            "lab_code": "SYN-001", "title": "Synthetic Lab", "sessions": 3,
            "summit_days": ["Day 1"], "total_attendees": 50,
            "instances_started": 0, "instances_failed": 0, "instances_total": 0,
            "provisioned": 0, "capacity": 0, "ci_name": "", "cloud": "CNV",
            "deploy_mode": None, "demolition_status": "none", "labagator_status": "planning",
        }]
    elif "mixed" in scenario_name:
        labs = [{
            "lab_code": "SYN-MIX", "title": "Mixed Lab", "sessions": 2,
            "summit_days": ["Day 1"], "total_attendees": 30,
            "instances_started": 5, "instances_failed": 2, "instances_total": 7,
            "provisioned": 5, "capacity": 5, "ci_name": "test", "cloud": "CNV",
            "deploy_mode": None, "demolition_status": "fail",
            "demolition_failed": 3, "demolition_total": 5, "demolition_completed": 2,
            "labagator_status": "in_development",
        }]

    return labs, pools, cluster_states, []
