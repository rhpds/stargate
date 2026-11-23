"""DB-derived tier-3 sweep freshness — the signal that watches the sweep.

`/health`'s scanner age comes from a five-minute snapshot of the *tier 1*
tick, so it stays green while tier 3 is wedged. These tests pin the metric
that answers the actual question: how old is the stalest live lab.
"""

from datetime import datetime, timedelta, timezone

import pytest

from api import tier3_freshness


def _run(db, namespace, minutes_ago, cluster="ocpv07"):
    from db.models import RunRecord

    db.add(RunRecord(
        run_id=f"run-{namespace}-{minutes_ago}",
        demo_id="d",
        namespace=namespace,
        requested_by="scanner",
        status="completed",
        rubric_version="v",
        cluster_name=cluster,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    ))
    db.commit()


def _scan(cluster, namespaces):
    return [{"cluster": cluster, "all_sandbox_namespaces": list(namespaces)}]


@pytest.fixture(autouse=True)
def _reset_state():
    tier3_freshness._state.clear()
    tier3_freshness._last_warn.clear()
    tier3_freshness._cache["clusters"] = []
    tier3_freshness._cache["computed_at"] = None
    yield
    tier3_freshness._state.clear()
    tier3_freshness._last_warn.clear()
    tier3_freshness._cache["clusters"] = []
    tier3_freshness._cache["computed_at"] = None


class TestCompute:
    def test_sweep_age_is_the_stalest_live_namespace(self, db):
        _run(db, "sandbox-a", 2)
        _run(db, "sandbox-b", 90)

        [cluster] = tier3_freshness.compute(db, _scan("ocpv07", ["sandbox-a", "sandbox-b"]))

        assert cluster["live"] == 2
        assert cluster["scanned"] == 2
        assert cluster["never_scanned"] == 0
        assert 89 * 60 <= cluster["sweep_age_seconds"] <= 91 * 60
        assert cluster["last_scan_age_seconds"] <= 3 * 60

    def test_destroyed_namespaces_stop_counting(self, db):
        # Teardown churn, not scanner lag: the namespace is gone from the
        # scanner's live set, so its 10 h-old run must not set the age.
        _run(db, "sandbox-gone", 600)
        _run(db, "sandbox-a", 5)

        [cluster] = tier3_freshness.compute(db, _scan("ocpv07", ["sandbox-a"]))

        assert cluster["live"] == 1
        assert cluster["sweep_age_seconds"] <= 6 * 60

    def test_never_scanned_namespaces_are_reported_separately(self, db):
        _run(db, "sandbox-a", 5)

        [cluster] = tier3_freshness.compute(
            db, _scan("ocpv07", ["sandbox-a", "sandbox-new", "sandbox-newer"])
        )

        assert cluster["never_scanned"] == 2
        assert cluster["scanned"] == 1
        assert cluster["unseen_sample"] == ["sandbox-new", "sandbox-newer"]
        # A live namespace that was never scanned must not masquerade as
        # infinitely old and hide behind the age of the ones that were.
        assert cluster["sweep_age_seconds"] <= 6 * 60

    def test_runs_older_than_the_lookback_count_as_never_scanned(self, db):
        _run(db, "sandbox-ancient", tier3_freshness.LOOKBACK_HOURS * 60 + 60)

        [cluster] = tier3_freshness.compute(db, _scan("ocpv07", ["sandbox-ancient"]))

        assert cluster["never_scanned"] == 1
        assert cluster["sweep_age_seconds"] is None

    def test_uses_each_clusters_own_live_set(self, db):
        _run(db, "sandbox-6", 10, cluster="ocpv06")
        _run(db, "sandbox-7", 100, cluster="ocpv07")

        clusters = tier3_freshness.compute(
            db,
            _scan("ocpv06", ["sandbox-6"]) + _scan("ocpv07", ["sandbox-7"]),
        )

        by_name = {c["cluster"]: c for c in clusters}
        assert by_name["ocpv06"]["sweep_age_seconds"] <= 11 * 60
        assert by_name["ocpv07"]["sweep_age_seconds"] >= 99 * 60

    def test_snapshot_without_namespaces_yields_nothing(self, db):
        assert tier3_freshness.compute(db, _scan("ocpv07", [])) == []
        assert tier3_freshness.compute(db, []) == []
        assert tier3_freshness.compute(db, None) == []

    def test_naive_timestamps_from_sqlite_do_not_explode(self, db):
        # SQLite drops tzinfo; a naive value must be read as UTC.
        from db.models import RunRecord

        db.add(RunRecord(
            run_id="naive", demo_id="d", namespace="sandbox-naive",
            requested_by="scanner", status="completed", rubric_version="v",
            cluster_name="ocpv07",
            started_at=(datetime.now(timezone.utc) - timedelta(minutes=30)).replace(tzinfo=None),
        ))
        db.commit()

        [cluster] = tier3_freshness.compute(db, _scan("ocpv07", ["sandbox-naive"]))
        assert 29 * 60 <= cluster["sweep_age_seconds"] <= 31 * 60


