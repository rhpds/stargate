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
