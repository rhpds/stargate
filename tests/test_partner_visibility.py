"""Tests for partner catalog visibility (engine/partner_visibility.py).

The registry encodes Billy's documented 90-day analysis (Confluence
511804406): partner items at 16.8% overall, several 50-90%, invisible in
the standard biweekly report.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from engine.partner_visibility import (
    _match_lab,
    _normalize,
    load_partner_registry,
    partner_visibility,
)
from tests.conftest import TestSession, test_engine

NOW = datetime.now(timezone.utc)


def test_normalize():
    assert _normalize("OCP-Virt/Migration_Factory.demo") == "ocpvirtmigrationfactorydemo"


def test_match_lab_via_hints():
    assert _match_lab("RHPDS agd-v2.parasol-aro", None, None, ["parasol"])
    assert _match_lab("lab-x", "Backup Recovery Ocp Virt Trilio", None, ["trilio"])
    assert _match_lab("lab-x", None, "enterprise/REDHAT_ADS_DEMO", ["enterprise/REDHAT_ADS_DEMO"])
    assert not _match_lab("RHPDS agd-v2.ocp-cluster-cnv-pools", None, None, ["parasol"])


def test_registry_loads_with_baselines():
    items = load_partner_registry()
    assert len(items) >= 13
    worst = next(i for i in items if "OpenStack Services" in i["name"])
    assert worst["baseline_failure_rate"] == 90.9
    assert all(i.get("match_hints") for i in items)


def _seed_partner_db():
    from db.database import Base
    from db.models import LabMapping, EvaluationRecord

    Base.metadata.create_all(bind=test_engine)
    db = TestSession()
    # identity rows: parasol matches, an unrelated lab does not
    db.add_all([
        LabMapping(lab_code="RHPDS agd-v2.parasol-aro", ci_name="Ocp Rhoai Aro Parasol",
                   agnosticv_path="agd_v2/parasol-aro"),
        LabMapping(lab_code="RHPDS agd-v2.ocp-unrelated", ci_name="Unrelated",
                   agnosticv_path="agd_v2/ocp-unrelated"),
    ])
    # evaluations: parasol fails hard (3/4), unrelated healthy (1/4)
    for lab, n_fail, n_pass in (("RHPDS agd-v2.parasol-aro", 3, 1),
                                ("RHPDS agd-v2.ocp-unrelated", 1, 3)):
        for i in range(n_fail):
            db.add(EvaluationRecord(
                run_id=f"pv-{lab}-{i}", stage_id="showroom-healthy", outcome="fail",
                failure_class="showroom_not_ready", message="x",
                evaluated_at=NOW - timedelta(hours=1), lab_code=lab, cluster_name="ocpvA"))
        for i in range(n_pass):
            db.add(EvaluationRecord(
                run_id=f"pv-{lab}-p{i}", stage_id="showroom-healthy", outcome="pass",
                failure_class=None, message="x",
                evaluated_at=NOW - timedelta(hours=1), lab_code=lab, cluster_name="ocpvA"))
    db.commit()
    return db


def test_partner_visibility_end_to_end(monkeypatch):
    db = _seed_partner_db()
    try:
        # window includes the seeded data
        monkeypatch.setattr("engine.partner_visibility.load_partner_registry", lambda: [
            {"name": "Parasol Insurance AI Lab", "baseline_failure_rate": 26.0,
             "match_hints": ["parasol"]},
        ])
        out = partner_visibility(db, days=1)
        assert out["partner_items_matched"] == 1
        assert out["partner_failure_rate"] == 75.0   # 3 fails / 4 evals
        assert out["partner_evaluations"] == 4
        item = out["items"][0]
        assert item["matched"] is True
        assert item["failure_rate"] == 75.0
        assert item["delta_vs_baseline"] == 49.0     # 75.0 - 26.0 baseline
        assert "RHPDS agd-v2.parasol-aro" in item["matched_lab_codes"]
        # fleet comparison includes the unrelated lab: 4 fails / 8 evals
        assert out["fleet_failure_rate"] == 50.0
    finally:
        db.rollback()
        db.close()
        from db.database import Base
        Base.metadata.drop_all(bind=test_engine)


def test_partner_visibility_unmatched_item(monkeypatch):
    db = _seed_partner_db()
    try:
        monkeypatch.setattr("engine.partner_visibility.load_partner_registry", lambda: [
            {"name": "No Such Item", "baseline_failure_rate": 10.0,
             "match_hints": ["definitely-not-present"]},
        ])
        out = partner_visibility(db, days=1)
        assert out["partner_items_matched"] == 0
        assert out["partner_failure_rate"] is None
        assert "no matching lab_codes" in out["items"][0]["note"]
    finally:
        db.rollback()
        db.close()
        from db.database import Base
        Base.metadata.drop_all(bind=test_engine)


def test_dashboard_endpoint(client, monkeypatch):
    monkeypatch.setattr("engine.partner_visibility.partner_visibility",
                        lambda db, days=7: {"partner_failure_rate": 16.8, "items": []})
    resp = client.get("/dashboard/partner-visibility")
    assert resp.status_code == 200
    assert resp.json()["partner_failure_rate"] == 16.8
