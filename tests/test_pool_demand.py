"""Per-pool demand projection — the event-pool class join.

TDD: written before engine/pool_demand.py exists. The join the gate's
event-pool failure demanded: session -> lab -> deploy_limit, occupancy
= attendees over the session duration, deficit when occupancy exceeds
the pool's environment slots. Validated shape (found in live data,
Nov 13 2026): LB1758 15 attendees vs limit 15 (the documented 98%),
LB2645 23 vs 11 (209% — the documented exhaustion), both scheduled
Sep 30 15:30.
"""

from datetime import datetime, timedelta, timezone

from engine.pool_demand import project_pool_demand

NOW = datetime.now(timezone.utc)


def _lab(code, deploy_limit, duration_hours=4.0):
    return {"lab_code": code, "deploy_limit": deploy_limit,
            "deploy_time_hours": duration_hours}


def _session(lab, hours_from_now, attendees, created_hours_before=48):
    start = NOW + timedelta(hours=hours_from_now)
    return {
        "lab_code": lab, "attendees": attendees,
        "start_time": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "session_date": start.strftime("%Y-%m-%d"),
        "created_at": (start - timedelta(hours=created_hours_before)).isoformat(),
    }


class TestPoolDemand:
    def test_occupancy_exceeding_limit_is_deficit(self):
        result = project_pool_demand(
            [_session("LB2645", 1, attendees=23)],
            {"LB2645": _lab("LB2645", deploy_limit=11)},
            hours=8, start=NOW)
        pool = result["pools"]["LB2645"]
        assert pool["deploy_limit"] == 11
        assert pool["peak_occupancy"] == 23
        assert pool["deficit_state"] == "deficit"
        assert pool["crossing_hour"] is not None

    def test_at_limit_is_not_deficit_but_flagged(self):
        """15 against 15 is full utilization — the documented 98 percent
        case — amber, not red: no headroom, no overshoot."""
        result = project_pool_demand(
            [_session("LB1758", 1, attendees=15)],
            {"LB1758": _lab("LB1758", deploy_limit=15)},
            hours=8, start=NOW)
        pool = result["pools"]["LB1758"]
        assert pool["deficit_state"] == "at_limit"

    def test_headroom_below_limit(self):
        result = project_pool_demand(
            [_session("LB1000", 1, attendees=5)],
            {"LB1000": _lab("LB1000", deploy_limit=15)},
            hours=8, start=NOW)
        assert result["pools"]["LB1000"]["deficit_state"] == "headroom"

    def test_occupancy_spans_session_duration(self):
        """23 attendees occupy slots for the session's duration, not just
        its start hour — the deficit persists across the window."""
        result = project_pool_demand(
            [_session("LB2645", 1, attendees=23)],
            {"LB2645": _lab("LB2645", deploy_limit=11, duration_hours=4)},
            hours=8, start=NOW)
        pool = result["pools"]["LB2645"]
        deficit_hours = [h for h in pool["hourly"] if h["occupancy"] > pool["deploy_limit"]]
        # 4h from :30 snaps outward to five occupied hours (15:00-20:00)
        assert len(deficit_hours) == 5

    def test_known_since_carries_lead_time_evidence(self):
        """The demand was knowable when the session was created — the
        crossing hour alone understates the warning lead time."""
        result = project_pool_demand(
            [_session("LB2645", 1, attendees=23, created_hours_before=72)],
            {"LB2645": _lab("LB2645", deploy_limit=11)},
            hours=8, start=NOW)
        pool = result["pools"]["LB2645"]
        assert pool["known_since"] is not None

    def test_unmapped_labs_counted_honestly(self):
        """Sessions for labs outside the index are counted, never
        dropped silently."""
        result = project_pool_demand(
            [_session("LB9999", 1, attendees=10)],
            {}, hours=8, start=NOW)
        assert result["coverage"]["sessions_unmapped"] == 1

    def test_zero_limit_is_indeterminate(self):
        """No deploy_limit declared — capacity unobserved, never zero."""
        result = project_pool_demand(
            [_session("LB0001", 1, attendees=10)],
            {"LB0001": {"lab_code": "LB0001", "deploy_limit": None}},
            hours=8, start=NOW)
        assert result["pools"]["LB0001"]["deficit_state"] == "indeterminate"


