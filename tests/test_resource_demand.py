"""Resource demand projection — the profiles × schedule join.

TDD: written before project_resource_demand exists. Pins the contract
for per-hour demand in real units (VM slots, AI cores, AI GiB) with
honest coverage (labs without profiles contribute no units — observed
demand is flagged as a lower bound) and per-hour citations (EDD: every
unit traceable to the sessions that produced it).
"""

from datetime import datetime, timedelta, timezone

from engine.capacity_projector import project_resource_demand
from engine.resource_profiles import ResourceProfile

NOW = datetime.now(timezone.utc)


def _session(lab, hours_from_now, attendees, pool="default"):
    start = NOW + timedelta(hours=hours_from_now)
    return {
        "lab_code": lab,
        "start_time": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "attendees": attendees,
        "pool_name": pool,
    }


def _profiles(**overrides):
    base = {
        "lab-a": ResourceProfile("lab-a", 3, 8.0, 32.0, "observed", "s"),
        "lab-b": ResourceProfile("lab-b", 2, None, None, "observed", "s"),
        "lab-c": ResourceProfile("lab-c", None, None, None, "fallback", "s"),
    }
    base.update(overrides)
    return base


class TestResourceDemandProjection:
    def test_demand_is_attendees_times_units(self):
        """Given 10 attendees on a lab needing 3 workers and 8 cores each,
        the hour's demand is 30 VM slots and 80 cores."""
        result = project_resource_demand(
            [_session("lab-a", 1, attendees=10)],
            _profiles(), hours=4, start=NOW,
        )
        hour = result["hourly"][1]
        assert hour["vm_slots"] == 30
        assert hour["ai_cores"] == 80.0
        assert hour["ai_memory_gib"] == 320.0

    def test_partial_profiles_contribute_what_they_have(self):
        """lab-b has a worker count but no AI specs: VM demand is real,
        AI demand is absent (not zero-valued fakery)."""
        result = project_resource_demand(
            [_session("lab-b", 1, attendees=5)],
            _profiles(), hours=4, start=NOW,
        )
        hour = result["hourly"][1]
        assert hour["vm_slots"] == 10
        assert hour["ai_cores"] is None

    def test_unprofiled_labs_flag_lower_bound(self):
        """Sessions for labs without profiles contribute no units and are
        counted — observed demand is explicitly a lower bound."""
        result = project_resource_demand(
            [_session("lab-c", 1, attendees=40)],
            _profiles(), hours=4, start=NOW,
        )
        hour = result["hourly"][1]
        assert hour["vm_slots"] is None
        assert hour["sessions_without_profiles"] == 1
        assert result["coverage"]["sessions_fallback"] == 1
        assert result["coverage"]["lower_bound"] is True

    def test_mixed_coverage_counts_honestly(self):
        result = project_resource_demand(
            [_session("lab-a", 1, 10), _session("lab-b", 2, 5),
             _session("lab-c", 3, 40), _session("lab-z", 1, 7)],
            _profiles(), hours=6, start=NOW,
        )
        c = result["coverage"]
        assert c["sessions_total"] == 4
        assert c["sessions_with_profiles"] == 2
        assert c["sessions_fallback"] == 2  # lab-c + unknown lab-z
        assert c["lower_bound"] is True

    def test_demand_carries_citations(self):
        """EDD: each hour's demand cites the sessions that produced it."""
        result = project_resource_demand(
            [_session("lab-a", 1, 10), _session("lab-b", 1, 5)],
            _profiles(), hours=4, start=NOW,
        )
        hour = result["hourly"][1]
        citations = hour["demand_citations"]
        by_lab = {c["lab"]: c for c in citations}
        assert by_lab["lab-a"]["attendees"] == 10
        assert by_lab["lab-a"]["vm_slots"] == 30
        assert by_lab["lab-b"]["attendees"] == 5
        assert by_lab["lab-b"]["vm_slots"] == 10

    def test_sessions_outside_window_excluded(self):
        result = project_resource_demand(
            [_session("lab-a", 1, 10), _session("lab-a", 48, 10)],
            _profiles(), hours=4, start=NOW,
        )
        assert result["coverage"]["sessions_total"] == 1

    def test_malformed_times_skipped_not_fatal(self):
        bad = _session("lab-a", 1, 10)
        bad["start_time"] = "not-a-time"
        result = project_resource_demand(
            [bad, _session("lab-a", 2, 10)],
            _profiles(), hours=4, start=NOW,
        )
        assert result["coverage"]["sessions_total"] == 1

    def test_peak_hour_reported(self):
        """The summary names the peak-demand hour in real units."""
        result = project_resource_demand(
            [_session("lab-a", 1, 10), _session("lab-a", 3, 30)],
            _profiles(), hours=6, start=NOW,
        )
        assert result["peak_hour"]["vm_slots"] == 90
        assert result["peak_hour"]["hour"] == result["hourly"][3]["hour"]
