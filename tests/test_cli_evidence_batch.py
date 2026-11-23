"""Evidence is batched for transport, not for the rubric.

A 55-user CNV namespace produces 165 evidence rows (3 stages x 55 objects) and
each row used to be its own POST. The rows that land, and every rubric input
built from them, must stay identical; only the number of round trips and
commits changes. These tests pin the client half of that contract, including
the fallbacks that keep a deploy skew from costing a stage's evidence.
"""

from __future__ import annotations

import cli.stargate as sg
from collectors.openshift.collect_resource_state import CollectedEvidence


class _BatchClient:
    def __init__(self, batch_error=None, batch_failures=0, single_error=None):
        self.batch_error = batch_error
        self.batch_failures = batch_failures
        self.single_error = single_error
        self.batch_calls = []
        self.single_calls = []
        self.started = []
        self.evaluated = []
        self.completed = None

    # --- the transport under test ---

    def submit_evidence_batch(self, run_id, stage_id, items):
        self.batch_calls.append((run_id, stage_id, items))
        if self.batch_error:
            return {"error": self.batch_error}
        created = len(items) - self.batch_failures
        return {
            "created": created,
            "evidence_ids": [f"ev-{i}" for i in range(created)],
            "failed": [{"index": i} for i in range(self.batch_failures)],
        }

    def submit_evidence(self, run_id, stage_id, evidence_type, source, observed, result):
        self.single_calls.append({
            "run_id": run_id,
            "stage_id": stage_id,
            "type": evidence_type,
            "source": source,
            "observed": observed,
            "result": result,
        })
        if self.single_error:
            return {"error": self.single_error}
        return {"evidence_id": "ev-single"}

    # --- the rest of the persist flow ---

    def create_run(self, **kwargs):
        return {"run_id": "run-batch"}

    def start_stage(self, run_id, stage_id):
        self.started.append(stage_id)
        return {}

    def evaluate_stage(self, run_id, stage_id, evidence=None):
        self.evaluated.append(stage_id)
        return {}

    def complete_run(self, run_id, status):
        self.completed = status
        return {}


def _payloads(count):
    return [
        {
            "type": "pod",
            "source": "oc",
            "observed": {"index": i},
            "result": "pass",
            "timestamp": "2026-11-23T22:00:00+00:00",
        }
        for i in range(count)
    ]


def _collected(count):
    return [
        CollectedEvidence(
            resource_kind="pod",
            resource_name=f"user{i}",
            namespace="sandbox-abc12-zt-rhelbu",
            observed={"index": i},
        )
        for i in range(count)
    ]


# --- _evidence_batch_size -------------------------------------------------

def test_batch_size_default_is_100(monkeypatch):
    monkeypatch.delenv("STARGATE_EVIDENCE_BATCH", raising=False)
    assert sg._evidence_batch_size() == sg._DEFAULT_EVIDENCE_BATCH


def test_batch_size_zero_is_the_legacy_path(monkeypatch):
    monkeypatch.setenv("STARGATE_EVIDENCE_BATCH", "0")
    assert sg._evidence_batch_size() == 0


def test_batch_size_is_clamped_to_the_api_cap(monkeypatch):
    """A value the API would reject must not turn into a failed request."""
    monkeypatch.setenv("STARGATE_EVIDENCE_BATCH", "5000")
    assert sg._evidence_batch_size() == sg._MAX_EVIDENCE_BATCH


def test_batch_size_bad_value_falls_back(monkeypatch):
    """A typo in the kill switch must not stop evidence collection."""
    monkeypatch.setenv("STARGATE_EVIDENCE_BATCH", "lots")
    assert sg._evidence_batch_size() == sg._DEFAULT_EVIDENCE_BATCH


# --- _submit_evidence_rows ------------------------------------------------

def test_a_stage_travels_in_one_request():
    client = _BatchClient()
    created, failed = sg._submit_evidence_rows(
        client, "run-1", "namespace-ready", _payloads(55), 100
    )

    assert (created, failed) == (55, 0)
    assert len(client.batch_calls) == 1
    assert len(client.batch_calls[0][2]) == 55
    assert client.single_calls == []


