"""Advisory resource forecast endpoint — /api/v1/resource-forecast.

TDD: written before the endpoint exists. Pins the wiring contract:
Labagator sessions × resource profiles → project_resource_demand →
capacity-forecast/v1, advisory authority, honest coverage. The network
and filesystem sources are monkeypatched — the suite's effects guard
blocks real collection.
"""

from datetime import datetime, timedelta, timezone

from engine.resource_profiles import ResourceProfile

NOW = datetime.now(timezone.utc)


def _session(lab, hours_from_now, attendees):
    start = (NOW + timedelta(hours=hours_from_now)).strftime("%Y-%m-%dT%H:%M:%S")
    return {"lab_code": lab, "attendees": attendees, "start_time": start}


class TestResourceForecastEndpoint:
    def test_returns_the_contract(self, client, monkeypatch):
        from api.routers import capacity
        monkeypatch.setattr(capacity, "_upcoming_sessions", lambda h: [])
        monkeypatch.setattr(capacity, "_resource_profiles", lambda: {})
        monkeypatch.setattr(capacity, "fleet_supply_vm_slots", lambda window_hours=48: None)

        resp = client.get("/api/v1/resource-forecast")
        assert resp.status_code == 200
        body = resp.json()
        assert body["contract"] == "capacity-forecast/v1"
        assert body["authority"] == "advisory"
        assert body["window_hours"] == 24

    def test_demand_from_sessions_times_profiles(self, client, monkeypatch):
        from api.routers import capacity
        monkeypatch.setattr(capacity, "_upcoming_sessions",
                            lambda h: [_session("lab-a", 1, 10)])
        monkeypatch.setattr(capacity, "_resource_profiles", lambda: {
            "lab-a": ResourceProfile("lab-a", 3, 8.0, 32.0, "observed", "s")})
        monkeypatch.setattr(capacity, "fleet_supply_vm_slots", lambda window_hours=48: None)

        body = client.get("/api/v1/resource-forecast").json()
        assert body["coverage"]["sessions_total"] == 1
        assert body["peak_hour"]["vm_slots"] == 30
        # no supply evidence wired yet -> indeterminate, amber, never green
        assert body["risk"] == "amber"

    def test_unprofiled_sessions_lower_bound(self, client, monkeypatch):
        from api.routers import capacity
        monkeypatch.setattr(capacity, "_upcoming_sessions",
                            lambda h: [_session("lab-x", 1, 40)])
        monkeypatch.setattr(capacity, "_resource_profiles", lambda: {})
        monkeypatch.setattr(capacity, "fleet_supply_vm_slots", lambda window_hours=48: None)

        body = client.get("/api/v1/resource-forecast").json()
        assert body["coverage"]["sessions_fallback"] == 1
        assert body["coverage"]["lower_bound"] is True
        assert body["risk"] == "amber"

    def test_no_sessions_is_amber_not_green(self, client, monkeypatch):
        """An empty schedule is unobserved demand — INDETERMINATE, never
        a clean bill of health."""
        from api.routers import capacity
        monkeypatch.setattr(capacity, "_upcoming_sessions", lambda h: [])
        monkeypatch.setattr(capacity, "_resource_profiles", lambda: {})
        monkeypatch.setattr(capacity, "fleet_supply_vm_slots", lambda window_hours=48: None)

        body = client.get("/api/v1/resource-forecast").json()
        assert body["risk"] == "amber"
        assert body["coverage"]["sessions_total"] == 0

    def test_window_parameter(self, client, monkeypatch):
        from api.routers import capacity
        monkeypatch.setattr(capacity, "_upcoming_sessions", lambda h: [])
        monkeypatch.setattr(capacity, "_resource_profiles", lambda: {})

        body = client.get("/api/v1/resource-forecast?hours=48").json()
        assert body["window_hours"] == 48
        assert len(body["hourly"]) == 48


class TestResourceForecastWithSupply:
    def test_deficit_when_demand_exceeds_observed_supply(self, client, monkeypatch):
        """With fleet supply wired, observed demand above the observed
        ceiling is a RED forecast — the rubric finally has teeth."""
        from api.routers import capacity
        monkeypatch.setattr(capacity, "_upcoming_sessions",
                            lambda h: [_session("lab-a", 1, 100)])
        monkeypatch.setattr(capacity, "_resource_profiles", lambda: {
            "lab-a": ResourceProfile("lab-a", 3, None, None, "observed", "s")})
        monkeypatch.setattr(capacity, "fleet_supply_vm_slots",
                            lambda window_hours=48: {"vm_slots": 100, "basis": "observed_peak_density"})

        body = client.get("/api/v1/resource-forecast").json()
        assert body["risk"] == "red"
        assert body["supply"]["vm_slots"] == 100

    def test_headroom_green_when_fully_observed(self, client, monkeypatch):
        from api.routers import capacity
        monkeypatch.setattr(capacity, "_upcoming_sessions",
                            lambda h: [_session("lab-a", 1, 10)])
        monkeypatch.setattr(capacity, "_resource_profiles", lambda: {
            "lab-a": ResourceProfile("lab-a", 3, None, None, "observed", "s")})
        monkeypatch.setattr(capacity, "fleet_supply_vm_slots",
                            lambda window_hours=48: {"vm_slots": 1000, "basis": "observed_peak_density"})

        body = client.get("/api/v1/resource-forecast").json()
        assert body["risk"] == "green"
        assert body["hourly"][1]["deficit_state"] == "headroom"