class TestPublishAndWarn:
    def test_gauges_are_published_per_cluster(self, db):
        from api.metrics import tier3_live_namespaces, tier3_never_scanned

        _run(db, "sandbox-a", 5)

        clusters = tier3_freshness.compute(db, _scan("ocpv07", ["sandbox-a", "sandbox-new"]))
        tier3_freshness._publish(clusters)

        assert tier3_live_namespaces.labels(cluster="ocpv07")._value.get() == 2
        assert tier3_never_scanned.labels(cluster="ocpv07")._value.get() == 1

    def test_a_stale_sweep_warns_with_the_laggards(self, db, caplog):
        _run(db, "sandbox-old", 200)

        clusters = tier3_freshness.compute(db, _scan("ocpv07", ["sandbox-old"]))
        with caplog.at_level("WARNING", logger="stargate.tier3_freshness"):
            tier3_freshness._warn(clusters, target=7200, now_epoch=1000.0)

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "ocpv07" in warnings[0].getMessage()
        assert "sandbox-old" in warnings[0].getMessage()

    def test_the_same_stale_cluster_is_not_re_warned_every_cycle(self, db, caplog):
        _run(db, "sandbox-old", 200)
        clusters = tier3_freshness.compute(db, _scan("ocpv07", ["sandbox-old"]))

        with caplog.at_level("WARNING", logger="stargate.tier3_freshness"):
            tier3_freshness._warn(clusters, target=7200, now_epoch=1000.0)
            tier3_freshness._warn(clusters, target=7200, now_epoch=1060.0)
            tier3_freshness._warn(clusters, target=7200, now_epoch=1000.0 + 3601)

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 2

    def test_recovery_is_logged_once(self, db, caplog):
        _run(db, "sandbox-old", 200)
        stale = tier3_freshness.compute(db, _scan("ocpv07", ["sandbox-old"]))
        tier3_freshness._warn(stale, target=7200, now_epoch=1000.0)

        _run(db, "sandbox-old", 1)
        fresh = tier3_freshness.compute(db, _scan("ocpv07", ["sandbox-old"]))
        with caplog.at_level("INFO", logger="stargate.tier3_freshness"):
            tier3_freshness._warn(fresh, target=7200, now_epoch=2000.0)

        assert any(
            r.levelname == "INFO" and "back inside" in r.getMessage()
            for r in caplog.records
        )


class TestTargetAndCache:
    def test_target_defaults_to_two_hours(self, monkeypatch):
        monkeypatch.delenv("STARGATE_TIER3_FRESHNESS_TARGET_SECONDS", raising=False)
        assert tier3_freshness.target_seconds() == 7200

    def test_target_is_configurable_and_rejects_junk(self, monkeypatch):
        monkeypatch.setenv("STARGATE_TIER3_FRESHNESS_TARGET_SECONDS", "3600")
        assert tier3_freshness.target_seconds() == 3600
        for junk in ("soon", "0", "-5"):
            monkeypatch.setenv("STARGATE_TIER3_FRESHNESS_TARGET_SECONDS", junk)
            assert tier3_freshness.target_seconds() == 7200

    def test_health_reports_tier3_from_the_cached_measurement(self, client, db):
        _run(db, "sandbox-a", 5)
        clusters = tier3_freshness.compute(db, _scan("ocpv07", ["sandbox-a"]))
        tier3_freshness._publish(clusters)
        tier3_freshness._cache["clusters"] = clusters
        tier3_freshness._cache["target"] = 7200.0
        tier3_freshness._cache["computed_at"] = datetime.now(timezone.utc).isoformat()

        body = client.get("/health").json()

        assert body["components"]["tier3"] == "ok"
        assert body["components"]["tier3_detail"]["clusters"][0]["cluster"] == "ocpv07"

    def test_health_calls_a_slow_sweep_stale(self, client):
        _run_stale = {
            "cluster": "ocpv07",
            "live": 10,
            "scanned": 8,
            "never_scanned": 2,
            "sweep_age_seconds": 3 * 3600,
            "last_scan_age_seconds": 60,
            "stalest": ["sandbox-old"],
            "unseen_sample": ["sandbox-new"],
        }
        tier3_freshness._cache["clusters"] = [_run_stale]
        tier3_freshness._cache["target"] = 7200.0
        tier3_freshness._cache["computed_at"] = datetime.now(timezone.utc).isoformat()

        body = client.get("/health").json()

        assert body["components"]["tier3"] == "stale"
        assert body["components"]["tier3_detail"]["stale_clusters"] == ["ocpv07"]
        assert body["status"] == "degraded"

    def test_health_omits_tier3_until_the_first_measurement(self, client):
        body = client.get("/health").json()

        assert "tier3" not in body["components"]
        assert "tier3_detail" not in body["components"]

    def test_refresh_caches_what_health_reads(self, monkeypatch):
        monkeypatch.setattr(
            tier3_freshness,
            "compute",
            lambda session, scan_data: [{
                "cluster": "ocpv07", "live": 1, "scanned": 1, "never_scanned": 0,
                "sweep_age_seconds": 300, "last_scan_age_seconds": 300,
                "stalest": ["sandbox-a"], "unseen_sample": [],
            }],
        )

        clusters = tier3_freshness.refresh(_scan("ocpv07", ["sandbox-a"]))

        assert clusters[0]["cluster"] == "ocpv07"
        assert tier3_freshness.cached()["clusters"][0]["cluster"] == "ocpv07"
        assert tier3_freshness.cached()["target_seconds"] == 7200.0
