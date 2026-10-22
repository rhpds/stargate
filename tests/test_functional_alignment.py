from datetime import datetime, timedelta, timezone

import pytest

from db.models import InvestigationRecord, SourceEvent
from engine.functional_alignment import (
    bounded_evidence, claim_source_events, create_jira_draft, detect_trends,
    evidence_hash, ingest_aap_failures, publish_reviewed_knowledge,
    queue_slack_delivery,
    finish_source_event_claims,
)


def test_missing_aap_inventory_is_reported_as_collection_outage(monkeypatch):
    from collectors.aap import collect_aap

    monkeypatch.setattr(collect_aap, "load_aap_controllers", lambda: [])
    monkeypatch.setattr(collect_aap, "_cache", {"data": None, "ts": 0})

    result = collect_aap.collect_aap_jobs()

    assert result["collection_status"] == [{
        "controller": "production-inventory",
        "scope": "production",
        "status": "collection-unavailable",
        "error_type": "configuration",
    }]


def failure(**overrides):
    value = {
        "controller": "event-0", "event_id": 42, "job_id": 7,
        "controller_url": "https://aap.example", "job_url": "https://aap.example/jobs/7",
        "failing_task": "Create workshop", "play": "Provision", "role": "workshop",
        "lab_code": "guid-abc", "catalog_item": "ocp4-cluster", "type": "provision",
        "provider": "openshift", "cluster": "ocpv09", "failure_class": "route53_failed",
        "error": "Route 53 request failed", "finished": datetime.now(timezone.utc).isoformat(),
    }
    value.update(overrides)
    return value


def investigation(db, **overrides):
    values = dict(job_id="auto-test", lab_code="guid-abc", cluster="ocpv09",
                  namespace="guid-abc", failure_class="route53_failed", trigger_type="auto",
                  status="complete", analysis="Diagnosis text", root_cause="DNS quota",
                  remediation_suggestion="Increase quota", trust_dimensions={"verdict": "ACTIONABLE", "confidence": .95},
                  created_at=datetime.now(timezone.utc), completed_at=datetime.now(timezone.utc))
    values.update(overrides)
    row = InvestigationRecord(**values); db.add(row); db.commit(); db.refresh(row)
    return row


def test_sanitizes_and_bounds_raw_evidence():
    result = bounded_evidence({"password": "bad", "message": "token=abc123", "large": "x" * 70000})
    assert result["truncated"] is True
    preview = result["preview"]
    assert "abc123" not in preview and "bad" not in preview
    assert len(preview.encode()) <= 65536


def test_aap_ingestion_is_idempotent(db):
    first = ingest_aap_failures(db, [failure()])
    second = ingest_aap_failures(db, [failure()])
    assert first == {"created": 1, "updated": 0, "evaluations_created": 1}
    assert second == {"created": 0, "updated": 1, "evaluations_created": 0}
    assert db.query(SourceEvent).count() == 1


def test_normalized_error_and_task_are_redacted_before_storage(db):
    from db.models import EvaluationRecord

    ingest_aap_failures(db, [failure(error="password=private-value", failing_task="token=private-token")])
    event = db.query(SourceEvent).one()
    evaluation = db.query(EvaluationRecord).one()
    assert "private-value" not in event.normalized_error
    assert "private-token" not in event.task
    assert "private-value" not in evaluation.message


def test_changed_evidence_reopens_diagnosed_event(db):
    ingest_aap_failures(db, [failure()])
    event = db.query(SourceEvent).one(); event.state = "diagnosed"; db.commit()
    ingest_aap_failures(db, [failure(error="A materially different error")])
    assert db.query(SourceEvent).one().state == "reopened"


def test_claim_is_durable_and_exclusive(db):
    ingest_aap_failures(db, [failure()])
    inv1 = investigation(db, job_id="inv-1", status="running")
    inv2 = investigation(db, job_id="inv-2", status="running")
    assert claim_source_events(db, inv1) == [db.query(SourceEvent.id).scalar()]
    assert claim_source_events(db, inv2) == []


