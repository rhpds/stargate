"""YAML loader for policy rules — loads from policies/rules.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from engine.policy_models import PolicyRuleSet


class PolicyLoadError(Exception):
    pass


_DEFAULT_PATH = Path(__file__).parent.parent / "policies" / "rules.yaml"
_cache: Optional[PolicyRuleSet] = None


def load_policy_rules(path: Optional[Path] = None) -> PolicyRuleSet:
    """Load policy rules from YAML. Caches on first load for default path."""
    global _cache
    use_path = path or _DEFAULT_PATH

    if path is None and _cache is not None:
        return _cache

    if not use_path.exists():
        raise PolicyLoadError(f"Policy rules file not found: {use_path}")

    try:
        with open(use_path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise PolicyLoadError(f"Invalid YAML in {use_path}: {e}") from e

    if not isinstance(data, dict):
        raise PolicyLoadError(f"Policy rules file must contain a YAML mapping, got {type(data)}")

    try:
        ruleset = PolicyRuleSet(**data)
    except Exception as e:
        raise PolicyLoadError(f"Policy rules validation failed: {e}") from e

    if path is None:
        _cache = ruleset

    return ruleset
