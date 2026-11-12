"""Capacity forecast contract — capacity-forecast/v1.

TDD: written before contracts/capacity_forecast.py exists. Pins the
contract semantics for forecast outputs, following the house pattern
from outcome_contracts.py: tri-state evidence, explicit states, failure
precedence, and no fabricated values. The forecast that earns dashboard
authority must emit this contract — nothing else.
"""

from datetime import datetime, timedelta, timezone

from contracts.capacity_forecast import (
    CAPACITY_FORECAST_CONTRACT_VERSION,
    DeficitState,
    ForecastRisk,
    build_capacity_forecast,
)

NOW = datetime.now(timezone.utc)


def _projection(vm_slots=30, fallback=0, sessions=1):
    """A minimal project_resource_demand-shaped result."""
    return {
        "hourly": [{
            "hour": (NOW + timedelta(hours=1)).strftime("%Y-%m-%dT%H:00"),
            "sessions": sessions,
            "vm_slots": vm_slots,
            "ai_cores": None,
            "ai_memory_gib": None,
            "sessions_without_profiles": fallback,
            "demand_citations": [],
        }],
        "coverage": {
            "sessions_total": sessions,
            "sessions_with_profiles": sessions - fallback,
            "sessions_fallback": fallback,
            "lower_bound": fallback > 0,
        },
        "peak_hour": None,
    }


class TestContractIdentity:
    def test_version_constant(self):
        assert CAPACITY_FORECAST_CONTRACT_VERSION == "capacity-forecast/v1"

    def test_contract_carries_version_and_window(self):
        fc = build_capacity_forecast(_projection(), window_hours=72)
        assert fc["contract"] == "capacity-forecast/v1"
        assert fc["window_hours"] == 72
        assert fc["generated_at"]
        assert fc["authority"] == "advisory"  # earns promotion, never starts there


class TestDeficitStates:
    def test_observed_deficit(self):
        """Demand above observed supply is a DEFICIT — stated, not hidden."""
        fc = build_capacity_forecast(_projection(vm_slots=30), supply_vm_slots=20)
        assert fc["hourly"][0]["deficit_state"] == DeficitState.DEFICIT

    def test_observed_headroom(self):
        fc = build_capacity_forecast(_projection(vm_slots=10), supply_vm_slots=20)
        assert fc["hourly"][0]["deficit_state"] == DeficitState.HEADROOM

    def test_unobserved_supply_is_indeterminate(self):
        """No supply evidence → INDETERMINATE, never a fabricated green."""
        fc = build_capacity_forecast(_projection(vm_slots=30), supply_vm_slots=None)
        assert fc["hourly"][0]["deficit_state"] == DeficitState.INDETERMINATE

    def test_unobserved_demand_is_indeterminate(self):
        """An hour with no observed demand units cannot claim headroom."""
        fc = build_capacity_forecast(_projection(vm_slots=None), supply_vm_slots=20)
        assert fc["hourly"][0]["deficit_state"] == DeficitState.INDETERMINATE

    def test_lower_bound_demand_is_flagged(self):
        """Fallback sessions present → demand is a floor; the state says
        so instead of pretending to a precise comparison."""
        fc = build_capacity_forecast(
            _projection(vm_slots=10, fallback=2, sessions=3), supply_vm_slots=20)
        assert fc["hourly"][0]["deficit_state"] == DeficitState.LOWER_BOUND_DEMAND


class TestRiskRubric:
    def test_red_on_observed_deficit(self):
        fc = build_capacity_forecast(_projection(vm_slots=30), supply_vm_slots=20)
        assert fc["risk"] == ForecastRisk.RED

    def test_amber_on_lower_bound(self):
        fc = build_capacity_forecast(
            _projection(vm_slots=10, fallback=1, sessions=2), supply_vm_slots=20)
        assert fc["risk"] == ForecastRisk.AMBER

    def test_amber_when_indeterminate(self):
        fc = build_capacity_forecast(_projection(vm_slots=30), supply_vm_slots=None)
        assert fc["risk"] == ForecastRisk.AMBER

    def test_green_requires_full_observation_and_headroom(self):
        """Green is earned: observed demand under observed supply with
        zero fallback sessions. Anything less is amber at best."""
        fc = build_capacity_forecast(_projection(vm_slots=10), supply_vm_slots=20)
        assert fc["risk"] == ForecastRisk.GREEN

    def test_risk_cannot_be_green_with_fallback_sessions(self):
        fc = build_capacity_forecast(
            _projection(vm_slots=10, fallback=1, sessions=2), supply_vm_slots=100)
        assert fc["risk"] != ForecastRisk.GREEN


class TestEvidenceSemantics:
    def test_coverage_passes_through(self):
        fc = build_capacity_forecast(_projection(fallback=1, sessions=2))
        assert fc["coverage"]["sessions_fallback"] == 1
        assert fc["coverage"]["lower_bound"] is True

    def test_demand_citations_preserved(self):
        """EDD: the contract carries the projection's citations."""
        proj = _projection()
        proj["hourly"][0]["demand_citations"] = [
            {"lab": "lab-a", "attendees": 10, "vm_slots": 30}]
        fc = build_capacity_forecast(proj)
        assert fc["hourly"][0]["demand_citations"][0]["lab"] == "lab-a"


class TestEmptyHourSemantics:
    def test_empty_hour_is_observed_zero_demand(self):
        """An hour with no scheduled sessions is OBSERVED zero demand —
        headroom when supply is observed — not missing evidence. Without
        this, green is unreachable (empty night hours read indeterminate)."""
        proj = _projection()
        proj["hourly"][0]["vm_slots"] = None
        proj["hourly"][0]["sessions"] = 0
        fc = build_capacity_forecast(proj, supply_vm_slots=20)
        assert fc["hourly"][0]["deficit_state"] == DeficitState.HEADROOM

    def test_sessions_without_units_stay_indeterminate(self):
        """Sessions present but no profiled units — that is the true
        unobserved case."""
        proj = _projection()
        proj["hourly"][0]["vm_slots"] = None
        proj["hourly"][0]["sessions"] = 3
        fc = build_capacity_forecast(proj, supply_vm_slots=20)
        assert fc["hourly"][0]["deficit_state"] == DeficitState.INDETERMINATE
