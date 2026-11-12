"""Capacity forecast contract — capacity-forecast/v1.

One definition site for the capacity forecaster's output vocabulary,
following the contract semantics of contracts/outcome_contracts.py:

1. TRI-STATE EVIDENCE. Demand units and supply are observed values or
   None (unobserved). Unobserved is never coerced: an hour without
   observed demand or without supply evidence is INDETERMINATE, never a
   fabricated headroom.

2. LOWER BOUND IS A STATE, NOT A FOOTNOTE. When sessions without
   resource profiles contribute unquantified demand, observed demand is
   a floor; the hour's state says LOWER_BOUND_DEMAND instead of
   pretending to a precise comparison. (Catalog audit: ~28 percent of
   items carry parseable resource specs.)

3. GREEN IS EARNED. The risk rubric reports green only for fully
   observed demand under observed supply with zero fallback sessions.
   Deficit is red; anything partial is amber. This mirrors how the
   platform treats evidence everywhere: authority is earned by proof,
   and partial evidence never buys a clean bill.

4. ADVISORY BY DEFAULT. The contract ships with authority="advisory".
   Promotion to alerting authority is earned through the retrospective
   gate (documented capacity incidents flagged with lead time) and can
   decay — see docs/capacity-forecaster-plan.md.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional

CAPACITY_FORECAST_CONTRACT_VERSION = "capacity-forecast/v1"


class DeficitState(str, Enum):
    """Per-hour relationship between observed demand and supply."""
    DEFICIT = "deficit"                    # observed demand > observed supply
    HEADROOM = "headroom"                  # observed demand <= observed supply
    LOWER_BOUND_DEMAND = "lower_bound_demand"  # demand is a floor (fallback present)
    INDETERMINATE = "indeterminate"        # demand or supply unobserved


class ForecastRisk(str, Enum):
    """Fleet-level red/amber/green for the forecast window."""
    RED = "red"
    AMBER = "amber"
    GREEN = "green"


def _hour_state(vm_slots, supply_vm_slots, fallback_sessions) -> DeficitState:
    if vm_slots is None or supply_vm_slots is None:
        return DeficitState.INDETERMINATE
    if fallback_sessions:
        return DeficitState.LOWER_BOUND_DEMAND
    if vm_slots > supply_vm_slots:
        return DeficitState.DEFICIT
    return DeficitState.HEADROOM


def build_capacity_forecast(
    projection: Dict,
    supply_vm_slots: Optional[float] = None,
    window_hours: int = 72,
) -> Dict:
    """Assemble a capacity-forecast/v1 contract from a resource demand
    projection (engine.capacity_projector.project_resource_demand).

    Supply is optional evidence: per-cluster node supply wiring arrives
    with the API layer; until then hours without supply evidence resolve
    INDETERMINATE rather than guessing.
    """
    hourly = []
    for entry in (projection or {}).get("hourly", []):
        state = _hour_state(
            entry.get("vm_slots"),
            supply_vm_slots,
            entry.get("sessions_without_profiles") or 0,
        )
        hour = dict(entry)
        hour["deficit_state"] = state
        hour["supply_vm_slots"] = supply_vm_slots
        hourly.append(hour)

    states = [h["deficit_state"] for h in hourly]
    if DeficitState.DEFICIT in states:
        risk = ForecastRisk.RED
    elif states and all(s == DeficitState.HEADROOM for s in states) \
            and not (projection.get("coverage") or {}).get("sessions_fallback"):
        risk = ForecastRisk.GREEN
    else:
        risk = ForecastRisk.AMBER

    return {
        "contract": CAPACITY_FORECAST_CONTRACT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_hours": window_hours,
        "authority": "advisory",
        "hourly": hourly,
        "coverage": (projection or {}).get("coverage", {}),
        "risk": risk,
        "peak_hour": (projection or {}).get("peak_hour"),
    }
