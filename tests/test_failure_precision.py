"""Failure precision — how much of a failure class is noise?

A class that fails and self-resolves in the same window is either flapping or
being measured wrongly (as showroom_route_reachable was). The ratio is the
adoption metric: one false alert teaches an owner to ignore the tool.
"""

from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc)


def _eval(db, cls, lab, stage, outcome, minutes_ago=10):
    from db.models import EvaluationRecord
    db.add(EvaluationRecord(
        run_id=f"run-{cls}-{lab}-{outcome}-{minutes_ago}",
        stage_id=stage, outcome=outcome,
        failure_class=cls if outcome == "fail" else None,
        lab_code=lab, cluster_name="ocpv08",
        evaluated_at=NOW - timedelta(minutes=minutes_ago),
    ))
    db.commit()


class TestFailurePrecision:
    def test_counts_self_resolved_labs(self, db):
        from db.repository import failure_precision

        # showroom: lab-a failed then passed; lab-b only failed
        _eval(db, "showroom_not_ready", "lab-a", "showroom-healthy", "fail", 60)
        _eval(db, "showroom_not_ready", "lab-a", "showroom-healthy", "pass", 30)
        _eval(db, "showroom_not_ready", "lab-b", "showroom-healthy", "fail", 50)
        # a different class, never resolved
        _eval(db, "pods_not_ready", "lab-c", "deployment-ready", "fail", 40)

        report = failure_precision(db, hours=24)
        by_class = {row["failure_class"]: row for row in report["classes"]}

        showroom = by_class["showroom_not_ready"]
        assert showroom["evaluations"] == 2
        assert showroom["labs"] == 2
        assert showroom["self_resolved_labs"] == 1
        assert showroom["self_resolved_pct"] == 50

        pods = by_class["pods_not_ready"]
        assert pods["self_resolved_pct"] == 0

    def test_ignores_evaluations_outside_the_window(self, db):
        from db.repository import failure_precision

        _eval(db, "showroom_not_ready", "lab-old", "showroom-healthy", "fail", 60 * 48)

        report = failure_precision(db, hours=24)
        assert report["classes"] == []


class TestMcpTool:
    def test_returns_the_report(self, db, monkeypatch):
        from api import mcp_server

        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        _eval(db, "showroom_not_ready", "lab-a", "showroom-healthy", "fail", 60)
        _eval(db, "showroom_not_ready", "lab-a", "showroom-healthy", "pass", 30)

        out = mcp_server.get_failure_precision(hours=24)

        assert "showroom_not_ready" in out
        assert '"self_resolved_pct": 100' in out
