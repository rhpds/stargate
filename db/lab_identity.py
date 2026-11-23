"""What counts as a lab namespace, in one place.

Lab namespaces are `sandbox-<code>-<catalog>`: a sandbox code, a dash, then the
catalog item (`sandbox-5bz2j-ocp4-cluster`). The platform's own *services* also
carry the prefix, so `startswith("sandbox-")` is not an identity test:

    sandbox-assignment-api      a service on ocp-us-east-1
    babylon-sandbox-api         already excluded by the prefix
    sandbox-diag2               a manual diagnostic namespace, not a catalog lab

`live_labs()`, the tier-3 collector and seven other queries all used the
`sandbox-%` prefix alone. That was dormant only because the five scanned
clusters happen to hold no such namespace — measured 2026-11-23, all 1,328
`sandbox-*` namespaces on ocpv03/06/07/08/09 are catalog labs. Adding a cluster
whose platform services get imported as labs would report failing demos that do
not exist.

The rule below is the smallest one that is true of the data:

* at least two dash-separated segments after `sandbox-` (`sandbox-<code>-<catalog>`),
  which drops `sandbox-diag2`;
* not a known platform service name, which drops `sandbox-assignment-api`.

**Not** a five-character sandbox code. It is tempting — 16,210 distinct codes in
`runs` are exactly five characters — but it is false: `sandbox-hcptest3`,
`hcptest5`–`hcptest8` and `sandbox-hcprt2` were real catalog labs in Jul–Aug
2026, 1,894 evaluations, and a five-character rule would have hidden them. A
predicate that hides a real lab fails silently and is the expensive direction;
one that admits a service produces a visibly failing "lab" and is cheap.

SQL and Python spellings must agree; both are exercised against the same
fixtures in `tests/test_lab_identity.py`. `LIKE` and `NOT IN` work on PostgreSQL
and on the in-memory SQLite the unit tests use, which a regular expression
would not.
"""

from __future__ import annotations

from typing import Any

LAB_NAMESPACE_PREFIX = "sandbox-"

#: Namespaces that carry the lab prefix but are platform services, not labs.
PLATFORM_SERVICE_NAMESPACES = frozenset({
    "sandbox-assignment-api",
    "sandbox-api-metrics",
})

#: SQL LIKE pattern equivalent to :func:`is_lab_namespace`.
LAB_CODE_LIKE = "sandbox-%-%"


def is_lab_namespace(name: str) -> bool:
    """True when *name* is a lab namespace rather than a similarly named service."""
    if not name.startswith(LAB_NAMESPACE_PREFIX) or name in PLATFORM_SERVICE_NAMESPACES:
        return False
    # "sandbox-<code>-<catalog>" has at least two dashes after the prefix.
    return name.count("-") >= 2


def lab_code_filter(column: Any) -> Any:
    """SQLAlchemy filter keeping only rows whose *column* is a lab namespace."""
    return column.like(LAB_CODE_LIKE) & column.notin_(sorted(PLATFORM_SERVICE_NAMESPACES))
