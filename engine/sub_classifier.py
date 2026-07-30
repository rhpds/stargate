"""Second-pass sub-classifier — determines root cause and workload context.

Runs after the primary failure_class regex match. Parses the event message
to determine WHY the failure happened, not just WHAT failed.
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, Optional

import yaml

logger = logging.getLogger("stargate.sub_classifier")

_SUB_CLASSES: Optional[Dict] = None


def _load_sub_classes() -> Dict:
    global _SUB_CLASSES
    if _SUB_CLASSES is not None:
        return _SUB_CLASSES

    path = Path(__file__).parent.parent / "failure-classes" / "sub-classes.yaml"
    if not path.exists():
        _SUB_CLASSES = {}
        return _SUB_CLASSES

    with open(path) as f:
        _SUB_CLASSES = yaml.safe_load(f) or {}
    return _SUB_CLASSES


def sub_classify(failure_class: str, message: str) -> Dict:
    """Return sub-classification for a failure based on message content.

    Returns dict with keys: sub_class, workload, auto_fix_confidence.
    Returns empty dict if no sub-class rules exist for this failure_class.
    """
    rules = _load_sub_classes()
    class_rules = rules.get(failure_class)
    if not class_rules:
        return {}

    msg = message or ""
    for rule in class_rules:
        pattern = rule.get("pattern")
        if pattern is None:
            return {
                "sub_class": rule["sub_class"],
                "workload": rule.get("workload", "unknown"),
                "auto_fix_confidence": rule.get("auto_fix_confidence", "low"),
            }
        if re.search(pattern, msg, re.IGNORECASE):
            return {
                "sub_class": rule["sub_class"],
                "workload": rule.get("workload", "unknown"),
                "auto_fix_confidence": rule.get("auto_fix_confidence", "low"),
            }

    return {}


def get_sub_class_info(sub_class: str) -> Dict:
    """Look up metadata for a sub_class name."""
    rules = _load_sub_classes()
    for fc, class_rules in rules.items():
        for rule in class_rules:
            if rule.get("sub_class") == sub_class:
                return {
                    "failure_class": fc,
                    "sub_class": sub_class,
                    "workload": rule.get("workload", "unknown"),
                    "auto_fix_confidence": rule.get("auto_fix_confidence", "low"),
                }
    return {}
