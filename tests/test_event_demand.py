"""Event-grouped demand — the Summit/RH1-scale view.

TDD: written before engine/event_demand.py exists. Per event, per day:
sessions, the cohort bound (shared people) and the summed bound
(workshop semantics), plus peak concurrent from REAL session
start/end times. The two bounds are the honest answer — whether an
event's rooms share one rotating cohort (roadshow) or hold separate
audiences (workshop) is not in the data, so the demand is bounded,
not pointed.
"""

from datetime import datetime, timezone

from engine.event_demand import project_event_demand

NOW = datetime.now(timezone.utc)


def _session(event_id, date, start, end, attendees, lab="LB1"):
    return {"event_id": event_id, "session_date": date, "start_time": start,
            "end_time": end, "attendees": attendees, "lab_code": lab}


class TestEventDemand:
    def test_per_event_per_day_shape(self):
        result = project_event_demand([
            _session(32, "2027-01-19", "09:00:00", "12:00:00", 120),
            _session(32, "2027-01-19", "13:00:00", "16:00:00", 90),
            _session(32, "2027-01-20", "09:00:00", "12:00:00", 120),
        ], start=datetime(2027, 1, 18, tzinfo=timezone.utc), days=5)
        ev = result["events"]["32"]
        assert ev["days"]["2027-01-19"]["sessions"] == 2
        assert ev["days"]["2027-01-20"]["sessions"] == 1

    def test_cohort_bound_is_max_not_sum(self):
        """Shared event + date: the people bound is the max attendance
        (one rotating cohort), not the sum."""
        result = project_event_demand([
            _session(46, "2026-11-17", "08:00:00", "18:00:00", 70, lab="R1"),
            _session(46, "2026-11-17", "08:00:00", "18:00:00", 70, lab="R2"),
            _session(46, "2026-11-17", "08:00:00", "18:00:00", 70, lab="R3"),
        ], start=NOW, days=7)
        day = result["events"]["46"]["days"]["2026-11-17"]
        assert day["cohort_bound"] == 70

    def test_summed_bound_is_the_workshop_upper(self):
        result = project_event_demand([
            _session(46, "2026-11-17", "08:00:00", "18:00:00", 70, lab="R1"),
            _session(46, "2026-11-17", "08:00:00", "18:00:00", 70, lab="R2"),
        ], start=NOW, days=7)
        day = result["events"]["46"]["days"]["2026-11-17"]
        assert day["summed_bound"] == 140

    def test_peak_concurrent_uses_real_times(self):
        """Non-overlapping sessions do not sum into the peak; overlapping
        ones do — computed from actual start/end, not assumed durations."""
        result = project_event_demand([
            _session(32, "2027-01-19", "09:00:00", "12:00:00", 100),
            _session(32, "2027-01-19", "09:30:00", "11:30:00", 50),
            _session(32, "2027-01-19", "14:00:00", "16:00:00", 120),
        ], start=datetime(2027, 1, 18, tzinfo=timezone.utc), days=5)
        day = result["events"]["32"]["days"]["2027-01-19"]
        assert day["peak_concurrent"] == 150  # morning overlap, not 270

    def test_sessions_without_event_are_grouped_as_ungrouped(self):
        result = project_event_demand([
            _session(None, "2027-01-19", "09:00:00", "12:00:00", 30),
        ], start=datetime(2027, 1, 18, tzinfo=timezone.utc), days=5)
        assert result["events"]["ungrouped"]["days"]["2027-01-19"]["sessions"] == 1
