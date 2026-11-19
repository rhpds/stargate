"""Runs must close.

98% of production runs were stuck in `running` (541,317 of 551,765) because the
CLI created a run, wrote stages and evidence, and never marked it complete.
MTTR, duration and "last passing run" all depend on this.
"""


def _run(client, run_id="run-close-1"):
    r = client.post("/runs", json={
        "run_id": run_id, "demo_id": "zt-rhelbu",
        "namespace": "sandbox-abc12-zt-rhelbu", "requested_by": "test",
    })
    assert r.status_code in (200, 201), r.text
    return run_id


class TestCompleteRun:
    def test_completing_sets_status_and_timestamp(self, client, db):
        run_id = _run(client)

        r = client.post(f"/runs/{run_id}/complete", json={"status": "completed"})

        assert r.status_code == 200
        from db.models import RunRecord
        row = db.query(RunRecord).filter_by(run_id=run_id).one()
        assert row.status == "completed"
        assert row.completed_at is not None

    def test_failed_status_is_recorded(self, client, db):
        run_id = _run(client, "run-close-2")

        client.post(f"/runs/{run_id}/complete", json={"status": "failed"})

        from db.models import RunRecord
        assert db.query(RunRecord).filter_by(run_id=run_id).one().status == "failed"

    def test_invalid_status_is_rejected(self, client):
        run_id = _run(client, "run-close-3")
        assert client.post(f"/runs/{run_id}/complete", json={"status": "exploded"}).status_code == 400

    def test_unknown_run_is_404(self, client):
        assert client.post("/runs/nope/complete", json={"status": "completed"}).status_code == 404

    def test_requires_admin(self, client):
        run_id = _run(client, "run-close-4")
        r = client.post(f"/runs/{run_id}/complete", json={"status": "completed"},
                        headers={"X-API-Key": ""})
        assert r.status_code in (401, 403)


class TestCliClosesTheRun:
    def test_persist_to_api_completes_the_run(self, monkeypatch):
        from cli import stargate

        calls = []

        class FakeClient:
            def __init__(self, api_url): pass
            def health(self): return True
            def create_run(self, **kwargs): return {"run_id": "run-x"}
            def start_stage(self, run_id, stage_id): calls.append(("start", stage_id))
            def submit_evidence(self, **kwargs): pass
            def evaluate_stage(self, run_id, stage_id, evidence=None):
                calls.append(("eval", stage_id))
            def complete_run(self, run_id, status="completed"):
                calls.append(("complete", status))

        monkeypatch.setattr("cli.api_client.StarGateClient", FakeClient)

        stargate._persist_to_api(
            api_url="http://api", demo_id="zt-rhelbu", namespace="sandbox-x",
            lab_code="sandbox-x", cluster_name="ocpv08", collected=[],
            results=[{"stage_id": "showroom-healthy", "outcome": "fail"}],
            out_format="json",
        )

        assert ("complete", "failed") in calls

    def test_all_pass_completes_not_failed(self, monkeypatch):
        from cli import stargate

        calls = []

        class FakeClient:
            def __init__(self, api_url): pass
            def health(self): return True
            def create_run(self, **kwargs): return {"run_id": "run-y"}
            def start_stage(self, run_id, stage_id): pass
            def submit_evidence(self, **kwargs): pass
            def evaluate_stage(self, run_id, stage_id, evidence=None): pass
            def complete_run(self, run_id, status="completed"):
                calls.append(status)

        monkeypatch.setattr("cli.api_client.StarGateClient", FakeClient)

        stargate._persist_to_api(
            api_url="http://api", demo_id="zt-rhelbu", namespace="sandbox-y",
            lab_code="sandbox-y", cluster_name="ocpv08", collected=[],
            results=[{"stage_id": "showroom-healthy", "outcome": "pass"}],
            out_format="json",
        )

        assert calls == ["completed"]
