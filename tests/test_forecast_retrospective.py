"""Retrospective harness — crossing and lead-time computation.

TDD for the pure logic: the crossing is the first hard DEFICIT before
the documented onset; soft lower-bound signals are reported but never
counted; lead time is onset minus crossing.
"""

from datetime import datetime, timezone

from scripts.forecast_retrospective import (
    build_retrospective,
    find_crossing,
    risk_during_window,
    sessions_in_window,
)

ONSET = datetime(2026, 10, 13, 0, 0, tzinfo=timezone.utc)


def _forecast(states):
    """states: list of (hour-offset-hours-from-oct12, deficit_state)."""
    base = datetime(2026, 10, 12, tzinfo=timezone.utc)
    return {"hourly": [
        {"hour": (base + timedelta(hours=h)).isoformat(), "deficit_state": s}
        for h, s in states
    ]}


from datetime import timedelta


class TestFindCrossing:
    def test_deficit_strictly_before_onset(self):
        forecast = _forecast([(20, "headroom"), (23, "deficit"), (25, "deficit")])
        crossing, soft = find_crossing(forecast, ONSET)
        assert crossing == (datetime(2026, 10, 12, 23, 0, tzinfo=timezone.utc)).isoformat()

    def test_lower_bound_is_soft_not_crossing(self):
        forecast = _forecast([(20, "lower_bound_demand"), (22, "headroom")])
        crossing, soft = find_crossing(forecast, ONSET)
        assert crossing is None
        assert len(soft) == 1

    def test_no_deficit_no_crossing(self):
        forecast = _forecast([(20, "headroom"), (22, "indeterminate")])
        crossing, _ = find_crossing(forecast, ONSET)
        assert crossing is None


class TestRiskDuringWindow:
    def test_deficit_at_onset_is_red(self):
        forecast = _forecast([(23, "headroom"), (24, "deficit"), (26, "deficit")])
        assert risk_during_window(forecast, ONSET) == "red"

    def test_all_headroom_is_green(self):
        forecast = _forecast([(24, "headroom"), (26, "headroom")])
        assert risk_during_window(forecast, ONSET) == "green"

    def test_lower_bound_is_amber(self):
        forecast = _forecast([(24, "lower_bound_demand")])
        assert risk_during_window(forecast, ONSET) == "amber"


class TestBuildRetrospective:
    def test_lead_time_computed(self):
        forecast = _forecast([(23, "deficit")])
        r = build_retrospective("incident", ONSET, forecast, ["approx"])
        assert r["incidents"][0]["lead_time_hours"] == 1.0
        assert r["incidents"][0]["forecast_crossing"]

    def test_no_crossing_means_no_lead_time(self):
        forecast = _forecast([(20, "headroom")])
        r = build_retrospective("incident", ONSET, forecast, [])
        assert r["incidents"][0]["lead_time_hours"] is None
        assert r["incidents"][0]["forecast_crossing"] is None


class TestSessionsInWindow:
    def test_filtering_and_shape(self):
        sessions = [
            {"session_date": "2026-10-13", "start_time": "09:00:00",
             "lab_code": "lab-a", "attendees": 10},
            {"session_date": "2026-11-01", "start_time": "09:00:00",
             "lab_code": "lab-b", "attendees": 5},
        ]
        start = datetime(2026, 10, 12, tzinfo=timezone.utc)
        end = datetime(2026, 10, 15, tzinfo=timezone.utc)
        rows = sessions_in_window(sessions, start, end)
        assert len(rows) == 1
        assert rows[0]["lab_code"] == "lab-a"
        assert rows[0]["attendees"] == 10
        assert rows[0]["start_time"].startswith("2026-10-13T09:00")
