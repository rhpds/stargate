"""Tests for idempotent monitoring-gap detections (api/app.py::_record_gap_detections).

A persisting condition (stuck teardown, orphaned PV, unhealthy operator,
WorkshopProvision finding) must produce ONE evaluation per episode that is
refreshed while it persists — not a duplicate record every cycle under a
fresh timestamped run_id.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from api import app as stargate_app
from db.models import EvaluationRecord


BABYLON = {
    "stuck_teardowns": {"stuck": [{
        "anarchy_subject": "subj-1", "namespace": "lab-ns", "cluster": "ocpv05",
        "state": "destroying", "age_hours": 3.2,
    }]},
    "resource_leaks": {"orphaned_pvs": [{
        "pv_name": "pv-abc", "bound_to_namespace": "gone-ns", "capacity": "10Gi",
    }]},
    "operator_health": {"unhealthy": [{
        "namespace": "openshift-operators", "pod": "etcd-operator-xyz", "issues": ["CrashLoopBackOff"],
    }]},
    "workshops": {"workshop_provisions": {
        "query": {"ok": False, "error": "forbidden"},
        "findings": [{
            "name": "wp-1", "namespace": "summit", "reason": "Ready=False",
            "message": "stalled", "failure_class": "workshop_provision_stalled",
            "catalog_item": "lab-x", "generation": 3, "observed_generation": 2, "age_hours": 5,
        }],
    }},
}

EXPECTED_CLASSES = {
    "teardown_stuck", "resource_leak_pv", "operator_unhealthy",
    "workshop_provision_crd_unavailable", "workshop_provision_stalled",
}


def _run(db, babylon=None):
    """Run gap detections with the babylon payload patched and the event bus
    spied, so tests never touch the real bus/Kafka/DB-persist path."""
    with patch.object(stargate_app._event_bus, "emit") as emit_spy:
        with patch("api.routers._shared._load_latest_babylon", return_value=babylon or BABYLON):
            stargate_app._record_gap_detections(db)
    return emit_spy


class TestGapDetectionIdempotency:
    def test_first_cycle_creates_one_record_per_condition(self, db):
        _run(db)
        records = db.query(EvaluationRecord).all()
        assert len(records) == 5
        assert all(r.outcome == "fail" for r in records)
        assert {r.failure_class for r in records} == EXPECTED_CLASSES

    def test_repeated_cycles_refresh_instead_of_duplicating(self, db):
        _run(db)
        _run(db)
        _run(db)
        assert db.query(EvaluationRecord).count() == 5

    def test_refresh_updates_message_and_evaluated_at(self, db):
        _run(db)
        first = db.query(EvaluationRecord).filter(
            EvaluationRecord.failure_class == "teardown_stuck").one()
        first_evaluated = first.evaluated_at
        aged = dict(BABYLON)
        aged["stuck_teardowns"] = {"stuck": [dict(BABYLON["stuck_teardowns"]["stuck"][0], age_hours=9.9)]}
        _run(db, babylon=aged)
        again = db.query(EvaluationRecord).filter(
            EvaluationRecord.failure_class == "teardown_stuck").one()
        assert again.id == first.id  # same row refreshed
        assert "9.9h" in again.message
        assert again.evaluated_at >= first_evaluated

    def test_episode_run_ids_are_stable_without_timestamps(self, db):
        _run(db)
        run_ids = {r.run_id for r in db.query(EvaluationRecord).all()}
        assert len(run_ids) == 5
        assert all(rid.startswith("gap-") for rid in run_ids)
        before = {r.run_id: r.id for r in db.query(EvaluationRecord).all()}
        _run(db)
        after = {r.run_id: r.id for r in db.query(EvaluationRecord).all()}
        assert before == after  # same rows refreshed, nothing inserted

    def test_recurrence_after_window_starts_new_episode(self, db):
        _run(db)
        stale = datetime.now(timezone.utc) - timedelta(hours=48)
        for record in db.query(EvaluationRecord).all():
            record.evaluated_at = stale
        db.commit()
        _run(db)
        assert db.query(EvaluationRecord).count() == 10  # a new episode per condition

    def test_distinct_conditions_get_distinct_episodes(self, db):
        babylon = dict(BABYLON)
        babylon["stuck_teardowns"] = {"stuck": [
            dict(BABYLON["stuck_teardowns"]["stuck"][0]),
            {**BABYLON["stuck_teardowns"]["stuck"][0], "anarchy_subject": "subj-2"},
        ]}
        _run(db, babylon=babylon)
        assert db.query(EvaluationRecord).filter(
            EvaluationRecord.failure_class == "teardown_stuck").count() == 2

    def test_destroy_failed_state_is_not_conflated_with_stuck(self, db):
        """destroy-failed/destroy-error is an explicit failure (destroy_failed);
        destroying past the threshold is a stall (teardown_stuck)."""
        babylon = dict(BABYLON)
        babylon["stuck_teardowns"] = {"stuck": [
            {**BABYLON["stuck_teardowns"]["stuck"][0], "state": "destroying"},
            {**BABYLON["stuck_teardowns"]["stuck"][0], "state": "destroy-failed"},
            {**BABYLON["stuck_teardowns"]["stuck"][0], "state": "destroy-error"},
        ]}
        _run(db, babylon=babylon)
        classes = db.query(EvaluationRecord).filter(
            EvaluationRecord.failure_class.in_(["destroy_failed", "teardown_stuck"])
        ).all()
        by_class = {}
        for r in classes:
            by_class.setdefault(r.failure_class, []).append(r)
        assert {c for c in by_class} == {"destroy_failed", "teardown_stuck"}
        assert len(by_class["destroy_failed"]) == 2
        assert len(by_class["teardown_stuck"]) == 1


class TestGapSuccessRecordsAndEvents:
    """WorkshopProvision successes are first-class pass records, and every
    new episode emits exactly one bus event (evaluation.passed/failed)."""

    def _babylon_with_success(self):
        import copy
        babylon = copy.deepcopy(BABYLON)
        babylon["workshops"]["workshop_provisions"]["succeeded"] = [
            {"name": "wp-ok", "namespace": "summit",
             "catalog_item": "lab-y", "owner": "mw-1"},
            {"name": "wp-ok-2", "namespace": "summit",
             "catalog_item": "lab-y", "owner": "mw-2"},
        ]
        return babylon

    def test_success_records_created_with_pass_outcome(self, db):
        emit = _run(db, babylon=self._babylon_with_success())
        passes = db.query(EvaluationRecord).filter(EvaluationRecord.outcome == "pass").all()
        assert len(passes) == 2
        for record in passes:
            assert record.stage_id == "provisioning"
            assert record.failure_class is None
            assert "succeeded" in record.message
        passed_events = [e for e in emit.call_args_list if e.args[0].event_type == "evaluation.passed"]
        assert len(passed_events) == 2

    def test_success_records_are_idempotent_and_events_emit_once(self, db):
        babylon = self._babylon_with_success()
        emit = _run(db, babylon=babylon)
        _run(db, babylon=babylon)
        _run(db, babylon=babylon)
        assert db.query(EvaluationRecord).filter(EvaluationRecord.outcome == "pass").count() == 2
        passed_events = [e for e in emit.call_args_list if e.args[0].event_type == "evaluation.passed"]
        assert len(passed_events) == 2  # one per episode, not per cycle

    def test_failure_episodes_emit_exactly_one_event_each(self, db):
        emit = _run(db)
        failed_events = [e for e in emit.call_args_list if e.args[0].event_type == "evaluation.failed"]
        assert len(failed_events) == 5  # one per failure episode in BABYLON
        _run(db)
        failed_events = [e for e in emit.call_args_list if e.args[0].event_type == "evaluation.failed"]
        assert len(failed_events) == 5  # refreshes do not re-emit

    def test_teardown_and_leak_records_use_destroy_complete_stage(self, db):
        _run(db)
        teardown = db.query(EvaluationRecord).filter(
            EvaluationRecord.failure_class == "teardown_stuck").one()
        leak = db.query(EvaluationRecord).filter(
            EvaluationRecord.failure_class == "resource_leak_pv").one()
        assert teardown.stage_id == "destroy-complete"
        assert leak.stage_id == "destroy-complete"
        operator = db.query(EvaluationRecord).filter(
            EvaluationRecord.failure_class == "operator_unhealthy").one()
        assert operator.stage_id == "cluster-health"

    def test_aap_destroy_successes_become_reclamation_records(self, db, monkeypatch):
        """Successful AAP destroy jobs are reclamation completions: pass
        records on the destroy-complete stage, one episode per job."""
        import api.routers._shared as shared
        monkeypatch.setattr(shared, "_aap_cache", {"data": {"recent_events": [
            {"job_id": 101, "type": "destroy", "outcome": "success",
             "lab_code": "lab-a", "catalog_item": "ci.x"},
            {"job_id": 102, "type": "destroy", "outcome": "success",
             "lab_code": "lab-b", "catalog_item": "ci.y"},
            {"job_id": 103, "type": "destroy", "outcome": "fail",
             "lab_code": "lab-c", "catalog_item": "ci.z"},
            {"job_id": 104, "type": "provision", "outcome": "success",
             "lab_code": "lab-d", "catalog_item": "ci.w"},
        ]}, "ts": 0.0}, raising=False)
        emit = _run(db)
        reclaimed = db.query(EvaluationRecord).filter(
            EvaluationRecord.run_id.like("gap-reclaim-%")).all()
        assert len(reclaimed) == 2  # only successful destroys
        for record in reclaimed:
            assert record.outcome == "pass"
            assert record.stage_id == "destroy-complete"
            assert record.failure_class is None
            assert "reclamation-outcome/v1: reclaimed" in record.message
        passed_events = [e for e in emit.call_args_list if e.args[0].event_type == "evaluation.passed"]
        assert len(passed_events) == 2
        # idempotent across cycles
        _run(db)
        assert db.query(EvaluationRecord).filter(
            EvaluationRecord.run_id.like("gap-reclaim-%")).count() == 2

    def test_missing_aap_cache_is_tolerated(self, db, monkeypatch):
        import api.routers._shared as shared
        monkeypatch.delattr(shared, "_aap_cache", raising=False)
        _run(db)  # must not raise
        assert db.query(EvaluationRecord).filter(
            EvaluationRecord.run_id.like("gap-reclaim-%")).count() == 0


class TestGapDetectionSingleWriter:
    """The advisory lock prevents the two-replica check-then-insert race
    (observed 2026-10-29: identical episode run_ids inserted 6ms apart)."""

    def test_lock_helper_acquires_on_sqlite(self, db):
        from api.app import _acquire_gap_lock
        assert _acquire_gap_lock(db) is True

    def test_busy_lock_skips_the_pass(self, db, monkeypatch):
        import api.app as app_module
        monkeypatch.setattr(app_module, "_acquire_gap_lock", lambda db: False)
        emit = _run(db)
        assert db.query(EvaluationRecord).count() == 0
        emit.assert_not_called()

    def test_nothing_to_write_releases_via_rollback(self, db, monkeypatch):
        """A pass with zero detections must not leave the transaction open."""
        import api.app as app_module
        babylon = {"stuck_teardowns": {"stuck": []}, "resource_leaks": {},
                   "operator_health": {}, "workshops": {}}
        rolled = []
        monkeypatch.setattr(db, "rollback", lambda: rolled.append(True))
        _run(db, babylon=babylon)
        assert db.query(EvaluationRecord).count() == 0
        assert rolled, "empty pass must rollback to release the advisory lock"

    def test_dedup_window_is_env_configurable(self, db, monkeypatch):
        monkeypatch.setenv("STARGATE_GAP_DEDUP_HOURS", "0")  # zero window: every cycle is a new episode
        _run(db)
        assert db.query(EvaluationRecord).count() == 5
        _run(db)  # window is zero, so the persisting condition starts a new episode
        assert db.query(EvaluationRecord).count() == 10