def test_expired_claim_is_reclaimed_and_old_completion_cannot_overwrite_owner(db):
    ingest_aap_failures(db, [failure()])
    old = investigation(db, job_id="old", status="running")
    new = investigation(db, job_id="new", status="running")
    claim_source_events(db, old)
    event = db.query(SourceEvent).one()
    event.claim_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert claim_source_events(db, new) == [event.id]
    finish_source_event_claims(db, old, success=True)
    assert db.query(SourceEvent).one().state == "claimed"
    finish_source_event_claims(db, new, success=True)
    assert db.query(SourceEvent).one().state == "diagnosed"


def test_changed_evidence_during_diagnosis_is_not_marked_diagnosed(db):
    ingest_aap_failures(db, [failure()])
    inv = investigation(db, status="running")
    claim_source_events(db, inv)
    ingest_aap_failures(db, [failure(error="Different evidence")])
    finish_source_event_claims(db, inv, success=True)
    assert db.query(SourceEvent).one().state == "reopened"


def test_completion_after_lease_expiry_reopens_event(db):
    ingest_aap_failures(db, [failure()])
    inv = investigation(db, status="running")
    claim_source_events(db, inv)
    event = db.query(SourceEvent).one()
    event.claim_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    finish_source_event_claims(db, inv, success=True)
    assert db.query(SourceEvent).one().state == "reopened"


def test_released_claim_can_be_retried_by_same_investigation(db):
    from db.models import InvestigationSourceEvent
    ingest_aap_failures(db, [failure()])
    inv = investigation(db, status="running")
    claim_source_events(db, inv)
    finish_source_event_claims(db, inv, success=False, reason="transport failure")
    assert claim_source_events(db, inv) == [db.query(SourceEvent).one().id]
    assert db.query(InvestigationSourceEvent).count() == 1
    assert db.query(InvestigationSourceEvent).one().released_at is None


def test_legacy_evaluation_does_not_claim_unrelated_source_events(db):
    from db.models import EvaluationRecord
    ingest_aap_failures(db, [failure()])
    legacy = EvaluationRecord(run_id="legacy", stage_id="platform", outcome="fail",
                              evaluated_at=datetime.now(timezone.utc))
    db.add(legacy); db.commit()
    inv = investigation(db, triggering_eval_id=legacy.id)
    assert claim_source_events(db, inv) == []


def test_repository_refuses_source_investigation_without_claim(db, monkeypatch):
    from db.models import EvaluationRecord
    from db.repository import start_investigation
    ingest_aap_failures(db, [failure()])
    evaluation = db.query(EvaluationRecord).one()
    owner = investigation(db, job_id="owner", status="running", triggering_eval_id=evaluation.id)
    claim_source_events(db, owner)
    contender = investigation(db, job_id="contender", status="queued", triggering_eval_id=evaluation.id)
    monkeypatch.setenv("STARGATE_GATE_DIAGNOSIS_CLAIMS", "true")
    with pytest.raises(ValueError, match="claim"):
        start_investigation(db, contender.job_id)
    db.refresh(contender)
    assert contender.status == "queued"


def test_agent_source_context_contains_owned_links_and_rejects_changed_evidence(db):
    from engine.functional_alignment import investigation_source_evidence
    ingest_aap_failures(db, [failure()])
    inv = investigation(db, status="running")
    claim_source_events(db, inv)
    context = investigation_source_evidence(db, inv.job_id)
    assert "https://aap.example/jobs/7" in context
    assert "Create workshop" in context
    assert "covered_source_event_ids" in context
    ingest_aap_failures(db, [failure(error="Changed after claim")])
    with pytest.raises(ValueError, match="claim changed"):
        investigation_source_evidence(db, inv.job_id)


