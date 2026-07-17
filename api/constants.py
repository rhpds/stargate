"""Shared constants — single source of truth for values used across routers, engine, and DB."""

import os

WARNING_CLASSES = {"guest_agent_not_connected", "health_check_failed"}

_ECOSYSTEM_DEFAULT = "launchpad-,stargate,deepfield,intel-rh-,user-demo-,partner-ai-"

ECOSYSTEM_PREFIXES = [
    p.strip() for p in
    os.environ.get("STARGATE_ECOSYSTEM_NS", _ECOSYSTEM_DEFAULT).split(",")
    if p.strip()
]

REMEDIATION_ALLOWED_PREFIXES = [
    p.strip() for p in
    os.environ.get("STARGATE_REMEDIATION_NS", _ECOSYSTEM_DEFAULT).split(",")
    if p.strip()
]

# Lab-level execution policy modes (distinct from engine.models.RemediationMode
# which describes catalog entry modes like recommend_only/auto_execute)
VALID_EXECUTION_MODES = {"recommend_only", "low_risk_auto", "full_auto"}


def is_ecosystem_ns(ns: str) -> bool:
    return any(ns.startswith(p) for p in ECOSYSTEM_PREFIXES)
