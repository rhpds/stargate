"""Tests for cluster saturation correlation (engine/cluster_saturation.py).

Scenarios mirror the documented incidents in docs/incident-validation-2026-10.md:
- SATURATED cluster: rate spike + diverse classes + lab differential (ocpv08, Oct 13-14)
- HEALTHY cluster: no signals
- CONTENT BUG: one lab failing on every cluster — must NOT fire (no differential)
- COMPONENT BUG: one failure class spiking cluster-wide — must NOT fire (no diversity)
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from db.database import Base
from engine.cluster_saturation import detect_cluster_saturation
from tests.conftest import TestSession, test_engine


NOW = datetime(2026, 10, 15, 12, 0, 0, tzinfo=timezone.utc)


def _mk_eval(db, lab, cluster, outcome, failure_class=None, at=NOW, count=1):
    for _ in range(count):
        db.execute(
            text(
                "INSERT INTO evaluations (run_id, stage_id, outcome, failure_class, "
                "message, evaluated_at, lab_code, cluster_name) "
                "VALUES (:run_id, :stage_id, :outcome, :fc, :msg, :at, :lab, :cluster)"
            ),
            {
                "run_id": f"run-{lab}-{cluster}-{at.isoformat()}-{_}",
                "stage_id": "showroom-healthy",
                "outcome": outcome,
                "fc": failure_class,
                "msg": "test",
                "at": at,
                "lab": lab,
                "cluster": cluster,
            },
        )


def _seed(db):
    """Seed a fleet: ocpvA saturated, ocpvB healthy, plus inverse patterns."""
    win = NOW - timedelta(hours=3)
    base = NOW - timedelta(days=4)

    # ---- ocpvA: SATURATED (the Oct 13-14 ocpv08 pattern) ----
    # Window: high failure rate across many distinct classes.
    sat_classes = [
        ("vmi_not_running", 30),
        ("datavolume_failed", 20),
        ("pods_not_ready", 18),
        ("showroom_not_ready", 15),
        ("service_has_no_endpoints", 12),
        ("unclassified", 10),
    ]
    for fc, n in sat_classes:
        _mk_eval(db, "lab-sat-1", "ocpvA", "fail", fc, at=win, count=n // 3)
        _mk_eval(db, "lab-sat-2", "ocpvA", "fail", fc, at=win, count=n - n // 3)
    _mk_eval(db, "lab-sat-1", "ocpvA", "pass", at=win, count=10)
    _mk_eval(db, "lab-sat-2", "ocpvA", "pass", at=win, count=10)
    # Same labs pass on healthy cluster ocpvB in-window (differential).
    _mk_eval(db, "lab-sat-1", "ocpvB", "pass", at=win, count=12)
    _mk_eval(db, "lab-sat-2", "ocpvB", "pass", at=win, count=12)
    # Baseline for ocpvA: low failure rate over sufficient volume.
    for i in range(120):
        _mk_eval(db, f"lab-base-{i}", "ocpvA", "pass", at=base)
    _mk_eval(db, "lab-base-0", "ocpvA", "fail", "showroom_not_ready", at=base)
    _mk_eval(db, "lab-base-1", "ocpvA", "fail", "vmi_not_running", at=base)

    # ---- ocpvB: HEALTHY ----
    for i in range(30):
        _mk_eval(db, f"lab-ok-{i}", "ocpvB", "pass", at=win)
    _mk_eval(db, "lab-ok-0", "ocpvB", "fail", "showroom_not_ready", at=win)
    for i in range(60):
        _mk_eval(db, f"lab-okb-{i}", "ocpvB", "pass", at=base)

    # ---- ocpvC: CONTENT BUG (one lab fails everywhere) ----
    # lab-broken fails on every cluster with one class — no differential,
    # but ocpvC gets extra volume so its rate spikes.
    _mk_eval(db, "lab-broken", "ocpvC", "fail", "ansible_playbook_bug", at=win, count=30)
    _mk_eval(db, "lab-broken", "ocpvA", "fail", "ansible_playbook_bug", at=win, count=10)
    _mk_eval(db, "lab-broken", "ocpvB", "fail", "ansible_playbook_bug", at=win, count=10)
    for i in range(20):
        _mk_eval(db, f"lab-okc-{i}", "ocpvC", "pass", at=win)
    for i in range(40):
        _mk_eval(db, f"lab-okcb-{i}", "ocpvC", "pass", at=base)

    # ---- ocpvD: COMPONENT BUG (single class spike, no diversity) ----
    # A routing bug breaks one thing cluster-wide: one class, high rate.
    _mk_eval(db, "lab-d1", "ocpvD", "fail", "route_missing", at=win, count=25)
    _mk_eval(db, "lab-d2", "ocpvD", "fail", "route_missing", at=win, count=25)
    _mk_eval(db, "lab-d1", "ocpvD", "pass", at=win, count=5)
    # d1/d2 pass elsewhere — differential may exist, but no diversity.
    _mk_eval(db, "lab-d1", "ocpvB", "pass", at=win, count=8)
    _mk_eval(db, "lab-d2", "ocpvB", "pass", at=win, count=8)
    for i in range(50):
        _mk_eval(db, f"lab-okdb-{i}", "ocpvD", "pass", at=base)

    db.commit()


@pytest.fixture()
def sat_db():
    """Fresh database with the seeded fleet."""
    Base.metadata.create_all(bind=test_engine)

    db = TestSession()
    _seed(db)
    yield db
    db.rollback()
    db.close()
    Base.metadata.drop_all(bind=test_engine)


def _get(report, cluster):
    return next(c for c in report["clusters"] if c["cluster"] == cluster)


def test_saturated_cluster_fires_all_three_signals(sat_db):
    report = detect_cluster_saturation(
        sat_db,
        window_start=NOW - timedelta(hours=6),
        window_end=NOW,
        window_hours=6,
    )
    a = _get(report, "ocpvA")
    assert a["saturated"], f"ocpvA should be saturated: {a['signals']}"
    assert a["severity"] == "critical"
    assert a["signals"]["rate_spike"]["present"]
    assert a["signals"]["symptom_diversity"]["present"]
    assert a["signals"]["lab_differential"]["present"]
    assert a["signals"]["symptom_diversity"]["distinct_failure_classes"] >= 5
    divergent = {d["lab"] for d in a["signals"]["lab_differential"]["divergent_labs"]}
    assert "lab-sat-1" in divergent and "lab-sat-2" in divergent
    assert "ocpvA" in report["saturated_clusters"]
    assert "interpretation" in a


def test_healthy_cluster_not_flagged(sat_db):
    report = detect_cluster_saturation(
        sat_db, window_start=NOW - timedelta(hours=6), window_end=NOW
    )
    b = _get(report, "ocpvB")
    assert not b["saturated"]
    assert b["severity"] in ("none", "watch")
    assert "ocpvB" not in report["saturated_clusters"]


def test_content_bug_not_flagged_as_saturation(sat_db):
    """A lab failing on every cluster is a content bug — no differential."""
    report = detect_cluster_saturation(
        sat_db, window_start=NOW - timedelta(hours=6), window_end=NOW
    )
    c = _get(report, "ocpvC")
    # lab-broken fails on A and B too, so it is not divergent for ocpvC.
    divergent = {d["lab"] for d in c["signals"]["lab_differential"]["divergent_labs"]}
    assert "lab-broken" not in divergent
    # Single class → no diversity signal.
    assert not c["signals"]["symptom_diversity"]["present"]
    assert not c["saturated"], "content bug must not be reported as saturation"


def test_component_bug_not_flagged_as_saturation(sat_db):
    """One failure class spiking cluster-wide is a component bug — no diversity."""
    report = detect_cluster_saturation(
        sat_db, window_start=NOW - timedelta(hours=6), window_end=NOW
    )
    d = _get(report, "ocpvD")
    assert d["signals"]["symptom_diversity"]["distinct_failure_classes"] < 5
    assert not d["saturated"], "component bug must not be reported as saturation"


def test_report_structure(sat_db):
    report = detect_cluster_saturation(
        sat_db, window_start=NOW - timedelta(hours=6), window_end=NOW
    )
    assert report["clusters_analyzed"] >= 4
    assert set(report["thresholds"]) == {
        "min_window_fails",
        "rate_multiplier",
        "min_distinct_classes",
        "min_divergent_labs",
    }
    assert report["window"]["hours"] == 6.0
    top = report["clusters"][0]
    assert top["saturated"]  # saturated clusters sort first


def test_default_window_uses_now(sat_db):
    """No window args → last N hours ending now (no crash, valid shape)."""
    report = detect_cluster_saturation(sat_db, window_hours=6)
    assert "window" in report
    assert report["window"]["hours"] == 6.0
    assert isinstance(report["saturated_clusters"], list)


def test_low_volume_cluster_baseline_insufficient(sat_db):
    """Tiny baseline history must not produce a rate-spike false positive."""
    Base.metadata.create_all(bind=test_engine)

    db2 = TestSession()
    try:
        win = NOW - timedelta(hours=2)
        # High failure rate in window, but almost no baseline history.
        _mk_eval(db2, "lab-x", "ocpvNEW", "fail", "vmi_not_running", at=win, count=25)
        _mk_eval(db2, "lab-x", "ocpvNEW", "fail", "pods_not_ready", at=win, count=10)
        _mk_eval(db2, "lab-x", "ocpvNEW", "pass", at=win, count=5)
        _mk_eval(db2, "lab-y", "ocpvNEW", "fail", "datavolume_failed", at=win, count=5)
        _mk_eval(db2, "lab-y", "ocpvNEW", "fail", "route_missing", at=win, count=5)
        _mk_eval(db2, "lab-y", "ocpvNEW", "pass", at=win, count=5)
        _mk_eval(db2, "lab-x", "ocpvOTHER", "pass", at=win, count=10)
        db2.commit()
        report = detect_cluster_saturation(
            db2, window_start=NOW - timedelta(hours=6), window_end=NOW
        )
        n = _get(report, "ocpvNEW")
        assert not n["signals"]["rate_spike"]["baseline_sufficient"]
        assert not n["saturated"]
    finally:
        db2.rollback()
        db2.close()


def test_dashboard_saturation_endpoint(client):
    """GET /dashboard/saturation returns the report; retrospective window works."""
    from tests.conftest import TestSession, test_engine
    from db.database import Base

    Base.metadata.create_all(bind=test_engine)
    db = TestSession()
    try:
        _seed(db)
    finally:
        db.commit()
        db.close()

    resp = client.get("/dashboard/saturation", params={
        "window_start": (NOW - timedelta(hours=6)).isoformat(),
        "window_end": NOW.isoformat(),
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["clusters_analyzed"] >= 4
    assert "ocpvA" in body["saturated_clusters"]
    entry = next(c for c in body["clusters"] if c["cluster"] == "ocpvA")
    assert entry["severity"] == "critical"
    assert entry["signals"]["lab_differential"]["present"]

    # Invalid ISO date is a 400, not a 500.
    bad = client.get("/dashboard/saturation", params={"window_start": "not-a-date"})
    assert bad.status_code == 400
