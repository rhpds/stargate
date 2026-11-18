"""MCP: the reviewer's workflow — failure in, reproduction context out."""

from datetime import datetime, timezone


def _seed(db, run_id="run-shr-1", namespace="sandbox-abc12-zt-rhelbu"):
    from db.models import EvaluationRecord, EvidenceRecord

    db.add(EvaluationRecord(
        run_id=run_id, stage_id="showroom-healthy", outcome="fail",
        failure_class="showroom_not_ready", lab_code=namespace,
        cluster_name="ocpv-infra01", evaluated_at=datetime.now(timezone.utc),
    ))
    db.add(EvidenceRecord(
        evidence_id="ev-shr-1", run_id=run_id, stage_id="showroom-healthy",
        type="ShowroomHealth", source="test",
        observed={
            "showroom_route_reachable": False,
            "route_url": "https://showroom-abc12.apps.example.com",
            "http_status": 503,
            "error": "HTTP 503",
            "catalog_item": "zt-rhel-bu-lab-developer-cnv",
        },
        result="fail", timestamp=datetime.now(timezone.utc),
    ))
    db.commit()


class TestGetShowroomContext:
    def test_resolves_the_latest_run_in_a_namespace(self, db, monkeypatch):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        _seed(db)

        out = mcp_server.get_showroom_context(namespace="sandbox-abc12-zt-rhelbu")

        assert "https://showroom-abc12.apps.example.com" in out
        assert "503" in out
        assert "zt-rhel-bu-lab-developer-cnv" in out

    def test_run_id_takes_precedence(self, db, monkeypatch):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        _seed(db)

        out = mcp_server.get_showroom_context(run_id="run-shr-1")

        assert "showroom-abc12" in out

    def test_missing_inputs_are_an_error_not_a_crash(self, db, monkeypatch):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)

        assert "ERROR" in mcp_server.get_showroom_context()