def test_large_stages_chunk_to_the_batch_size():
    client = _BatchClient()
    created, failed = sg._submit_evidence_rows(
        client, "run-1", "namespace-ready", _payloads(165), 100
    )

    assert (created, failed) == (165, 0)
    assert [len(call[2]) for call in client.batch_calls] == [100, 65]


def test_batch_size_one_posts_each_row():
    client = _BatchClient()
    created, failed = sg._submit_evidence_rows(
        client, "run-1", "namespace-ready", _payloads(3), 1
    )

    assert (created, failed) == (3, 0)
    assert client.batch_calls == []
    assert [c["observed"]["index"] for c in client.single_calls] == [0, 1, 2]


def test_transport_error_falls_back_to_one_post_per_row():
    """An API without the endpoint (deploy skew) must not cost evidence."""
    client = _BatchClient(batch_error="HTTP Error 404: Not Found")
    created, failed = sg._submit_evidence_rows(
        client, "run-1", "namespace-ready", _payloads(4), 100
    )

    assert (created, failed) == (4, 0)
    assert len(client.batch_calls) == 1
    assert len(client.single_calls) == 4
    # the per-row payload keeps the API field names
    assert client.single_calls[0]["type"] == "pod"
    assert client.single_calls[0]["result"] == "pass"


def test_server_reported_failures_are_counted_not_hidden():
    client = _BatchClient(batch_failures=2)
    created, failed = sg._submit_evidence_rows(
        client, "run-1", "namespace-ready", _payloads(55), 100
    )

    assert (created, failed) == (53, 2)


def test_per_row_transport_errors_are_counted():
    client = _BatchClient(batch_error="connection refused", single_error="connection refused")
    created, failed = sg._submit_evidence_rows(
        client, "run-1", "namespace-ready", _payloads(3), 100
    )

    assert (created, failed) == (0, 3)


# --- _persist_to_api end to end ------------------------------------------

def test_three_stages_of_55_rows_make_three_requests(monkeypatch):
    client = _BatchClient()
    monkeypatch.setattr("cli.api_client.StarGateClient", lambda base_url: client)
    monkeypatch.delenv("STARGATE_EVIDENCE_BATCH", raising=False)

    run_id, error = sg._persist_to_api(
        api_url="http://stargate-api:8090",
        demo_id="demo",
        namespace="sandbox-abc12-zt-rhelbu",
        lab_code="sandbox-abc12-zt-rhelbu",
        cluster_name="ocpv08",
        collected=_collected(55),
        results=[
            {"stage_id": stage, "outcome": "pass"}
            for stage in ("namespace-ready", "build-ready", "platform-ready")
        ],
        out_format="json",
    )

    assert (run_id, error) == ("run-batch", None)
    # 165 rows, 3 requests — the count the batched transport replaces 165 of
    assert [len(call[2]) for call in client.batch_calls] == [55, 55, 55]
    assert client.single_calls == []
    # the batch payload is the API contract, not the domain object
    assert set(client.batch_calls[0][2][0]) == {"type", "source", "observed", "result", "timestamp"}
    assert client.started == ["namespace-ready", "build-ready", "platform-ready"]
    assert client.evaluated == client.started
    assert client.completed == "completed"


def test_no_collected_objects_makes_no_evidence_request(monkeypatch):
    client = _BatchClient()
    monkeypatch.setattr("cli.api_client.StarGateClient", lambda base_url: client)

    run_id, error = sg._persist_to_api(
        api_url="http://stargate-api:8090",
        demo_id="demo",
        namespace="ns",
        lab_code=None,
        cluster_name=None,
        collected=[],
        results=[{"stage_id": "namespace-ready", "outcome": "pass"}],
        out_format="json",
    )

    assert error is None
    assert client.batch_calls == []
    assert client.single_calls == []
    assert client.evaluated == ["namespace-ready"]
