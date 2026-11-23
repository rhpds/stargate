"""Resolve cluster kubeconfig files.

Canonical name is `kubeconfig-<cluster>`, and it is the only name this module
resolves on its own.

The 2026 Turkey Vulture rotation replaced the scanner service-account tokens.
The old filenames `kubeconfig` (ocp-us-east-1) and `kubeconfig-cnv` (ocpv06)
held revoked tokens. They survived the rotation because resolution fell back to
them when the canonical file was missing — so a deployment that lost a
canonical copy would silently keep working against a dead credential, and
`ocpv06` was one missing file away from scanning nothing while reporting a
healthy cycle.

That fallback is gone. A missing canonical file is now a visible error naming
the file that should be there, which is what `Scheduler` logs and what
`credential-health` reports.

An explicitly configured filename is still honoured, including a legacy one:
that is a deliberate operator choice (a comma-separated `STARGATE_CLUSTERS`
mapping exists for it), not a silent fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

SECRETS_DIR = Path(__file__).parent.parent / "secrets"


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
    name. Returns the canonical path when nothing exists, so the caller's error
    names the file that should be there.
    """
    base = Path(secrets_dir) if secrets_dir else SECRETS_DIR

    if kubeconfig:
        # An explicitly configured filename is what the operator asked for;
        # return it even when missing so the error names that path.
        return base / kubeconfig

    return base / canonical_name(cluster)
