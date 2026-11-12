#!/usr/bin/env python
"""Retrospective forecast harness — B+C tracks of the authority gate.

Reconstructs a historical window: pulls the sessions Labagator
actually scheduled, joins them with catalog resource profiles,
projects demand against the observed-peak supply ceiling, and asks
the question the gate needs answered: would the forecast have
crossed supply BEFORE the documented incident onset — with how much
lead time?

Stated approximations (carried into the gate result):
- resource profiles are CURRENT AgnosticV state as a historical proxy
- the supply ceiling is the CURRENT 48h observed peak density as a
  proxy for the window's (scan history does not reach back to October
  until the revived scan_snapshots accumulates)

Run inside the API pod (Labagator is cluster-internal):
  python3 scripts/forecast_retrospective.py \
    --start 2026-10-12 --end 2026-10-15 \
    --name ocpv_saturation --onset 2026-10-13T00:00:00+00:00 \
    --evaluate
"""

import argparse
import json
from datetime import datetime, timedelta, timezone


def sessions_in_window(sessions, start, end):
    """Loader-shaped sessions -> projector shape, filtered to window."""
    out = []
    for s in sessions or []:
        sd, st = s.get("session_date"), s.get("start_time")
        if not sd or not st:
            continue
        try:
            dt = datetime.fromisoformat(f"{sd}T{st}")
        except (ValueError, TypeError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if start <= dt < end:
            out.append({
                "lab_code": s.get("lab_code"),
                "attendees": s.get("attendees") or 0,
                "start_time": dt.isoformat(),
            })
    return out


def find_crossing(forecast, onset):
    """First hard DEFICIT hour strictly before the documented onset.

    LOWER_BOUND_DEMAND hours are soft signals (demand is a floor, the
    comparison imprecise) — reported separately, never counted as the
    crossing. The crossing is the hour where observed demand exceeded
    observed supply.
    """
    crossing = None
    soft_signals = []
    for hour in forecast.get("hourly", []):
        label = hour.get("hour", "")
        try:
            hour_dt = datetime.fromisoformat(label)
        except (ValueError, TypeError):
            continue
        if hour_dt.tzinfo is None:
            # the projector's hour labels are wall-clock without offset
            hour_dt = hour_dt.replace(tzinfo=timezone.utc)
        if hour_dt >= onset:
            break
        if hour.get("deficit_state") == "deficit" and crossing is None:
            crossing = label
        elif hour.get("deficit_state") == "lower_bound_demand":
            soft_signals.append(label)
    return crossing, soft_signals


def risk_during_window(forecast, onset, hours=6):
    """The contract's risk in the hours around the documented onset."""
    states = []
    for hour in forecast.get("hourly", []):
        try:
            hour_dt = datetime.fromisoformat(hour.get("hour", ""))
        except (ValueError, TypeError):
            continue
        if hour_dt.tzinfo is None:
            hour_dt = hour_dt.replace(tzinfo=timezone.utc)
        if onset <= hour_dt < onset + timedelta(hours=hours):
            states.append(hour.get("deficit_state"))
    if not states:
        return "unknown"
    if "deficit" in states:
        return "red"
    if "lower_bound_demand" in states:
        return "amber"
    if all(s == "headroom" for s in states):
        return "green"
    return "unknown"


def build_retrospective(name, onset, forecast, approximations):
    crossing, soft = find_crossing(forecast, onset)
    lead_time_hours = None
    if crossing:
        lead_time_hours = round(
            (onset - datetime.fromisoformat(crossing)).total_seconds() / 3600, 2)
    return {
        "incidents": [{
            "name": name,
            "documented_onset": onset.isoformat(),
            "forecast_crossing": crossing,
            "soft_signals": soft,
            "lead_time_hours": lead_time_hours,
            "forecast_risk_during_window": risk_during_window(forecast, onset),
        }],
        "approximations": approximations,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="window start date YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="window end date (exclusive)")
    ap.add_argument("--name", required=True, help="incident name")
    ap.add_argument("--onset", required=True, help="documented onset ISO datetime")
    ap.add_argument("--evaluate", action="store_true",
                    help="run the authority gate on the result")
    args = ap.parse_args()

    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)
    onset = datetime.fromisoformat(args.onset.replace("Z", "+00:00"))
    if onset.tzinfo is None:
        onset = onset.replace(tzinfo=timezone.utc)
    hours = int((end - start).total_seconds() / 3600)

    from api.routers.capacity import (
        _resolve_agnosticv_dir,
        fleet_supply_vm_slots,
    )
    from collectors.labagator.collect_labagator import collect_sessions
    from constraints.agnosticv_loader import load_all_constraints
    from contracts.capacity_forecast import build_capacity_forecast
    from engine.capacity_projector import project_resource_demand
    from engine.resource_profiles import build_resource_profiles

    sessions = sessions_in_window(collect_sessions(), start, end)
    print("sessions in window: %d" % len(sessions))

    agnosticv_dir = _resolve_agnosticv_dir()
    profiles = build_resource_profiles(
        load_all_constraints(agnosticv_dir)) if agnosticv_dir else {}
    print("profiles: %d (agnosticv dir: %s)" % (len(profiles), agnosticv_dir))

    projection = project_resource_demand(
        sessions, profiles, hours=hours, start=start)
    supply = fleet_supply_vm_slots(window_hours=48)
    forecast = build_capacity_forecast(
        projection,
        supply_vm_slots=(supply or {}).get("vm_slots"),
        window_hours=hours)

    approximations = [
        "resource profiles are current AgnosticV state as historical proxy",
        "supply ceiling is the current 48h observed peak density as proxy",
    ]
    retrospective = build_retrospective(args.name, onset, forecast, approximations)
    print(json.dumps(retrospective, indent=2))

    if args.evaluate:
        from engine.forecast_gate import evaluate_forecast_gate
        print(json.dumps(evaluate_forecast_gate(retrospective), indent=2))


if __name__ == "__main__":
    main()