def test_claim_error_does_not_start_investigation(db, monkeypatch):
    from db.models import EvaluationRecord
    from db.repository import start_investigation
    import engine.functional_alignment as alignment
    ingest_aap_failures(db, [failure()])
    inv = investigation(db, status="queued", triggering_eval_id=db.query(EvaluationRecord).one().id)
    monkeypatch.setenv("STARGATE_GATE_DIAGNOSIS_CLAIMS", "true")
    def broken_claim(*args):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(alignment, "claim_source_events", broken_claim)
    with pytest.raises(RuntimeError, match="database unavailable"):
        start_investigation(db, inv.job_id)
    db.refresh(inv)
    assert inv.status == "queued"


def test_inflight_claim_is_released_when_gate_disabled_before_failure(db, monkeypatch):
    from db.models import EvaluationRecord
    from db.repository import start_investigation, fail_investigation
    ingest_aap_failures(db, [failure()])
    inv = investigation(db, status="queued", triggering_eval_id=db.query(EvaluationRecord).one().id)
    monkeypatch.setenv("STARGATE_GATE_DIAGNOSIS_CLAIMS", "true")
    start_investigation(db, inv.job_id)
    assert db.query(SourceEvent).one().state == "claimed"
    monkeypatch.setenv("STARGATE_GATE_DIAGNOSIS_CLAIMS", "false")
    fail_investigation(db, inv.job_id, "worker failure during rollback")
    assert db.query(SourceEvent).one().state == "reopened"


def test_source_candidates_exclude_later_success_and_recycled_workloads(db):
    from engine.functional_alignment import source_diagnosis_candidates
    now = datetime.now(timezone.utc)
    base = {"name": "RHPDS agd-v2.ocp-cluster.prod-abc12-provision-test", "catalog_item": "agd-v2.ocp-cluster"}
    ingest_aap_failures(db, [failure(**base, event_id=1, finished=(now-timedelta(hours=2)).isoformat()),
        failure(**base, event_id=2, outcome="success", finished=(now-timedelta(hours=1)).isoformat())])
    assert source_diagnosis_candidates(db)["eligible_total"] == 0
    ingest_aap_failures(db, [failure(**base, event_id=3, finished=now.isoformat())])
    result = source_diagnosis_candidates(db)
    assert result["eligible_total"] == 1
    assert result["items"][0]["guid"] == "abc12"
    ingest_aap_failures(db, [failure(**{**base, "name": "RHPDS agd-v2.ocp-cluster.prod-abc12-destroy-test"},
        event_id=4, outcome="success", type="destroy", finished=(now+timedelta(seconds=1)).isoformat())])
    assert source_diagnosis_candidates(db)["eligible_total"] == 0


def test_source_candidates_exclude_stale_and_missing_evidence(db):
    from engine.functional_alignment import source_diagnosis_candidates
    ingest_aap_failures(db, [failure(event_id=1, finished=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()),
        failure(event_id=2, error="Unknown error")])
    result = source_diagnosis_candidates(db)
    assert result["eligible_total"] == 0
    assert result["excluded"]["insufficient_evidence"] == 1


def test_source_candidates_do_not_group_different_controllers(db):
    from engine.functional_alignment import source_diagnosis_candidates
    name = "RHPDS agd-v2.ocp-cluster.prod-abc12-provision-test"
    ingest_aap_failures(db, [failure(name=name, type="provision", controller="prod0", event_id=1),
        failure(name=name, type="provision", controller="prod1", event_id=2, outcome="success")])
    result = source_diagnosis_candidates(db)
    assert result["eligible_total"] == 1
    assert result["items"][0]["controller"] == "prod0"


def test_source_candidates_recognize_explicit_shortened_job_operations(db):
    from engine.functional_alignment import source_diagnosis_candidates
    ingest_aap_failures(db, [failure(name="RHPDS agd-v2.ocp-cluster.dev-abc12-1-provisxyz", type="other")])
    result = source_diagnosis_candidates(db)
    assert result["eligible_total"] == 1
    assert result["items"][0]["action"] == "provision"
    assert result["items"][0]["guid"] == "abc12-1"


