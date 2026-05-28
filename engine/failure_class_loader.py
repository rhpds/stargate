"""Failure class loader — reads classification definitions from YAML files.

All failure classes are defined in failure-classes/*.yaml, not in Python code.
This module loads them and provides lookup functions for the miners.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger("stargate.failure_classes")

FAILURE_CLASSES_DIR = Path(__file__).parent.parent / "failure-classes"

_cache: Dict[str, Dict] = {}
_cache_loaded = False


def _load_all() -> None:
    global _cache, _cache_loaded
    if _cache_loaded:
        return
    _cache = {}
    for yaml_file in sorted(FAILURE_CLASSES_DIR.glob("*.yaml")):
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
            source = data.get("source", yaml_file.stem)
            for cls_name, cls_data in data.get("classes", {}).items():
                cls_data["_source_file"] = yaml_file.name
                cls_data["_source"] = source
                _cache[cls_name] = cls_data
        except Exception as e:
            logger.warning("Failed to load %s: %s", yaml_file, e)
    _cache_loaded = True
    logger.info("Loaded %d failure classes from %d files", len(_cache), len(list(FAILURE_CLASSES_DIR.glob("*.yaml"))))


def get_all_classes() -> Dict[str, Dict]:
    _load_all()
    return dict(_cache)


def get_class(name: str) -> Optional[Dict]:
    _load_all()
    return _cache.get(name)


def get_classes_by_source(source: str) -> Dict[str, Dict]:
    _load_all()
    return {k: v for k, v in _cache.items() if v.get("_source") == source}


def classify_by_pattern(text: str, source: str = None) -> Tuple[str, Dict]:
    """Match text against all failure class patterns. Returns (class_name, class_data)."""
    _load_all()
    classes = _cache if source is None else get_classes_by_source(source)
    for cls_name, cls_data in classes.items():
        pattern = cls_data.get("pattern", "")
        if pattern and re.search(pattern, text, re.IGNORECASE):
            return cls_name, cls_data
    return "unclassified", {}


def classify_by_alertname(alertname: str, description: str = "") -> Tuple[str, Dict]:
    """Match an alert by its alertname field."""
    _load_all()
    alert_classes = get_classes_by_source("alertmanager")

    # Special case: InsightsRecommendationActive with CVE
    if alertname == "InsightsRecommendationActive" and re.search(r"CVE-\d{4}-\d+", description):
        cls = alert_classes.get("insights_cve")
        if cls:
            return "insights_cve", cls

    for cls_name, cls_data in alert_classes.items():
        if alertname in cls_data.get("alertnames", []):
            return cls_name, cls_data
    return "unclassified_alert", {}


def reload():
    """Force reload from disk."""
    global _cache_loaded
    _cache_loaded = False
    _load_all()