class TestZeroDuration:
    def test_zero_deploy_time_falls_back_to_default(self):
        """Found live: LB2645's deploy_time_hours is 0 — a zero-width
        span matched no hour and hid a 23-vs-11 deficit. Zero or negative
        durations fall back to the default session window."""
        result = project_pool_demand(
            [_session("LB2645", 1, attendees=23)],
            {"LB2645": {"lab_code": "LB2645", "deploy_limit": 11,
                        "deploy_time_hours": 0}},
            hours=8, start=NOW)
        pool = result["pools"]["LB2645"]
        assert pool["peak_occupancy"] == 23
        assert pool["deficit_state"] == "deficit"

    def test_zero_duration_string_also_falls_back(self):
        result = project_pool_demand(
            [_session("LB2645", 1, attendees=23)],
            {"LB2645": {"lab_code": "LB2645", "deploy_limit": 11,
                        "deploy_time_hours": "0.00"}},
            hours=8, start=NOW)
        assert result["pools"]["LB2645"]["peak_occupancy"] == 23


class TestSharedCohortEvents:
    """Roadshow semantics (found in the first forward pass, Nov 13 2026):
    one event (event_id 46) stamps its total attendance on every room
    session, all rooms running the same all-day window — the same ~70
    people rotating, not 70 concurrent environments per room. Sessions
    sharing (event_id, date) are one cohort: demand is the cohort's
    attendance once, against each room's limit only when that room
    hosts the whole cohort — conservatively, the max across the
    event's rooms, never the sum."""

    def _rot_session(self, lab, attendees, event_id=46):
        start = NOW + timedelta(hours=1)
        return {"lab_code": lab, "attendees": attendees, "event_id": event_id,
                "start_time": start.strftime("%Y-%m-%dT%H:%M:%S"),
                "session_date": start.strftime("%Y-%m-%d"),
                "created_at": start.isoformat()}

    def test_shared_event_is_one_cohort_not_summed(self):
        """11 rooms x 70 attendees of one event must not read as 770
        concurrent demands — the people are shared."""
        sessions = [self._rot_session("R%d" % i, 70) for i in range(11)]
        result = project_pool_demand(sessions, {}, hours=4, start=NOW)
        # all rooms share the cohort: each room's occupancy reflects the
        # cohort (70), and the fleet-level demand counts 70 once
        assert result["coverage"]["shared_cohort_sessions"] == 11

    def test_cohort_demand_is_max_not_sum_per_pool(self):
        """Same event, same date, different rooms mapped to the SAME
        catalog item: the pool sees the cohort once, not N times."""
        labs = {"R1": {"lab_code": "R1", "deploy_limit": 100},
                "R2": {"lab_code": "R2", "deploy_limit": 100}}
        sessions = [self._rot_session("R1", 70), self._rot_session("R2", 70)]
        result = project_pool_demand(sessions, labs, hours=4, start=NOW)
        assert result["coverage"]["sessions_mapped"] == 2
        assert result["cohort_demand"] == 70  # not 140

    def test_different_events_are_separate_cohorts(self):
        sessions = [self._rot_session("R1", 70, event_id=46),
                    self._rot_session("R1", 30, event_id=47)]
        result = project_pool_demand(sessions, {"R1": {"lab_code": "R1", "deploy_limit": 100}},
                                     hours=4, start=NOW)
        assert result["cohort_demand"] == 100  # separate people: summed

    def test_no_event_id_counts_normally(self):
        """Sessions without event_id keep workshop semantics: each
        session's attendees are its own concurrent demand."""
        s1 = self._rot_session("R1", 40, event_id=None)
        s2 = self._rot_session("R1", 30, event_id=None)
        result = project_pool_demand([s1, s2], {"R1": {"lab_code": "R1", "deploy_limit": 100}},
                                     hours=4, start=NOW)
        assert result["cohort_demand"] == 70
