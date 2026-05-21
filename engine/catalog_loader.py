"""Remediation catalog loader — loads from remediations/catalog.yaml and bridges action types to catalog entries."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from engine.models import Remediation, RemediationRisk


RISK_ORDER = {
    RemediationRisk.LOW: 0,
    RemediationRisk.MEDIUM: 1,
    RemediationRisk.HIGH: 2,
    RemediationRisk.CRITICAL: 3,
}


ACTION_TO_FAILURE_CLASSES = {
    "cleanup_stuck": ["pods_crashlooping", "pods_not_ready"],
    "smoke_test_failing": ["smoke_test_failed", "health_check_failed"],
    "provision_blocked_lab": ["provision_not_started", "anarchysubject_missing", "provision_failed"],
    "pool_exhaustion": ["pool_exhausted", "pool_capacity_low"],
    "cluster_capacity": ["cluster_overloaded", "cluster_memory_pressure"],
}

_DEFAULT_PATH = Path(__file__).parent.parent / "remediations" / "catalog.yaml"
_cache: Optional[List[Remediation]] = None


def load_catalog(path: Optional[Path] = None) -> List[Remediation]:
    """Load remediation catalog from YAML. Validates each entry against the Remediation model."""
    global _cache
    use_path = path or _DEFAULT_PATH

    if path is None and _cache is not None:
        return _cache

    with open(use_path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, list):
        return []

    entries = []
    for item in data:
        entries.append(Remediation(**item))

    if path is None:
        _cache = entries

    return entries


def get_commands_for_action(
    action_type: str,
    namespace: str,
    params: Dict[str, Any],
    max_risk: Optional[RemediationRisk] = None,
) -> List[str]:
    """Find catalog entries matching an action type and return formatted commands.

    Bridges action types (e.g., 'cleanup_stuck') to catalog entries via failure class mapping.
    Filters entries where forbidden_when matches the namespace.
    Substitutes {namespace}, {pod}, {deployment}, etc. in command templates.
    When max_risk is set, only entries at or below that risk level are included.
    """
    failure_classes = ACTION_TO_FAILURE_CLASSES.get(action_type, [])
    if not failure_classes:
        return []

    catalog = load_catalog()
    matching_entries = []
    max_risk_level = RISK_ORDER.get(max_risk, 999) if max_risk else 999

    for entry in catalog:
        if entry.mode.value == "recommend_only":
            continue
        if RISK_ORDER.get(entry.risk, 0) > max_risk_level:
            continue
        entry_classes = set()
        for condition in entry.allowed_when:
            parts = condition.split("==")
            if len(parts) == 2 and parts[0].strip() == "failure_class":
                entry_classes.add(parts[1].strip())

        if entry_classes & set(failure_classes):
            if not _is_forbidden(entry, namespace):
                matching_entries.append(entry)

    _safe_name = re.compile(r"^[a-zA-Z0-9._\-]*$")
    _safe_url = re.compile(r"^https?://[a-zA-Z0-9._\-/:]+$")

    def _sanitize(val: str, allow_url: bool = False) -> str:
        v = str(val)
        if allow_url and _safe_url.match(v):
            return v
        if _safe_name.match(v):
            return v
        return re.sub(r"[^a-zA-Z0-9._\-]", "", v)

    commands = []
    substitutions = {
        "namespace": _sanitize(namespace),
        "pod": _sanitize(params.get("pods", ["unknown"])[0] if isinstance(params.get("pods"), list) and params.get("pods") else params.get("pod", "unknown")),
        "deployment": _sanitize(params.get("deployment", "app")),
        "pool": _sanitize(params.get("pool", "default-pool")),
        "vm_name": _sanitize(params.get("vm_name", "vm")),
        "service": _sanitize(params.get("service", "svc")),
        "run_id": _sanitize(params.get("run_id", "")),
        "route_url": _sanitize(params.get("route_url", ""), allow_url=True),
        "showroom_url": _sanitize(params.get("showroom_url", ""), allow_url=True),
        "isvc_name": _sanitize(params.get("isvc_name", "")),
        "inference_url": _sanitize(params.get("inference_url", ""), allow_url=True),
    }

    for entry in matching_entries:
        for cmd_template in entry.commands:
            cmd = cmd_template
            for key, val in substitutions.items():
                cmd = cmd.replace("{" + key + "}", val)
            commands.append(cmd)

    return commands


def _is_forbidden(entry: Remediation, namespace: str) -> bool:
    """Check if an entry's forbidden_when conditions match the namespace."""
    for condition in entry.forbidden_when:
        parts = condition.split("==")
        if len(parts) == 2 and parts[0].strip() == "namespace":
            pattern = parts[1].strip().strip('"').strip("'")
            if fnmatch.fnmatch(namespace, pattern):
                return True
    return False
