"""Resource profiles — per-catalog resource units for capacity forecasting.

Turns the AgnosticV constraints already parsed by
``constraints/agnosticv_loader.py`` (worker_instance_count,
ai_workers_cores, ai_workers_memory) into demand-side units for the
capacity projector. Evidence semantics are tri-state, like everything
else in the platform:

- ``observed``    — declared specs present (the profile carries real units)
- ``fallback``    — the item was parsed and simply declares no resources;
                    demand falls back to complexity scores
- ``indeterminate`` — the item could not be parsed at all (loader error)

Values are never fabricated: a missing or malformed spec is ``None``
(unobserved), never zero. Grounded in the real catalog audit of Nov 12
2026: 316 items, 126 with worker counts, 61 with AI specs — the fallback
path carries ~60% of the catalog and is a first-class design element,
not an edge case.
"""

from typing import Dict, List, Optional

_MEMORY_UNITS = {
    "ki": 1.0 / (1024 * 1024),
    "mi": 1.0 / 1024,
    "gi": 1.0,
    "ti": 1024.0,
}


def parse_memory_gib(value) -> Optional[float]:
    """Parse a Kubernetes-style memory string into GiB; None if unparseable."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    for suffix, factor in _MEMORY_UNITS.items():
        if lowered.endswith(suffix):
            head = lowered[: -len(suffix)].strip()
            try:
                return float(head) * factor
            except ValueError:
                return None
    try:
        return float(lowered)
    except ValueError:
        return None


def _parse_int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def _parse_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return None


class ResourceProfile:
    """Resource units for one catalog item, with coverage and citation.

    ``worker_formula`` captures Jinja-templated worker counts (54 items in
    the real catalog, e.g. ``max(ceil(num_users/10), 3)``) — the catalog's
    own demand-scaling rule. Phase 1b evaluates these against session
    attendee counts; until then they contribute no static units and count
    as fallback, but the evidence is preserved rather than discarded.
    """

    def __init__(self, catalog_item: str, worker_count: Optional[int],
                 ai_cores: Optional[float], ai_memory_gib: Optional[float],
                 coverage: str, source: str = "",
                 worker_formula: Optional[str] = None):
        self.catalog_item = catalog_item
        self.worker_count = worker_count
        self.ai_cores = ai_cores
        self.ai_memory_gib = ai_memory_gib
        self.coverage = coverage
        self.source = source
        self.worker_formula = worker_formula

    @classmethod
    def from_constraints(cls, catalog_item: str, constraints: Dict,
                         source: str = "") -> "ResourceProfile":
        """Build a profile from loader-shaped constraints.

        An error dict from the loader (unparseable YAML) is indeterminate;
        the absence of specs is fallback. Both keep every unit None.
        """
        if not isinstance(constraints, Dict) or "error" in constraints:
            return cls(catalog_item, None, None, None, "indeterminate", source)

        worker_count = _parse_int(constraints.get("worker_instance_count"))
        ai_cores = _parse_float(constraints.get("ai_workers_cores"))
        ai_memory = parse_memory_gib(constraints.get("ai_workers_memory"))

        # A Jinja-templated worker count is a scaling formula, not a unit —
        # preserved as evidence for Phase 1b formula evaluation.
        raw_worker = constraints.get("worker_instance_count")
        worker_formula = None
        if worker_count is None and raw_worker and "{" in str(raw_worker):
            worker_formula = str(raw_worker)

        # Observed = the profile contributes real units to at least one
        # demand dimension (workers, AI cores, AI memory). A worker count
        # alone is observed VM demand; only total absence of specs is
        # fallback. Audited reality: 90 of 316 items parse to real units;
        # 54 more carry scaling formulas.
        any_unit = any(v is not None for v in (worker_count, ai_cores, ai_memory))
        coverage = "observed" if any_unit else "fallback"
        return cls(catalog_item, worker_count, ai_cores, ai_memory,
                   coverage, source, worker_formula)

    @staticmethod
    def coverage_stats(profiles: List["ResourceProfile"]) -> Dict[str, int]:
        """Counts per coverage state — the profile-coverage rubric input."""
        stats = {"observed": 0, "fallback": 0, "indeterminate": 0}
        for p in profiles:
            stats[p.coverage] = stats.get(p.coverage, 0) + 1
        return stats

    def to_dict(self) -> Dict:
        return {
            "catalog_item": self.catalog_item,
            "worker_count": self.worker_count,
            "ai_cores": self.ai_cores,
            "ai_memory_gib": self.ai_memory_gib,
            "coverage": self.coverage,
            "source": self.source,
        }


def build_resource_profiles(constraints_by_item: Dict[str, Dict],
                            source_prefix: str = "agnosticv") -> Dict[str, ResourceProfile]:
    """Build the profile index from load_all_constraints() output."""
    profiles: Dict[str, ResourceProfile] = {}
    for item, constraints in (constraints_by_item or {}).items():
        profiles[item] = ResourceProfile.from_constraints(
            item, constraints, source="%s/%s/common.yaml" % (source_prefix, item))
    return profiles
