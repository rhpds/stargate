"""MCP tool: get_capacity_forecast — the advisory forecast as an agent surface.

TDD: written before the tool exists. The tool must present the
capacity-forecast/v1 contract honestly: advisory authority, tri-state
coverage, lower-bound flagging, and the structural amber ceiling while
supply evidence is unwired.
"""

from datetime import datetime, timedelta, timezone

from engine.resource_profiles import ResourceProfile

NOW = datetime.now(timezone.utc)


def _session(lab, hours_from_now, attendees):
    start = (NOW + timedelta(hours=hours_from_now)).strftime("%Y-%m-%dT%H:%M:%S")
    return {"lab_code": lab, "attendees": attendees, "start_time": start}


class TestGetCapacityForecastTool:
    def _patch(self, monkeypatch, sessions, profiles):
        from api.routers import capacity
        monkeypatch.setattr(capacity, "_upcoming_sessions", lambda h: sessions)
        monkeypatch.setattr(capacity, "_resource_profiles", lambda: profiles)

    def test_summary_carries_contract_and_advisory(self, monkeypatch):
        from api import mcp_server
        self._patch(monkeypatch, [], {})
        result = mcp_server.get_capacity_forecast(hours=4)
        assert "capacity-forecast/v1" in result
        assert "advisory" in result

    def test_peak_demand_in_real_units(self, monkeypatch):
        from api import mcp_server
        self._patch(
            monkeypatch,
            [_session("lab-a", 1, 10), _session("lab-a", 3, 30)],
            {"lab-a": ResourceProfile("lab-a", 3, 8.0, 32.0, "observed", "s")},
        )
        result = mcp_server.get_capacity_forecast(hours=6)
        assert "90 VM slots" in result  # 30 attendees x 3 workers
        assert "240.0 AI cores" in result  # 30 x 8

    def test_fallback_sessions_flag_lower_bound(self, monkeypatch):
        from api import mcp_server
        self._patch(monkeypatch, [_session("lab-x", 1, 40)], {})
        result = mcp_server.get_capacity_forecast(hours=4)
        assert "lower bound" in result.lower()
        assert "1" in result  # one unprofiled session counted

    def test_supply_honesty_stated(self, monkeypatch):
        """The tool says why risk cannot be green — supply unwired."""
        from api import mcp_server
        self._patch(monkeypatch, [_session("lab-a", 1, 10)],
                    {"lab-a": ResourceProfile("lab-a", 3, None, None, "observed", "s")})
        result = mcp_server.get_capacity_forecast(hours=4)
        assert "amber" in result
        assert "supply" in result.lower()

    def test_no_sessions_is_explicit(self, monkeypatch):
        from api import mcp_server
        self._patch(monkeypatch, [], {})
        result = mcp_server.get_capacity_forecast(hours=4)
        assert "No sessions" in result


class TestGetCapacityForecastWithSupply:
    def _patch(self, monkeypatch, sessions, profiles):
        from api.routers import capacity
        monkeypatch.setattr(capacity, "_upcoming_sessions", lambda h: sessions)
        monkeypatch.setattr(capacity, "_resource_profiles", lambda: profiles)

    def test_supply_present_when_observed(self, monkeypatch):
        from api import mcp_server
        self._patch(monkeypatch, [_session("lab-a", 1, 100)],
                    {"lab-a": ResourceProfile("lab-a", 3, None, None, "observed", "s")})
        from api.routers import capacity
        monkeypatch.setattr(capacity, "fleet_supply_vm_slots",
                            lambda window_hours=48: {"vm_slots": 100, "basis": "observed_peak_density", "window_hours": 48})
        result = mcp_server.get_capacity_forecast(hours=4)
        assert "Supply: 100 VM slots" in result
        assert result.splitlines()[1] == "Risk: red"  # 300 demand > 100 supply

    def test_no_supply_keeps_honesty_line(self, monkeypatch):
        from api import mcp_server
        self._patch(monkeypatch, [], {})
        from api.routers import capacity
        monkeypatch.setattr(capacity, "fleet_supply_vm_slots", lambda window_hours=48: None)
        result = mcp_server.get_capacity_forecast(hours=4)
        assert "Supply evidence is not yet wired" in result


class TestGetEventForecastTool:
    def test_event_summary_with_bounds(self, monkeypatch):
        from api import mcp_server
        monkeypatch.setattr(
            "collectors.labagator.collect_labagator.collect_sessions",
            lambda event_id=None, limit=500: [
                {"event_id": 32, "session_date": "2027-01-20",
                 "start_time": "09:00:00", "end_time": "12:00:00",
                 "attendees": 120, "lab_code": "LB1"}],
            raising=False)
        monkeypatch.setattr(
            "collectors.labagator.collect_labagator.collect_events",
            lambda base_url="", event_id=None: [
                {"id": 32, "name": "Red Hat One 2027"}],
            raising=False)
        result = mcp_server.get_event_forecast(days=90)
        assert "Red Hat One 2027" in result
        assert "peak concurrent 120" in result
        assert "bounded" in result.lower() or "Bounds" in result

    def test_no_events_is_explicit(self, monkeypatch):
        from api import mcp_server
        monkeypatch.setattr(
            "collectors.labagator.collect_labagator.collect_sessions",
            lambda event_id=None, limit=500: [], raising=False)
        monkeypatch.setattr(
            "collectors.labagator.collect_labagator.collect_events",
            lambda base_url="", event_id=None: [], raising=False)
        result = mcp_server.get_event_forecast(days=30)
        assert "No scheduled events" in result
