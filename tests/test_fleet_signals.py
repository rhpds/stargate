"""Cross-cluster divergence and time-to-recovery."""

from datetime import datetime, timedelta, timezone

BASE = datetime.now(timezone.utc) - timedelta(hours=6)


def _eval(db, lab, cluster, stage, outcome, minutes, cls=None):
    from db.models import EvaluationRecord
    db.add(EvaluationRecord(
        run_id=f"run-{lab}-{outcome}-{minutes}", stage_id=stage, outcome=outcome,
        failure_class=cls if outcome == "fail" else None,
        lab_code=lab, cluster_name=cluster,
        evaluated_at=BASE + timedelta(minutes=minutes),
    ))
    db.commit()


class TestFleetDivergence:
    def test_same_family_passing_here_failing_there(self, db):
        from db.repository import fleet_divergence

        _eval(db, "sandbox-11111-zt-rhelbu", "ocpv06", "showroom-healthy", "pass", 1)
        _eval(db, "sandbox-22222-zt-rhelbu", "ocpv08", "showroom-healthy", "fail", 1,
              "showroom_not_ready")

        report = fleet_divergence(db, hours=24)

        assert len(report["divergences"]) == 1
        row = report["divergences"][0]
        assert row["family"] == "zt-rhelbu"
        assert row["stage"] == "showroom-healthy"
        clusters = {c["cluster"]: c for c in row["clusters"]}
        assert clusters["ocpv06"]["pass"] == 1
        assert clusters["ocpv08"]["fail"] == 1

    def test_same_outcome_everywhere_is_not_divergence(self, db):
        from db.repository import fleet_divergence

        _eval(db, "sandbox-33333-zt-rhelbu", "ocpv06", "showroom-healthy", "pass", 1)
        _eval(db, "sandbox-44444-zt-rhelbu", "ocpv08", "showroom-healthy", "pass", 1)

        assert fleet_divergence(db, hours=24)["divergences"] == []


class TestRecoveryTime:
    def test_measures_first_fail_to_next_pass(self, db):
        from db.repository import recovery_time

        _eval(db, "sandbox-a", "ocpv08", "deployment-ready", "fail", 0, "pods_not_ready")
        _eval(db, "sandbox-a", "ocpv08", "deployment-ready", "pass", 30)
        _eval(db, "sandbox-b", "ocpv08", "deployment-ready", "fail", 5, "pods_not_ready")
        _eval(db, "sandbox-b", "ocpv08", "deployment-ready", "pass", 65)

        report = recovery_time(db, hours=24)
        row = next(r for r in report["classes"] if r["failure_class"] == "pods_not_ready")

        assert row["recoveries"] == 2
        assert row["median_minutes"] == 45
        assert row["max_minutes"] == 60

    def test_counts_labs_that_never_recovered(self, db):
        from db.repository import recovery_time

        _eval(db, "sandbox-c", "ocpv08", "deployment-ready", "fail", 0, "pods_not_ready")

        report = recovery_time(db, hours=24)
        row = next(r for r in report["classes"] if r["failure_class"] == "pods_not_ready")

        assert row["recoveries"] == 0
        assert row["unrecovered"] == 1


class TestSurfaces:
    def test_mcp_tools_return_the_reports(self, db, monkeypatch):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        _eval(db, "sandbox-11111-zt-rhelbu", "ocpv06", "showroom-healthy", "pass", 1)
        _eval(db, "sandbox-22222-zt-rhelbu", "ocpv08", "showroom-healthy", "fail", 1,
              "showroom_not_ready")

        assert '"family": "zt-rhelbu"' in mcp_server.get_fleet_divergence()
        assert "showroom_not_ready" in mcp_server.get_recovery_time()
