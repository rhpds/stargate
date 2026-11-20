"""The cluster card's numbers are a window, and the window has no time bound.

`get_cluster_failure_summary` takes the newest N evaluations for a cluster. A
cluster that stops reporting keeps that window forever, so the card has to say
how old it is — otherwise "0% health three weeks ago" renders exactly like
"0% health a minute ago" (ocpv03 vs ocpv09, measured 2026-11-20).
"""

from datetime import datetime, timedelta, timezone

from db import repository
from db.models import EvaluationRecord


def _record(run_id, evaluated_at, *, outcome="pass", cluster="ocpv09",
            lab_code="sandbox-abcd9-zt-ansiblebu", failure_class=None):
    return EvaluationRecord(
        run_id=run_id,
        stage_id="route-ready",
        outcome=outcome,
        failure_class=failure_class,
        message="",
        evaluated_at=evaluated_at,
        lab_code=lab_code,
        cluster_name=cluster,
    )


def _summary(db, cluster="ocpv09"):
    return repository.get_cluster_failure_summary(db, cluster)


def test_scanning_cluster_reports_fresh(db):
    now = datetime.now(timezone.utc)
    db.add(_record("run-fresh", now - timedelta(seconds=30)))
    db.commit()

    summary = _summary(db)

    assert summary["freshness"] == "fresh"
    assert summary["age_seconds"] < 300
    assert summary["last_evaluated_at"] is not None
    assert summary["window_started_at"] is not None


def test_abandoned_cluster_reports_stale_with_its_window(db):
    """This is ocpv03: a window that stopped on 2 November still reads 0%."""
    now = datetime.now(timezone.utc)
    first = now - timedelta(days=21)
    last = now - timedelta(days=18)
    db.add_all([
        _record("run-old-1", first, outcome="fail", failure_class="unclassified"),
        _record("run-old-2", last, outcome="fail", failure_class="unclassified"),
    ])
    db.commit()

    summary = _summary(db)

    assert summary["freshness"] == "stale"
    assert summary["age_seconds"] >= 18 * 24 * 3600
    assert summary["failure_classes"] == {"unclassified": 2}
    assert summary["window_started_at"] < summary["last_evaluated_at"]


def test_empty_window_is_unknown_not_fresh(db):
    summary = _summary(db)

    assert summary["freshness"] == "unknown"
    assert summary["age_seconds"] is None
    assert summary["last_evaluated_at"] is None
    assert summary["window_started_at"] is None
    assert summary["total_evaluations"] == 0
    assert summary["health_rate"] == 0


def test_window_is_bounded_by_count_not_by_time(db):
    """The limit still applies, and does not silently become a time filter."""
    now = datetime.now(timezone.utc)
    db.add_all([
        _record(f"run-{i}", now - timedelta(days=20) + timedelta(minutes=i))
        for i in range(250)
    ])
    db.commit()

    summary = _summary(db)

    assert summary["total_evaluations"] == 200
    assert summary["freshness"] == "stale"
    assert summary["age_seconds"] >= 19 * 24 * 3600


def test_dashboard_clusters_ships_the_age(client, db, monkeypatch):
    now = datetime.now(timezone.utc)
    db.add(_record("run-api", now - timedelta(days=5)))
    db.commit()
    monkeypatch.setattr("cli.scan.load_clusters", lambda: {"ocpv09": "kubeconfig-ocpv09"})

    resp = client.get("/dashboard/clusters")

    assert resp.status_code == 200
    card = resp.json()["clusters"][0]
    assert card["cluster"] == "ocpv09"
    assert card["freshness"] == "stale"
    assert card["age_seconds"] >= 5 * 24 * 3600
    assert card["last_evaluated_at"] is not None
