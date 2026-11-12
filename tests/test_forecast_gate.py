"""The forecast authority gate — promotion and decay by evidence.

TDD: written before engine/forecast_gate.py exists. Pins the rules
that turn retrospective evidence into an authority decision:

- PASS requires every documented incident flagged with lead time > 0
- a false green (forecast said all-clear during an incident window) is
  a hard fail — the one unforgivable output for a capacity forecaster
- promotion is eligible only on pass; anything less holds advisory
- authority decays on live-accuracy degradation (the proof-lab rule)
"""

from engine.forecast_gate import evaluate_forecast_gate


def _retrospective(**overrides):
    base = {
        "incidents": [
            {
                "name": "ocpv_saturation",
                "documented_onset": "2026-10-13T06:00:00+00:00",
                "forecast_crossing": "2026-10-13T01:00:00+00:00",
                "lead_time_hours": 5.0,
                "forecast_risk_during_window": "red",
            },
            {
                "name": "event_pool_exhaustion",
                "documented_onset": "2026-10-01T12:00:00+00:00",
                "forecast_crossing": "2026-09-30T20:00:00+00:00",
                "lead_time_hours": 16.0,
                "forecast_risk_during_window": "red",
            },
        ],
        "approximations": ["current AgnosticV profiles as historical proxy"],
    }
    base.update(overrides)
    return base


class TestGateEvaluation:
    def test_pass_when_all_incidents_flagged_with_lead_time(self):
        result = evaluate_forecast_gate(_retrospective())
        assert result["verdict"] == "pass"
        assert result["rag"] == "green"
        assert result["promotion"] == "eligible"

    def test_partial_when_one_incident_missed(self):
        retros = _retrospective()
        retros["incidents"][1]["forecast_crossing"] = None
        retros["incidents"][1]["lead_time_hours"] = None
        result = evaluate_forecast_gate(retros)
        assert result["verdict"] == "partial"
        assert result["rag"] == "amber"
        assert result["promotion"] == "hold"

    def test_fail_when_nothing_flagged(self):
        retros = _retrospective()
        for inc in retros["incidents"]:
            inc["forecast_crossing"] = None
            inc["lead_time_hours"] = None
        result = evaluate_forecast_gate(retros)
        assert result["verdict"] == "fail"
        assert result["rag"] == "red"
        assert result["promotion"] == "not_eligible"

    def test_false_green_is_a_hard_fail(self):
        """A forecast that said green during a documented incident
        window is disqualified outright — the one unforgivable output."""
        retros = _retrospective()
        retros["incidents"][0]["forecast_risk_during_window"] = "green"
        result = evaluate_forecast_gate(retros)
        assert result["verdict"] == "fail"
        assert result["rag"] == "red"
        assert result["promotion"] == "not_eligible"
        assert any("false green" in r.lower() for r in result["reasons"])

    def test_zero_lead_time_does_not_pass(self):
        retros = _retrospective()
        retros["incidents"][0]["lead_time_hours"] = 0.0
        result = evaluate_forecast_gate(retros)
        assert result["verdict"] == "partial"

    def test_decay_on_accuracy_degradation(self):
        """Authority decays when live accuracy drops below threshold —
        the proof-lab gates-decay-on-failure rule applied to forecasts."""
        result = evaluate_forecast_gate(
            _retrospective(), accuracy={"rate": 0.41, "n": 40})
        assert result["promotion"] == "not_eligible"
        assert any("decay" in r.lower() for r in result["reasons"])

    def test_high_accuracy_sustains(self):
        result = evaluate_forecast_gate(
            _retrospective(), accuracy={"rate": 0.9, "n": 40})
        assert result["promotion"] == "eligible"

    def test_reasons_are_stated(self):
        result = evaluate_forecast_gate(_retrospective())
        assert result["approximations"] == ["current AgnosticV profiles as historical proxy"]


class TestGateDecayBoundary:
    def test_accuracy_threshold_is_half(self):
        """Below 0.5 realized-accuracy the gate cannot hold authority;
        the threshold is deliberately modest — advisory promotion needs
        better-than-coin-flip, not perfection."""
        assert evaluate_forecast_gate(
            _retrospective(), accuracy={"rate": 0.49, "n": 40})["promotion"] == "not_eligible"
        assert evaluate_forecast_gate(
            _retrospective(), accuracy={"rate": 0.51, "n": 40})["promotion"] == "eligible"


class TestScopeDeclaration:
    """The scope declaration (Nov 13 2026, evidence-based): the forecaster
    earns demand-shock authority (34-day lead time demonstrated on the
    event-pool class); supply-degradation belongs to the saturation
    detector (validated 4/4). Incidents classified supply_degradation are
    explicitly out of scope — reported, never counted against the gate."""

    def _scoped(self):
        return {
            "incidents": [
                {"name": "event_pool_exhaustion", "incident_class": "demand_shock",
                 "documented_onset": "2026-09-30T15:30:00+00:00",
                 "forecast_crossing": "2026-08-27T14:51:31+00:00",
                 "lead_time_hours": 816.6, "forecast_risk_during_window": "red"},
                {"name": "ocpv_saturation", "incident_class": "supply_degradation",
                 "documented_onset": "2026-10-14T00:00:00+00:00",
                 "forecast_crossing": None, "lead_time_hours": None,
                 "forecast_risk_during_window": "green"},
            ],
            "approximations": [],
        }

    def test_out_of_scope_incident_does_not_fail_the_gate(self):
        result = evaluate_forecast_gate(self._scoped())
        assert result["verdict"] == "pass"
        assert result["promotion"] == "eligible"
        # the out-of-scope incident is reported, not counted
        oos = [i for i in result["per_incident"] if i["name"] == "ocpv_saturation"][0]
        assert oos.get("out_of_scope") is True

    def test_scope_must_be_declared_not_assumed(self):
        """An incident without a class is in scope by default — scope is
        an explicit declaration carried by the evidence, not a default
        exclusion."""
        retros = self._scoped()
        retros["incidents"][1]["incident_class"] = None
        result = evaluate_forecast_gate(retros)
        assert result["verdict"] == "fail"  # the false green counts again

    def test_in_scope_miss_still_fails(self):
        retros = self._scoped()
        retros["incidents"][0]["lead_time_hours"] = None
        retros["incidents"][0]["forecast_crossing"] = None
        result = evaluate_forecast_gate(retros)
        assert result["verdict"] == "fail"

    def test_out_of_scope_false_green_is_noted_not_fatal(self):
        """A green forecast during an out-of-scope (supply-degradation)
        window is the declared limitation, recorded as a note — not the
        hard-fail it rightly is for in-scope incidents."""
        result = evaluate_forecast_gate(self._scoped())
        assert result["rag"] == "green"
        assert any("out of scope" in r.lower() for r in result["reasons"])
