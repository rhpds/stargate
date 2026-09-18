from datetime import datetime, timedelta, timezone

import pytest

from db.models import InvestigationRecord, SourceEvent
from engine.functional_alignment import (
    bounded_evidence, claim_source_events, create_jira_draft, detect_trends,
    evidence_hash, ingest_aap_failures, publish_reviewed_knowledge,
    queue_slack_delivery,
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
