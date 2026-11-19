"""Live lab inventory from recent evaluations."""

from datetime import datetime, timedelta, timezone

NOW = datetime.now(timezone.utc)


def _eval(db, lab, cluster, stage, outcome, minutes, cls=None):
    from db.models import EvaluationRecord
    db.add(EvaluationRecord(
        run_id=f"r-{lab}-{stage}-{minutes}", stage_id=stage, outcome=outcome,
        failure_class=cls if outcome == "fail" else None,
        lab_code=lab, cluster_name=cluster,
        evaluated_at=NOW - timedelta(minutes=minutes),
    ))
    db.commit()


class TestLiveLabs:
    def test_state_is_derived_per_stage(self, db):
        from db.repository import live_labs

        _eval(db, "sandbox-a-zt-rhelbu", "ocpv08", "namespace-ready", "pass", 10)
        _eval(db, "sandbox-a-zt-rhelbu", "ocpv08", "deployment-ready", "fail", 5,
              "pods_not_ready")
        _eval(db, "sandbox-b-zt-rhelbu", "ocpv07", "namespace-ready", "pass", 8)
        _eval(db, "sandbox-b-zt-rhelbu", "ocpv07", "deployment-ready", "pass", 4)

        report = live_labs(db, window_hours=2)
        by_lab = {row["lab"]: row for row in report["labs"]}

        assert by_lab["sandbox-a-zt-rhelbu"]["state"] == "failing"
        assert by_lab["sandbox-a-zt-rhelbu"]["failure_class"] == "pods_not_ready"
        assert by_lab["sandbox-b-zt-rhelbu"]["state"] == "ready"
        assert report["summary"] == {
            **report["summary"],
            "labs": 2, "ready": 1, "failing": 1, "unknown": 0,
        }

    def test_owner_and_catalog_come_from_the_mapping(self, db):
        from db.models import LabMapping
        from db.repository import live_labs

        _eval(db, "sandbox-c-zt-rhelbu", "ocpv08", "namespace-ready", "pass", 3)
        db.add(LabMapping(lab_code="sandbox-c-zt-rhelbu", owner="babylon",
                          ci_slug="zero-touch-base-rhel"))
        db.commit()

        row = live_labs(db, window_hours=2)["labs"][0]

        assert row["owner"] == "babylon"
        assert row["catalog_item"] == "zero-touch-base-rhel"
        assert row["family"] == "zt-rhelbu"

    def test_stale_labs_are_not_live(self, db):
        from db.repository import live_labs
        _eval(db, "sandbox-old-zt-rhelbu", "ocpv08", "namespace-ready", "pass", 180)
        assert live_labs(db, window_hours=2)["summary"]["labs"] == 0


class TestSurfaces:
    def test_http_endpoint(self, client, db):
        _eval(db, "sandbox-d-zt-rhelbu", "ocpv08", "namespace-ready", "pass", 3)
        body = client.get("/labs/live?window_hours=2").json()
        assert body["summary"]["ready"] == 1
        assert body["labs"][0]["lab"] == "sandbox-d-zt-rhelbu"

    def test_mcp_tool(self, db, monkeypatch):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        _eval(db, "sandbox-e-zt-rhelbu", "ocpv08", "deployment-ready", "fail", 2,
              "pods_not_ready")
        out = mcp_server.get_live_labs(window_hours=2)
        assert '"state": "failing"' in out
