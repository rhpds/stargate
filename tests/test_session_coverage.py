"""Planned seats vs provisioned, healthy and missing labs."""

from datetime import datetime, timedelta, timezone

NOW = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)


def _eval(db, lab, stage, outcome, minutes, cls=None):
    from db.models import EvaluationRecord
    db.add(EvaluationRecord(
        run_id=f"r-{lab}-{stage}", stage_id=stage, outcome=outcome,
        failure_class=cls if outcome == "fail" else None,
        lab_code=lab, cluster_name="ocpv08",
        evaluated_at=NOW + timedelta(minutes=minutes),
    ))
    db.commit()


def _mapping(db, lab, slug):
    from db.models import LabMapping
    db.add(LabMapping(lab_code=lab, ci_slug=slug))
    db.commit()


def _session(lab_code, attendees, start_hour=10, minutes=0):
    start = NOW.replace(hour=start_hour, minute=minutes)
    return {
        "lab_code": lab_code, "attendees": attendees,
        "session_date": start.date().isoformat(),
        "start_time": start.time().isoformat(),
        "end_time": (start + timedelta(hours=8)).time().isoformat(),
        "room": "Room1",
    }


class TestSessionCoverage:
    def test_counts_provisioned_ready_failing_and_missing(self, db):
        from engine.session_coverage import coverage

        # two healthy sandboxes of the catalog item, one failing
        for i in range(2):
            _eval(db, f"sandbox-{i}aaa-zt-rhelbu", "namespace-ready", "pass", 10)
            _eval(db, f"sandbox-{i}aaa-zt-rhelbu", "deployment-ready", "pass", 12)
            _mapping(db, f"sandbox-{i}aaa-zt-rhelbu", "published.zt-rhelbu.prod")
        _eval(db, "sandbox-3bbb-zt-rhelbu", "deployment-ready", "fail", 15, "pods_not_ready")
        _mapping(db, "sandbox-3bbb-zt-rhelbu", "published.zt-rhelbu.prod")

        report = coverage(
            db, [_session("RHSC-H01", 10)], {"RHSC-H01": "published.zt-rhelbu"},
            now=NOW, hours_back=6, hours_ahead=6,
        )
        row = report["sessions"][0]

        assert row["catalog_item"] == "zt-rhelbu"
        assert row["planned_seats"] == 10
        assert row["provisioned"] == 3
        assert (row["ready"], row["failing"], row["missing"]) == (2, 1, 7)
        assert report["summary"]["coverage_pct"] == 30

    def test_ignores_other_catalog_items(self, db):
        from engine.session_coverage import coverage

        _eval(db, "sandbox-9ccc-ocp4-cluster", "namespace-ready", "pass", 5)
        _mapping(db, "sandbox-9ccc-ocp4-cluster", "published.ocp4-cluster.prod")

        report = coverage(
            db, [_session("RHSC-H01", 5)], {"RHSC-H01": "published.zt-rhelbu"},
            now=NOW, hours_back=6, hours_ahead=6,
        )
        assert report["sessions"][0]["provisioned"] == 0

    def test_sessions_outside_the_window_are_ignored(self, db):
        from engine.session_coverage import coverage

        report = coverage(
            db, [_session("RHSC-H01", 5, start_hour=23)], {"RHSC-H01": "zt-rhelbu"},
            now=NOW, hours_back=1, hours_ahead=1,
        )
        assert report["sessions"] == []


class TestMcpTool:
    def test_tool_wires_schedule_and_resolution(self, db, monkeypatch):
        from api import mcp_server
        import collectors.labagator.collect_labagator as labagator

        # The tool uses the real clock; build the session around it.
        real_now = datetime.now(timezone.utc)
        start = real_now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        session = {
            "lab_code": "RHSC-H01", "attendees": 4,
            "session_date": start.date().isoformat(),
            "start_time": start.time().isoformat(),
            "end_time": (start + timedelta(hours=8)).time().isoformat(),
            "room": "Room1",
        }

        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        monkeypatch.setattr(labagator, "collect_sessions", lambda *a, **k: [session])
        monkeypatch.setattr(
            "api.routers.capacity._lab_code_resolution",
            lambda: {"RHSC-H01": "published.zt-rhelbu"},
        )

        from db.models import EvaluationRecord
        db.add(EvaluationRecord(
            run_id="r-mcp", stage_id="namespace-ready", outcome="pass",
            lab_code="sandbox-4ddd-zt-rhelbu", cluster_name="ocpv08",
            evaluated_at=real_now,
        ))
        db.commit()
        _mapping(db, "sandbox-4ddd-zt-rhelbu", "published.zt-rhelbu.prod")

        out = mcp_server.get_session_coverage(hours_back=6, hours_ahead=6)

        assert '"planned_seats": 4' in out
        assert '"provisioned": 1' in out
