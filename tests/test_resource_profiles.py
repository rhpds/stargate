"""Resource profiles — the demand-side join for capacity forecasting.

TDD: written before engine/resource_profiles.py exists. These tests pin
the contract for turning parsed AgnosticV constraints into per-catalog
resource units, with honest tri-state coverage (observed specs /
complexity fallback / indeterminate) — the same evidence semantics the
platform applies everywhere else. Grounded in the real catalog (Nov 12
2026: 316 items, 126 with worker_instance_count, 61 with ai_workers
specs) — the fallback path is load-bearing for the ~60% without specs.
"""

from pathlib import Path

import pytest

from engine.resource_profiles import (
    ResourceProfile,
    build_resource_profiles,
    parse_memory_gib,
)

AGNOSTICV_DIR = Path(__file__).parent.parent.parent / "github review" / "agnosticv"


class TestMemoryParsing:
    def test_gib(self):
        assert parse_memory_gib("32Gi") == 32.0

    def test_mib_converts(self):
        assert parse_memory_gib("512Mi") == 0.5

    def test_tib_converts(self):
        assert parse_memory_gib("1Ti") == 1024.0

    def test_bare_number_is_gib(self):
        assert parse_memory_gib("16") == 16.0

    def test_malformed_is_none_not_zero(self):
        # None = unobserved; 0 would be a false claim of no memory
        assert parse_memory_gib("lots") is None
        assert parse_memory_gib("") is None
        assert parse_memory_gib(None) is None


class TestResourceProfileContract:
    def test_full_spec_is_observed(self):
        """Given a constraint dict with real specs, the profile carries
        resource units and observed coverage with a source citation."""
        profile = ResourceProfile.from_constraints(
            "my-lab",
            {"worker_instance_count": "3",
             "ai_workers_cores": "8",
             "ai_workers_memory": "32Gi",
             "cloud_provider": "aws"},
            source="agnosticv/my-lab/common.yaml",
        )
        assert profile.catalog_item == "my-lab"
        assert profile.worker_count == 3
        assert profile.ai_cores == 8.0
        assert profile.ai_memory_gib == 32.0
        assert profile.coverage == "observed"
        assert profile.source == "agnosticv/my-lab/common.yaml"

    def test_partial_spec_keeps_values_and_is_observed(self):
        """A lab with a worker count but no AI specs keeps what it has —
        a worker count alone is observed VM demand, not fallback."""
        profile = ResourceProfile.from_constraints(
            "partial-lab", {"worker_instance_count": "2"}, source="s")
        assert profile.worker_count == 2
        assert profile.ai_cores is None
        assert profile.coverage == "observed"

    def test_no_specs_is_fallback(self):
        """No declared resources → complexity-score territory, never a
        fabricated zero."""
        profile = ResourceProfile.from_constraints("bare-lab", {}, source="s")
        assert profile.worker_count is None
        assert profile.ai_cores is None
        assert profile.ai_memory_gib is None
        assert profile.coverage == "fallback"

    def test_malformed_values_are_unobserved(self):
        """Garbage in the spec fields degrades to unobserved, not crash,
        not fake numbers."""
        profile = ResourceProfile.from_constraints(
            "weird-lab",
            {"worker_instance_count": "many",
             "ai_workers_cores": "fast",
             "ai_workers_memory": "big"},
            source="s")
        assert profile.worker_count is None
        assert profile.ai_cores is None
        assert profile.ai_memory_gib is None
        assert profile.coverage == "fallback"

    def test_empty_constraints_are_indeterminate(self):
        """The loader returns an error dict for unparseable YAML — that is
        indeterminate (we could not observe), distinct from fallback
        (we observed, there were no specs)."""
        profile = ResourceProfile.from_constraints(
            "broken-lab", {"error": "empty or unparseable YAML"}, source="s")
        assert profile.coverage == "indeterminate"
        assert profile.worker_count is None


class TestProfileCollection:
    def test_build_from_loader_output(self):
        """Given loader-shaped constraints for several items, the
        collection indexes by catalog item and reports coverage stats."""
        constraints = {
            "lab-a": {"worker_instance_count": "3",
                      "ai_workers_cores": "8",
                      "ai_workers_memory": "32Gi"},
            "lab-b": {"worker_instance_count": "2"},
            "lab-c": {},
            "lab-d": {"error": "empty or unparseable YAML"},
        }
        profiles = build_resource_profiles(constraints)
        assert set(profiles) == {"lab-a", "lab-b", "lab-c", "lab-d"}
        assert profiles["lab-a"].coverage == "observed"
        assert profiles["lab-b"].coverage == "observed"  # worker demand alone
        assert profiles["lab-d"].coverage == "indeterminate"
        stats = ResourceProfile.coverage_stats(list(profiles.values()))
        assert stats == {"observed": 2, "fallback": 1, "indeterminate": 1}

    def test_templated_worker_count_is_captured_as_formula(self):
        """A Jinja worker count is a scaling rule, not a unit: no static
        value (fallback), but the formula is preserved as evidence for
        Phase 1b evaluation against attendee counts."""
        profile = ResourceProfile.from_constraints(
            "scaled-lab",
            {"worker_instance_count":
             "{{ [(num_users | int / 10) | round(0, 'ceil') | int, 3] | max }}"},
            source="s")
        assert profile.worker_count is None
        assert profile.worker_formula is not None
        assert "num_users" in profile.worker_formula
        assert profile.coverage == "fallback"

    @pytest.mark.skipif(not AGNOSTICV_DIR.exists(), reason="AgnosticV repo not cloned")
    def test_real_catalog_coverage(self):
        """Against the real catalog: profiles build for every item;
        observed coverage matches the audited reality (90 of 316 parse to
        real units, ~28 percent; 54 more carry scaling formulas captured
        as worker_formula) — the evidence anchor for the fallback design."""
        from constraints.agnosticv_loader import load_all_constraints
        constraints = load_all_constraints(AGNOSTICV_DIR)
        profiles = build_resource_profiles(constraints)
        assert len(profiles) >= 300
        stats = ResourceProfile.coverage_stats(list(profiles.values()))
        observed_fraction = stats["observed"] / len(profiles)
        assert 0.22 < observed_fraction < 0.40, (
            "observed coverage drifted from the audited ~28%%: %s" % stats)
        formulas = [p for p in profiles.values() if p.worker_formula]
        assert 40 <= len(formulas) <= 70, (
            "scaling-formula count drifted from the audited 54: %d" % len(formulas))
