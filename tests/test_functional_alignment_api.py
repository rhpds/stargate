from datetime import datetime, timezone

from db.models import SourceEvent


def test_gate_flags_are_disabled_by_default(client):
    response = client.get("/admin/functional/gates")
    assert response.status_code == 200
    assert all(value is False for value in response.json()["gates"].values())


def test_source_event_read_api(client, db):
    now = datetime.now(timezone.utc)
    db.add(SourceEvent(source_system="aap", source_instance="event-0", source_event_id="42",
        evidence_hash="a" * 64, state="new", normalized_error="failed task",
        first_seen_at=now, last_seen_at=now))
    db.commit()
    response = client.get("/admin/functional/source-events")
    assert response.status_code == 200
    assert response.json()["items"][0]["source_event_id"] == "42"


def test_stage_receipt_requires_all_promotion_evidence(client):
    response = client.post("/admin/functional/gates/gate-1/receipt", json={"rubric_score": 100})
    assert response.status_code == 422


def test_stage_receipt_computes_eligibility(client):
    response = client.post("/admin/functional/gates/gate-1/receipt", json={
        "rubric_score": 94, "critical_passed": True, "severity_one_open": 0,
        "duplicate_count": 0, "rollback_verified": True,
        "tests": ["tests/test_functional_alignment.py"],
    })
    assert response.status_code == 200
    assert response.json()["promotion_eligible"] is True
    receipts = client.get("/admin/functional/gates/receipts").json()["items"]
    assert receipts[0]["passed"] is True


def test_stage_receipt_preserves_full_gate_name(client):
    gate = "gate-1-source-ingestion"
    response = client.post(f"/admin/functional/gates/{gate}/receipt", json={
        "rubric_score": 95, "critical_passed": True, "severity_one_open": 0,
        "duplicate_count": 0, "rollback_verified": True,
    })
    assert response.status_code == 200
    assert response.json()["promotion_eligible"] is True
    receipts = client.get("/admin/functional/gates/receipts").json()["items"]
    assert receipts[0]["gate"] == gate
