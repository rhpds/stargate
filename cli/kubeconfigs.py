"""Resolve cluster kubeconfig files, with legacy filename aliases.

The 2026 Turkey Vulture rotation replaced the scanner service-account tokens.
The old filenames `kubeconfig` and `kubeconfig-cnv` held revoked tokens; they
survived only because code defaults and two helper scripts still named them, so
any redeploy or manual scan run pointed at dead credentials.

Canonical name is `kubeconfig-<cluster>`. Legacy names are still readable so an
existing deployment keeps working while the copies are cleaned up.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

SECRETS_DIR = Path(__file__).parent.parent / "secrets"

# cluster -> pre-rotation filename. Read-only fallback; never written.
LEGACY_ALIASES = {
    "ocpv06": "kubeconfig-cnv",
    "ocp-us-east-1": "kubeconfig",
}


def canonical_name(cluster: str) -> str:
    """The kubeconfig filename for a cluster."""
    return f"kubeconfig-{cluster}"


def resolve_kubeconfig(
    cluster: str,
    kubeconfig: Optional[str] = None,
    secrets_dir: Optional[Path] = None,
) -> Path:
    """Return the kubeconfig path for a cluster.

    Resolution order: the explicitly configured filename, then the canonical
    name, then the pre-rotation alias. Returns the canonical path when nothing
    exists, so the caller's error names the file that should be there rather
    than a legacy one that never will be.
    """
    base = Path(secrets_dir) if secrets_dir else SECRETS_DIR

    if kubeconfig:
        explicit = base / kubeconfig
        if explicit.exists():
            return explicit
        alias = LEGACY_ALIASES.get(cluster)
        if alias and (base / alias).exists():
            return base / alias
        return explicit

    canonical = base / canonical_name(cluster)
    if canonical.exists():
        return canonical
    alias = LEGACY_ALIASES.get(cluster)
    if alias and (base / alias).exists():
        return base / alias
    return canonical