def test_review_of_old_diagnosis_does_not_review_changed_source(db):
    from api.routers.admin.functional import review_investigation
    ingest_aap_failures(db, [failure()])
    inv = investigation(db)
    claim_source_events(db, inv)
    finish_source_event_claims(db, inv, success=True)
    ingest_aap_failures(db, [failure(error="New failure after previous diagnosis")])
    review_investigation(inv.id, {"state": "reviewed"}, db)
    assert db.query(SourceEvent).one().state == "reopened"


def test_notification_delivery_deduplicates(db):
    inv = investigation(db)
    first = queue_slack_delivery(db, inv)
    second = queue_slack_delivery(db, inv)
    assert first.id == second.id


def test_transient_diagnosis_does_not_notify(db):
    inv = investigation(db, trust_dimensions={"verdict": "TRANSIENT"})
    assert queue_slack_delivery(db, inv) is None


def test_only_reviewed_diagnosis_can_publish_knowledge(db):
    inv = investigation(db)
    with pytest.raises(ValueError):
        publish_reviewed_knowledge(db, inv.id, "operator")
    inv.review_state = "reviewed"; db.commit()
    entry = publish_reviewed_knowledge(db, inv.id, "operator")
    assert entry.active and entry.version == 1


def test_new_knowledge_version_retires_previous(db):
    first_inv = investigation(db, job_id="knowledge-1", review_state="reviewed")
    first = publish_reviewed_knowledge(db, first_inv.id, "operator")
    second_inv = investigation(db, job_id="knowledge-2", review_state="reviewed", root_cause="New verified cause")
    second = publish_reviewed_knowledge(db, second_inv.id, "operator")
    db.refresh(first)
    assert not first.active and second.version == 2


def test_jira_is_draft_and_pending_approval(db):
    inv = investigation(db)
    ticket, pending = create_jira_draft(db, inv)
    assert ticket.status == "draft"
    assert pending.action_type == "create_jira_ticket" and pending.status == "pending"
    same_ticket, same_pending = create_jira_draft(db, inv)
    assert same_ticket.id == ticket.id and same_pending.id == pending.id


def test_failure_rate_trend_threshold(db):
    now = datetime.now(timezone.utc)
    for index in range(5):
        item = failure(event_id=index, finished=(now - timedelta(hours=index)).isoformat())
        ingest_aap_failures(db, [item])
    signals = detect_trends(db, now=now)
    assert len(signals) == 1
    assert signals[0].signal_type == "failure_rate_increase"


def test_catalog_regression_requires_observed_success_baseline(db):
    now = datetime.now(timezone.utc)
    for index in range(10):
        ingest_aap_failures(db, [failure(event_id=f"success-{index}", outcome="success",
            status="successful", error="", finished=(now - timedelta(days=2, minutes=index)).isoformat())])
    for index in range(3):
        ingest_aap_failures(db, [failure(event_id=f"recent-fail-{index}",
            finished=(now - timedelta(minutes=index)).isoformat())])
    signals = detect_trends(db, now=now)
    assert any(signal.signal_type == "catalog_regression" for signal in signals)


def test_collection_unavailable_is_visible_but_not_actionable(db):
    from engine.functional_alignment import ingest_aap_collection_status
    from db.models import EvaluationRecord
    created = ingest_aap_collection_status(db, [{
        "controller": "prod0", "scope": "production",
        "status": "collection-unavailable", "error_type": "authentication",
    }])
    assert created == 1
    event = db.query(SourceEvent).one()
    assert event.state == "suppressed"
    assert event.outcome == "collection-unavailable"
    evaluation = db.query(EvaluationRecord).one()
    assert evaluation.failure_class == "collection_unavailable"
    assert evaluation.criteria_results["actionable"] is False
