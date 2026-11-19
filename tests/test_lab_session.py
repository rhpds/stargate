"""One lab's life, from stored data only."""

from datetime import datetime, timedelta, timezone

START = datetime.now(timezone.utc) - timedelta(hours=3)


def _run(db, run_id, namespace="sandbox-x", status="completed"):
    from db.models import RunRecord
    db.add(RunRecord(
        run_id=run_id, demo_id="zt-rhelbu", namespace=namespace,
        requested_by="test", status=status, rubric_version="v",
        started_at=START, completed_at=START + timedelta(minutes=20),
        cluster_name="ocpv08",
    ))
    db.commit()


def _eval(db, run_id, stage, outcome, minutes, cls=None, lab="sandbox-x"):
    from db.models import EvaluationRecord
    db.add(EvaluationRecord(
        run_id=run_id, stage_id=stage, outcome=outcome,
        failure_class=cls if outcome == "fail" else None,
        lab_code=lab, cluster_name="ocpv08",
        evaluated_at=START + timedelta(minutes=minutes),
    ))
    db.commit()


def _evidence(db, run_id, kind, observed):
    from db.models import EvidenceRecord
    from uuid import uuid4
    db.add(EvidenceRecord(
        evidence_id=f"ev-{uuid4().hex[:8]}", run_id=run_id, stage_id="namespace-ready",
        type=kind, source="test", observed=observed, result="pass",
        timestamp=START + timedelta(minutes=1),
    ))
    db.commit()


class TestLabSession:
    def test_assembles_owner_state_and_flapping(self, db):
        from db.repository import lab_session

        _run(db, "r1")
        _evidence(db, "r1", "Namespace", {
            "name": "sandbox-x", "phase": "Active",
            "owner": "alice", "owner_email": "alice@example.com",
            "catalog_item": "zt-rhel-bu-lab-developer-cnv",
        })
        _eval(db, "r1", "namespace-ready", "pass", 2)
        _eval(db, "r1", "deployment-ready", "fail", 5, "pods_not_ready")
        _eval(db, "r1", "deployment-ready", "pass", 15)
        _eval(db, "r1", "showroom-healthy", "fail", 20, "showroom_not_ready")

        session = lab_session(db, "sandbox-x")

        assert session["found"] is True
        assert session["owner"] == "alice"
        assert session["catalog_item"] == "zt-rhel-bu-lab-developer-cnv"
        assert session["cluster"] == "ocpv08"
        assert session["runs"]["total"] == 1
        assert session["evaluations"]["failed"] == 2
        assert session["flaps"] == 1
        # showroom never passed, so the lab never reached "ready"
        assert session["ready_at"] is None
        assert session["state"]["namespace_phase"] == "Active"

    def test_ready_when_every_observed_stage_passed(self, db):
        from db.repository import lab_session

        _run(db, "r2")
        _eval(db, "r2", "namespace-ready", "pass", 1)
        _eval(db, "r2", "deployment-ready", "pass", 3)
        _eval(db, "r2", "showroom-healthy", "pass", 6)

        session = lab_session(db, "sandbox-x")

        assert session["ready_at"] is not None
        assert session["time_to_ready_minutes"] == 6

    def test_unknown_lab_is_explicit(self, db):
        from db.repository import lab_session
        assert lab_session(db, "sandbox-none")["found"] is False

    def test_follows_container_runs_by_lab_code(self, db):
        """Container runs store a different run namespace; lab_code is the join."""
        from db.repository import lab_session

        _run(db, "zt-rhel-1", namespace="sg-ocpv08-abc")
        _eval(db, "zt-rhel-1", "showroom-healthy", "pass", 4, lab="sandbox-y")

        session = lab_session(db, "sandbox-y")

        assert session["found"] is True
        assert session["evaluations"]["total"] == 1


class TestSurfaces:
    def test_mcp_tool_returns_the_session(self, db, monkeypatch):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        _run(db, "r3")
        _eval(db, "r3", "namespace-ready", "pass", 1)

        out = mcp_server.get_lab_session("sandbox-x")

        assert '"found": true' in out
        assert "sandbox-x" in out

    def test_http_endpoint_returns_the_session(self, client, db):
        _run(db, "r4")
        _eval(db, "r4", "namespace-ready", "pass", 1)

        body = client.get("/labs/sandbox-x/session").json()

        assert body["found"] is True
        assert body["evaluations"]["total"] == 1
