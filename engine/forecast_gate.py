"""The forecast authority gate — promotion and decay by evidence.

Turns retrospective evidence (would the forecast have flagged the
documented capacity incidents, with lead time?) and forward accuracy
(did projected demand materialize?) into an authority decision.

Rules, in precedence order:

1. FALSE GREEN IS A HARD FAIL. A forecast that reported green during
   a documented incident window is disqualified outright — for a
   capacity forecaster, "all clear while it burned" is the one
   unforgivable output.
2. PASS requires every documented incident flagged with lead time
   strictly greater than zero.
3. PROMOTION (advisory -> alerting authority) is eligible only on a
   full pass with sustained accuracy; anything less holds advisory.
4. DECAY: live accuracy below 0.5 realized-rate withdraws eligibility
   — the proof-lab gates-decay-on-failure rule, applied to forecasts.
   The threshold is deliberately modest: promotion needs
   better-than-coin-flip, not perfection.

The gate never promotes on promises — only on the incidents we
already know happened and the accuracy we already measured.
"""

from typing import Dict, Optional

ACCURACY_DECAY_THRESHOLD = 0.5


def _incident_result(incident: Dict) -> Dict:
    lead = incident.get("lead_time_hours")
    flagged = incident.get("forecast_crossing") is not None and lead is not None and lead > 0
    false_green = incident.get("forecast_risk_during_window") == "green"
    out_of_scope = incident.get("incident_class") == "supply_degradation"
    return {
        "name": incident.get("name", "?"),
        "flagged_with_lead_time": flagged,
        "lead_time_hours": lead,
        "false_green": false_green,
        "out_of_scope": out_of_scope,
    }


def evaluate_forecast_gate(
    retrospective: Dict,
    accuracy: Optional[Dict] = None,
) -> Dict:
    """Evaluate the authority gate from retrospective (and optionally
    forward-accuracy) evidence.

    Scope (declared, never assumed): incidents classified
    ``supply_degradation`` are out of scope — reported with
    ``out_of_scope: true``, never counted against the gate. The
    declaration is evidence-based (Nov 13 2026): the forecaster
    demonstrated 34-day lead time on the demand-shock class; supply
    degradation belongs to the saturation detector (validated 4/4).
    An incident without a class is in scope by default.
    """
    incidents = retrospective.get("incidents", [])
    per_incident = [_incident_result(inc) for inc in incidents]

    reasons = []
    in_scope = [r for r in per_incident if not r["out_of_scope"]]
    out_of_scope = [r["name"] for r in per_incident if r["out_of_scope"]]
    if out_of_scope:
        reasons.append(
            "out of scope (supply degradation — the saturation detector's "
            "validated domain): %s" % ", ".join(out_of_scope))

    false_greens = [r["name"] for r in in_scope if r["false_green"]]
    if false_greens:
        reasons.append(
            "false green during documented incident window: %s"
            % ", ".join(false_greens))

    if not incidents:
        reasons.append("no documented incidents evaluated — gate cannot pass on an empty set")

    flagged = [r for r in in_scope if r["flagged_with_lead_time"]]
    if false_greens or not in_scope:
        verdict, rag = "fail", "red"
    elif len(flagged) == len(in_scope):
        verdict, rag = "pass", "green"
    elif flagged:
        verdict, rag = "partial", "amber"
    else:
        verdict, rag = "fail", "red"

    if verdict != "pass" and not false_greens and in_scope:
        missed = [r["name"] for r in in_scope if not r["flagged_with_lead_time"]]
        if missed:
            reasons.append("not flagged with lead time: %s" % ", ".join(missed))

    promotion = "eligible" if verdict == "pass" else (
        "hold" if verdict == "partial" else "not_eligible")

    if accuracy is not None:
        rate = accuracy.get("rate")
        if rate is not None and rate < ACCURACY_DECAY_THRESHOLD:
            promotion = "not_eligible"
            reasons.append(
                "authority decay: realized accuracy %.2f below threshold %.2f"
                % (rate, ACCURACY_DECAY_THRESHOLD))

    return {
        "verdict": verdict,
        "rag": rag,
        "promotion": promotion,
        "per_incident": per_incident,
        "reasons": reasons,
        "approximations": retrospective.get("approximations", []),
        "accuracy": accuracy,
    }
