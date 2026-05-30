"""Shared failure class schema — consumed by both StarGate and DeepField.

Provides a normalized wire format for cross-product failure class sync.
StarGate serves classes via GET /api/failure-classes, DeepField consumes
them to build its FailureClassifierAgent pattern table.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class FailureClass:
    name: str
    patterns: List[str]
    severity: str = "medium"
    source: str = "unknown"
    remediation: str = ""
    category: str = "general"


CATEGORY_MAP = {
    "k8s-events": "pod_health",
    "alertmanager": "cluster_health",
    "infrastructure": "infrastructure",
    "summit": "provisioning",
    "aap": "provisioning",
}


def normalize_raw_class(raw: dict) -> dict:
    """Convert a StarGate failure class (from YAML loader) to the shared wire format."""
    patterns = raw.get("patterns", [])
    if not patterns:
        pattern_str = raw.get("pattern", "")
        if pattern_str:
            patterns = [p.strip() for p in pattern_str.strip("()").split("|") if p.strip()]
    if not patterns:
        alertnames = raw.get("alertnames", [])
        if alertnames:
            patterns = alertnames if isinstance(alertnames, list) else [alertnames]
    if isinstance(patterns, str):
        patterns = [patterns]

    source = raw.get("source", raw.get("_source", "unknown"))

    return {
        "name": raw.get("name", raw.get("failure_class", "")),
        "patterns": patterns,
        "severity": raw.get("severity", "medium"),
        "source": source,
        "remediation": raw.get("remediation", ""),
        "category": CATEGORY_MAP.get(source, "general"),
    }
