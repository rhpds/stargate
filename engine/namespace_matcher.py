"""Namespace matcher — maps K8s namespaces to lab codes using fnmatch patterns."""

from __future__ import annotations

import fnmatch
from typing import Optional


def match_namespace_to_lab(namespace: str, mappings: list) -> Optional[str]:
    """Match a namespace against a list of pattern mappings.

    Each mapping should have:
      - namespace_pattern: a glob/fnmatch pattern (e.g. "ocp4-*-rhdp-*")
      - lab_code: the lab code to return on match

    Returns the lab_code for the first matching pattern, or None.
    """
    for m in mappings:
        pattern = m.get("namespace_pattern", "")
        if pattern and fnmatch.fnmatch(namespace, pattern):
            return m.get("lab_code")
    return None
