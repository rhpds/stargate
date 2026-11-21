"""The scanner must be able to tell "collected" from "stored".

Persisting used to be gated on ``/health == ok``. ``/health`` reports
``degraded`` for reasons that have nothing to do with the write path — a stale
scanner, an unconfigured LLM, an unreachable sandbox-api — so a namespace could
be collected, evaluated, and then have every record silently discarded while
the cycle reported success. ``live_labs`` then shows the lab as stale or missing,
which reads as "unknown lab" rather than "lost write".
"""

from __future__ import annotations

import json

import cli.stargate as sg


class _Recorder:
    def __init__(self, run_id="run-123", run_error=None):
        self.run_id = run_id
        self.run_error = run_error
        self.calls = []

    def __call__(self, base_url):
        return self

    # The old gate; if anything consults it the test fails loudly.
    def health(self):
        raise AssertionError("persistence must not be gated on /health")

    def create_run(self, **kwargs):
        self.calls.append(("create_run", kwargs))
        if self.run_error:
            return {"error": self.run_error}
        return {"run_id": self.run_id}

    def start_stage(self, run_id, stage_id):
        self.calls.append(("start_stage", stage_id))
        return {}

    def submit_evidence(self, **kwargs):
        return {}

    def evaluate_stage(self, run_id, stage_id, evidence=None):
        return {}

    def complete_run(self, run_id, status):
        self.calls.append(("complete_run", status))
        return {}


def _persist(client, out_format="json"):
    return sg._persist_to_api(
        api_url="http://stargate-api:8090",
        demo_id="demo",
        namespace="sandbox-abc12-zt-rhelbu",
        lab_code="sandbox-abc12-zt-rhelbu",
        cluster_name="ocpv08",
        collected=[],
        results=[{"stage_id": "namespace-ready", "outcome": "pass"}],
        out_format=out_format,
    )


def test_degraded_health_does_not_discard_the_evaluation(monkeypatch):
    """A degraded API still accepts writes; do not throw the result away."""
    client = _Recorder()
    monkeypatch.setattr("cli.api_client.StarGateClient", client)
    monkeypatch.setenv("STARGATE_ADMIN_API_KEY", "")

    run_id, error = _persist(client)

    assert run_id == "run-123"
    assert error is None
    assert client.calls[0][0] == "create_run"
    assert ("complete_run", "completed") in client.calls


def test_unreachable_api_reports_why(monkeypatch):
    client = _Recorder(run_error="connection refused")
    monkeypatch.setattr("cli.api_client.StarGateClient", client)

    run_id, error = _persist(client)

    assert run_id is None
    assert error == "connection refused"


def test_collect_dir_json_says_when_the_write_was_lost(monkeypatch, tmp_path, capsys):
    (tmp_path / "namespace.json").write_text(json.dumps({
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {"name": "sandbox-abc12-zt-rhelbu"},
        "status": {"phase": "Active"},
    }))

    monkeypatch.setattr(sg, "_persist_to_api", lambda **kwargs: (None, "connection refused"))

    rc = sg.main([
        "collect-dir", str(tmp_path),
        "--stages", "namespace-ready",
        "--api-url", "http://stargate-api:8090",
        "--format", "json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0  # the evaluation itself is real; only the write was lost
    assert payload["persisted"] is False
    assert payload["persist_error"] == "connection refused"
    assert payload["results"][0]["stage_id"] == "namespace-ready"


def test_collect_dir_json_says_when_the_write_landed(monkeypatch, tmp_path, capsys):
    (tmp_path / "namespace.json").write_text(json.dumps({
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {"name": "sandbox-abc12-zt-rhelbu"},
        "status": {"phase": "Active"},
    }))

    monkeypatch.setattr(sg, "_persist_to_api", lambda **kwargs: ("run-123", None))

    sg.main([
        "collect-dir", str(tmp_path),
        "--stages", "namespace-ready",
        "--api-url", "http://stargate-api:8090",
        "--format", "json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert payload["persisted"] is True
    assert payload["run_id"] == "run-123"
    assert "persist_error" not in payload


def test_offline_collection_reports_no_persistence_field(tmp_path, capsys):
    """Without --api-url there is nothing to report: no false alarm."""
    (tmp_path / "namespace.json").write_text(json.dumps({
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {"name": "sandbox-abc12-zt-rhelbu"},
        "status": {"phase": "Active"},
    }))

    sg.main(["collect-dir", str(tmp_path), "--stages", "namespace-ready", "--format", "json"])

    payload = json.loads(capsys.readouterr().out)
    assert "persisted" not in payload
