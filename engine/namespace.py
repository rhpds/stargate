"""Sandbox namespace parsing — single source of truth for the sandbox-{guid}-{catalog} pattern."""

import re
from typing import Optional, Tuple

_SANDBOX_RE = re.compile(r"^sandbox-([a-z0-9]+)-(.+)$")


def extract_catalog_item(ns: str) -> Optional[str]:
    m = _SANDBOX_RE.match(ns)
    return m.group(2) if m else None


def extract_guid(ns: str) -> Optional[str]:
    m = _SANDBOX_RE.match(ns)
    return m.group(1) if m else None


def extract_sandbox_parts(ns: str) -> Optional[Tuple[str, str]]:
    m = _SANDBOX_RE.match(ns)
    return (m.group(1), m.group(2)) if m else None


def is_sandbox(ns: str) -> bool:
    return _SANDBOX_RE.match(ns) is not None


def strip_sandbox_prefix(ns: str) -> str:
    m = _SANDBOX_RE.match(ns)
    return m.group(2) if m else ns
