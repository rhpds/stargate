"""TDD tests — Capacity projector: demand/supply projection and risk detection."""

from datetime import datetime, timedelta, timezone


class TestCapacityProjector:
    def test_function_exists(self):
        from engine.capacity_projector import project_capacity
        assert callable(project_capacity)

    def test_empty_inputs(self):
        from engine.capacity_projector import project_capacity
        result = project_capacity(sessions=[], pools={}, complexities={}, pool_velocities={}, hours=3)
        assert result["risk_level"] == "low"
        assert len(result["hourly_projections"]) == 3
        assert result["bottleneck_pools"] == []

    def test_simple_session_creates_demand(self):
        from engine.capacity_projector import project_capacity
        now = datetime.now(timezone.utc)
        sessions = [{
            "lab_code": "LB0001",
            "start_time": (now + timedelta(minutes=30)).isoformat(),
            "attendees": 50,
            "pool_name": "pool-a",
        }]
        pools = {"pool-a": {"available": 100, "min_required": 10}}
        result = project_capacity(sessions, pools, {}, {}, hours=2)
        assert result["hourly_projections"][0]["sessions_starting"] == 1
        assert result["total_demand"] > 0

    def test_overloaded_pool_detected(self):
        from engine.capacity_projector import project_capacity
        now = datetime.now(timezone.utc)
        sessions = [
            {"lab_code": f"LB{i}", "start_time": (now + timedelta(minutes=10)).isoformat(),
             "attendees": 100, "pool_name": "small-pool"}
            for i in range(5)
        ]
        pools = {"small-pool": {"available": 2, "min_required": 5}}
        complexities = {f"LB{i}": {"score": 0.8} for i in range(5)}
        result = project_capacity(sessions, pools, complexities, {}, hours=2)
        assert "small-pool" in result["bottleneck_pools"]
        assert result["risk_level"] in ("high", "critical")

    def test_recovering_pool_ok(self):
        from engine.capacity_projector import project_capacity
        now = datetime.now(timezone.utc)
        sessions = [{
            "lab_code": "LB0001",
            "start_time": (now + timedelta(hours=4)).isoformat(),
            "attendees": 10,
            "pool_name": "pool-b",
        }]
        pools = {"pool-b": {"available": 20, "min_required": 5}}
        velocities = {"pool-b": {"handles_per_hour": 2.0, "recycling_rate": 1.0}}
        result = project_capacity(sessions, pools, {}, velocities, hours=6)
        assert result["risk_level"] == "low"

    def test_high_complexity_increases_demand(self):
        from engine.capacity_projector import project_capacity
        now = datetime.now(timezone.utc)
        session = {
            "lab_code": "LB_AI",
            "start_time": (now + timedelta(minutes=20)).isoformat(),
            "attendees": 30,
            "pool_name": "pool-c",
        }
        pools = {"pool-c": {"available": 50}}

        result_low = project_capacity([session], pools, {"LB_AI": {"score": 0.1}}, {}, hours=1)
        result_high = project_capacity([session], pools, {"LB_AI": {"score": 0.9}}, {}, hours=1)
        demand_low = result_low["total_demand"]
        demand_high = result_high["total_demand"]
        assert demand_high > demand_low


class TestProjectionStructure:
    def test_hourly_has_required_fields(self):
        from engine.capacity_projector import project_capacity
        result = project_capacity([], {}, {}, {}, hours=2)
        for entry in result["hourly_projections"]:
            assert "hour" in entry
            assert "sessions_starting" in entry
            assert "demand_by_pool" in entry
            assert "supply_by_pool" in entry

    def test_result_has_required_fields(self):
        from engine.capacity_projector import project_capacity
        result = project_capacity([], {}, {}, {}, hours=1)
        assert "hourly_projections" in result
        assert "bottleneck_pools" in result
        assert "risk_level" in result
        assert "total_demand" in result
        assert "total_supply" in result
