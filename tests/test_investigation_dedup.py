"""Tests for investigation dedup against known diagnoses.

When a COMPLETE investigation with an ACTIONABLE diagnosis already exists
for the same lab+failure_class within the known-diagnosis window (24h
default), new triggers must NOT create a duplicate investigation — they
attach a recurrence to the existing one instead. TRANSIENT diagnoses never
suppress re-investigation.
"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

NOW = datetime.now(timezone.utc)

# Baselines that classify a failing namespace as anomalous (rate < 5% of a
# catalog with > 50 evals), the same patching approach as
# tests/test_attention_classifier.py.
ANOMALOUS_BASELINES = {
    "ocp4": {
        "total_evals": 100,
        "namespace_count": 10,
        "failure_profiles": {
            "pods_crashlooping": {"rate": 0.01, "count": 1, "p95_ttr_minutes": None},
        },
    }
}

LAB = "sandbox-ab12c-ocp4"


def _seed_complete(
    db,
    job_id,
    lab_code=LAB,
    cluster="east",
    failure_class="pods_crashlooping",
    verdict="ACTIONABLE",
    root_cause="image pull failure",
    age_hours=8.0,
):
    """Seed a COMPLETE investigation at a controlled age (default 8h: outside
    the 4h namespace dedup, inside the 24h known-diagnosis window)."""
    from db.models import InvestigationRecord

    created_at = NOW - timedelta(hours=age_hours)
    inv = InvestigationRecord(
        job_id=job_id,
        lab_code=lab_code,
        namespace=lab_code,
        cluster=cluster,
        failure_class=failure_class,
        trigger_type="auto",
        status="complete",
        analysis=f"analysis for {job_id}",
        root_cause=root_cause,
        trust_dimensions={"verdict": verdict, "confidence": 85},
        created_at=created_at,
        completed_at=created_at + timedelta(minutes=10),
    )
    db.add(inv)
    db.commit()
    return inv


class TestGetRecentCompleteInvestigation:
    def test_returns_actionable_even_when_transient_is_newer(self, db):
        from db.repository import get_recent_complete_investigation

        actionable = _seed_complete(db, "inv-known01", verdict="ACTIONABLE", age_hours=8)
        _seed_complete(db, "inv-known02", verdict="TRANSIENT", age_hours=6)

        result = get_recent_complete_investigation(db, LAB, "pods_crashlooping")
        assert result is not None
        assert result.id == actionable.id

    def test_only_transient_returns_none(self, db):
        from db.repository import get_recent_complete_investigation

        _seed_complete(db, "inv-known03", verdict="TRANSIENT", age_hours=6)

        assert get_recent_complete_investigation(db, LAB, "pods_crashlooping") is None

    def test_outside_window_returns_none(self, db):
        from db.repository import get_recent_complete_investigation

        _seed_complete(db, "inv-known04", verdict="ACTIONABLE", age_hours=25)

        assert get_recent_complete_investigation(db, LAB, "pods_crashlooping", hours=24) is None

    def test_comma_joined_failure_class_matches(self, db):
        from db.repository import get_recent_complete_investigation

        inv = _seed_complete(
            db, "inv-known05",
            failure_class="showroom_not_ready,service_has_no_endpoints",
        )

        result = get_recent_complete_investigation(db, LAB, "service_has_no_endpoints")
        assert result is not None
        assert result.id == inv.id

    def test_different_lab_returns_none(self, db):
        from db.repository import get_recent_complete_investigation

        _seed_complete(db, "inv-known06", lab_code="sandbox-other-zt-rhel")

        assert get_recent_complete_investigation(db, LAB, "pods_crashlooping") is None

    def test_missing_root_cause_returns_none(self, db):
        from db.repository import get_recent_complete_investigation

        _seed_complete(db, "inv-known07", root_cause=None)

        assert get_recent_complete_investigation(db, LAB, "pods_crashlooping") is None


class TestRecordInvestigationRecurrence:
    def test_bumps_count_sets_timestamp_appends_log(self, db):
        from db.repository import record_investigation_recurrence

        inv = _seed_complete(db, "inv-rec01")

        result = record_investigation_recurrence(
            db, inv.id, triggering_eval_id=42,
            note="deduped trigger: pods_crashlooping",
        )
        assert result is not None
        assert result.recurrence_count == 1
        assert result.last_recurrence_at is not None
        assert len(result.recurrence_log) == 1
        entry = result.recurrence_log[0]
        assert entry["eval_id"] == 42
        assert entry["note"] == "deduped trigger: pods_crashlooping"
        assert isinstance(entry["at"], str) and "T" in entry["at"]  # iso timestamp

    def test_debounced_within_window(self, db):
        from db.repository import get_investigation, record_investigation_recurrence

        inv = _seed_complete(db, "inv-rec02")

        first = record_investigation_recurrence(db, inv.id, note="first")
        assert first is not None

        # Second call within 30 minutes must not inflate the count.
        second = record_investigation_recurrence(db, inv.id, note="second")
        assert second is None

        rec = get_investigation(db, "inv-rec02")
        assert rec.recurrence_count == 1
        assert len(rec.recurrence_log) == 1
        assert rec.recurrence_log[0]["note"] == "first"

    def test_records_again_after_debounce_window(self, db):
        from db.repository import record_investigation_recurrence

        inv = _seed_complete(db, "inv-rec03")
        record_investigation_recurrence(db, inv.id, note="first")

        # Age the last recurrence past the 30-minute debounce.
        inv.last_recurrence_at = datetime.now(timezone.utc) - timedelta(minutes=31)
        db.commit()

        result = record_investigation_recurrence(db, inv.id, note="second")
        assert result is not None
        assert result.recurrence_count == 2
        assert len(result.recurrence_log) == 2

    def test_log_capped_at_50_oldest_dropped(self, db):
        from db.repository import get_investigation, record_investigation_recurrence

        inv = _seed_complete(db, "inv-rec04")

        with patch.dict(os.environ, {"STARGATE_INVESTIGATE_RECURRENCE_DEBOUNCE_MINUTES": "0"}):
            for i in range(55):
                record_investigation_recurrence(db, inv.id, note=f"n{i}")

        rec = get_investigation(db, "inv-rec04")
        assert rec.recurrence_count == 55
        assert len(rec.recurrence_log) == 50
        assert rec.recurrence_log[0]["note"] == "n5"    # oldest entries dropped
        assert rec.recurrence_log[-1]["note"] == "n54"  # newest kept

    def test_unknown_investigation_returns_none(self, db):
        from db.repository import record_investigation_recurrence

        assert record_investigation_recurrence(db, 999999) is None


class TestShouldAutoInvestigateKnownDiagnosis:
    def test_known_diagnosis_skips_and_records_recurrence(self, db):
        from db.repository import get_investigation
        from engine.attention_classifier import should_auto_investigate

        inv = _seed_complete(db, "inv-gate01", verdict="ACTIONABLE", age_hours=8)

        with patch("engine.attention_classifier.get_cached_baselines",
                   return_value=ANOMALOUS_BASELINES):
            should, reason, attention = should_auto_investigate(
                db, LAB, "pods_crashlooping", "east",
            )

        assert not should
        assert "recurrence" in reason
        assert f"#{inv.id}" in reason
        assert attention == "anomalous"

        rec = get_investigation(db, "inv-gate01")
        assert rec.recurrence_count == 1
        assert rec.last_recurrence_at is not None
        assert rec.recurrence_log[0]["note"] == "deduped trigger: pods_crashlooping"

    def test_transient_diagnosis_does_not_skip(self, db):
        from engine.attention_classifier import should_auto_investigate

        # Only a TRANSIENT complete investigation exists: the known-diagnosis
        # gate must be a no-op. Seeded at 8h (outside the 4h namespace dedup)
        # so every other gate passes and the trigger proceeds.
        _seed_complete(db, "inv-gate02", verdict="TRANSIENT", age_hours=8)

        with patch("engine.attention_classifier.get_cached_baselines",
                   return_value=ANOMALOUS_BASELINES):
            should, reason, _attention = should_auto_investigate(
                db, LAB, "pods_crashlooping", "east",
            )

        assert should
        assert "recurrence" not in reason
        assert "attention=" in reason

    def test_recurrence_write_failure_still_skips(self, db):
        from engine.attention_classifier import should_auto_investigate

        _seed_complete(db, "inv-gate03", verdict="ACTIONABLE", age_hours=8)

        with patch("engine.attention_classifier.get_cached_baselines",
                   return_value=ANOMALOUS_BASELINES), \
             patch("db.repository.record_investigation_recurrence",
                   side_effect=RuntimeError("db write failed")):
            should, reason, _attention = should_auto_investigate(
                db, LAB, "pods_crashlooping", "east",
            )

        assert not should
        assert "recurrence" in reason


class TestCausalChainRecurrence:
    def test_chain_exposes_recurrence(self, db):
        from db.repository import build_causal_chain, record_investigation_recurrence

        inv = _seed_complete(db, "inv-chain01")
        record_investigation_recurrence(
            db, inv.id, note="deduped trigger: pods_crashlooping",
        )

        chain = build_causal_chain(db, investigation_id=inv.id)
        assert chain["found"] is True
        assert chain["investigation"]["recurrence_count"] == 1
        assert isinstance(chain["investigation"]["last_recurrence_at"], str)

    def test_chain_defaults_without_recurrence(self, db):
        from db.repository import build_causal_chain

        inv = _seed_complete(db, "inv-chain02")

        chain = build_causal_chain(db, investigation_id=inv.id)
        assert chain["found"] is True
        assert chain["investigation"]["recurrence_count"] == 0
        assert chain["investigation"]["last_recurrence_at"] is None
