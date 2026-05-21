"""Data contract definitions for dashboard API responses.

Each contract specifies: source system, required fields, types, staleness limits.
Used by api/contracts.py for runtime validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class FieldContract:
    name: str
    source: str
    required: bool = False
    type: str = "any"
    stale_after_seconds: Optional[int] = None
    path: str = ""


@dataclass
class CrossCheck:
    description: str
    check_fn: str


@dataclass
class ResponseContract:
    endpoint: str
    fields: List[FieldContract] = field(default_factory=list)
    cross_checks: List[CrossCheck] = field(default_factory=list)
    list_field: str = ""


CONTRACTS = {
    "/dashboard/labs": ResponseContract(
        endpoint="/dashboard/labs",
        list_field="labs",
        fields=[
            FieldContract("lab_code", "labagator", required=True, type="string"),
            FieldContract("title", "labagator", required=True, type="string"),
            FieldContract("labagator_status", "labagator", required=True, type="string"),
            FieldContract("cloud", "labagator", required=False, type="string"),
            FieldContract("sessions", "labagator", required=True, type="int"),
            FieldContract("demolition_status", "demolition", required=False, type="string"),
            FieldContract("demolition_total", "demolition", required=False, type="int"),
            FieldContract("instances_total", "babylon", required=False, type="int"),
            FieldContract("instances_started", "babylon", required=False, type="int"),
            FieldContract("instances_failed", "babylon", required=False, type="int"),
            FieldContract("provisioned", "poolboy", required=False, type="int"),
            FieldContract("capacity", "poolboy", required=False, type="int"),
            FieldContract("last_scanned", "stargate_db", required=False, stale_after_seconds=900),
            FieldContract("schedule_status", "computed", required=False, type="string"),
            FieldContract("next_action", "computed", required=False, type="dict"),
        ],
    ),
    "/dashboard/overview": ResponseContract(
        endpoint="/dashboard/overview",
        fields=[
            FieldContract("labs", "labagator", required=True, type="dict", path="labs.total"),
            FieldContract("clusters", "scanner", required=True, type="dict", path="clusters.total"),
            FieldContract("pools", "babylon", required=False, type="dict"),
        ],
    ),
    "/dashboard/pipeline": ResponseContract(
        endpoint="/dashboard/pipeline",
        list_field="stages",
        fields=[
            FieldContract("stage_id", "stargate_db", required=True, type="string"),
            FieldContract("pass", "stargate_db", required=True, type="int"),
            FieldContract("fail", "stargate_db", required=True, type="int"),
            FieldContract("warn", "stargate_db", required=True, type="int"),
            FieldContract("total", "stargate_db", required=True, type="int"),
            FieldContract("health_rate", "stargate_db", required=False, type="float"),
        ],
        cross_checks=[
            CrossCheck("pass + warn + fail == total", "stage_totals"),
        ],
    ),
    "/dashboard/clusters": ResponseContract(
        endpoint="/dashboard/clusters",
        list_field="clusters",
        fields=[
            FieldContract("cluster", "scanner", required=True, type="string"),
            FieldContract("health_rate", "stargate_db", required=False, type="float"),
        ],
    ),
    "/dashboard/pools": ResponseContract(
        endpoint="/dashboard/pools",
        list_field="summit_pools",
        fields=[
            FieldContract("name", "babylon", required=True, type="string"),
            FieldContract("available", "babylon", required=True, type="int"),
            FieldContract("ready", "babylon", required=False, type="int"),
            FieldContract("min", "babylon", required=False, type="int"),
            FieldContract("status", "computed", required=True, type="string"),
        ],
    ),
    "/dashboard/provisioning-recommendations": ResponseContract(
        endpoint="/dashboard/provisioning-recommendations",
        list_field="recommendations",
        fields=[
            FieldContract("type", "policy_engine", required=True, type="string"),
            FieldContract("urgency", "policy_engine", required=True, type="string"),
            FieldContract("recommendation", "policy_engine", required=True, type="string"),
            FieldContract("confidence_score", "policy_engine", required=False, type="float"),
            FieldContract("evidence", "multi_source", required=False, type="dict"),
        ],
    ),
    "/dashboard/security": ResponseContract(
        endpoint="/dashboard/security",
        fields=[
            FieldContract("known_cves", "hardcoded", required=True, type="list"),
            FieldContract("clusters", "scanner", required=False, type="list"),
        ],
    ),
    "/dashboard/forecast": ResponseContract(
        endpoint="/dashboard/forecast",
        fields=[
            FieldContract("hourly", "computed", required=True, type="list"),
            FieldContract("summary", "computed", required=True, type="dict"),
            FieldContract("cluster_projections", "scanner", required=False, type="list"),
        ],
    ),
    "/dashboard/aap": ResponseContract(
        endpoint="/dashboard/aap",
        fields=[
            FieldContract("summary", "aap", required=True, type="dict"),
            FieldContract("top_errors", "aap", required=False, type="list"),
            FieldContract("by_cluster", "aap", required=False, type="dict"),
            FieldContract("by_lab", "aap", required=False, type="dict"),
            FieldContract("recent_failures", "aap", required=False, type="list"),
        ],
    ),
    "/dashboard/sandbox-api": ResponseContract(
        endpoint="/dashboard/sandbox-api",
        fields=[
            FieldContract("api_healthy", "sandbox_api", required=True, type="bool"),
            FieldContract("replicas_desired", "sandbox_api", required=False, type="int"),
            FieldContract("replicas_ready", "sandbox_api", required=False, type="int"),
            FieldContract("total_sandboxes", "scanner", required=False, type="int"),
            FieldContract("active", "scanner", required=False, type="int"),
            FieldContract("failing", "scanner", required=False, type="int"),
        ],
    ),
    "/dashboard/zerotouch": ResponseContract(
        endpoint="/dashboard/zerotouch",
        fields=[
            FieldContract("available", "zerotouch", required=True, type="bool"),
            FieldContract("catalog_total", "zerotouch", required=False, type="int"),
            FieldContract("catalog_active", "zerotouch", required=False, type="int"),
            FieldContract("workshops", "zerotouch", required=False, type="dict"),
        ],
    ),
    "/dashboard/capacity-analysis": ResponseContract(
        endpoint="/dashboard/capacity-analysis",
        fields=[
            FieldContract("pool_velocities", "computed", required=True, type="dict"),
            FieldContract("workload_complexities", "computed", required=True, type="dict"),
            FieldContract("evidence_summary", "computed", required=True, type="string"),
        ],
    ),
    "/dashboard/readiness": ResponseContract(
        endpoint="/dashboard/readiness",
        fields=[
            FieldContract("overall_readiness_pct", "computed", required=True, type="float"),
            FieldContract("gates", "multi_source", required=True, type="dict"),
            FieldContract("escalated_events", "event_bus", required=False, type="int"),
        ],
    ),
    "/dashboard/executive-summary": ResponseContract(
        endpoint="/dashboard/executive-summary",
        fields=[
            FieldContract("evidence", "multi_source", required=True, type="string"),
            FieldContract("analysis", "llm", required=True, type="string"),
            FieldContract("model", "llm", required=True, type="string"),
            FieldContract("readiness", "multi_source", required=True, type="dict"),
        ],
    ),
}
