"""Tests for the AAP replay engine (cli/aap_replay.py).

The engine streams John's bastion ETL extracts (gzip or plain, JSON lines
or arrays) through the same idempotent ingestion path as live collection.
"""

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from cli.aap_replay import adapt, iter_records, run


def _write_jsonl(path: Path, records):
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _write_jsonl_gz(path: Path, records):
    with gzip.open(path, "wt") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def test_iter_records_jsonl_plain_and_gz(tmp_path):
    records = [{"job_id": 1, "error": "x"}, {"job_id": 2, "error": "y"}]
    plain = tmp_path / "extract.jsonl"
    zipped = tmp_path / "extract.jsonl.gz"
    _write_jsonl(plain, records)
    _write_jsonl_gz(zipped, records)
    assert list(iter_records(plain)) == records
    assert list(iter_records(zipped)) == records


def test_iter_records_json_array(tmp_path):
    records = [{"job_id": 1}, {"job_id": 2}]
    arr = tmp_path / "extract.json"
    arr.write_text(json.dumps(records))
    assert list(iter_records(arr)) == records


def test_iter_records_skips_malformed_lines(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"job_id": 1}\nnot json\n{"job_id": 2}\n\n')
    out = list(iter_records(p))
    assert len(out) == 2


def test_adapt_maps_fields():
    raw = {"id": 4242, "result_stdout": "Fatal: timeout", "task_name": "Wait for CSV",
           "finished": "2025-06-15T10:00:00Z", "ci_name": "some-lab"}
    adapted = adapt(raw, controller_hint="prod0")
    assert adapted["job_id"] == 4242
    assert adapted["event_id"] == 4242
    assert adapted["controller"] == "prod0"
    assert adapted["error"] == "Fatal: timeout"
    assert adapted["failing_task"] == "Wait for CSV"
    assert adapted["catalog_item"] == "some-lab"
    assert adapted["finished"] == "2025-06-15T10:00:00Z"


def test_adapt_rejects_non_job_records():
    assert adapt({"summary": "not a job"}) is None


def test_dry_run_reports_without_writing(tmp_path, monkeypatch):
    """Dry-run parses, counts, previews classifications — no DB touched."""
    monkeypatch.setattr("cli.aap_replay.STATE_FILE", tmp_path / "state.json")
    records = [
        {"job_id": 1, "error": "InsufficientInstanceCapacity", "finished": "2025-06-01T00:00:00Z"},
        {"job_id": 2, "error": "Connection refused", "finished": "2025-06-02T00:00:00Z"},
        {"not": "a job"},
    ]
    f = tmp_path / "extract.jsonl"
    _write_jsonl(f, records)

    result = run([f], controller="prod0", dry_run=True)
    assert result["records"] == 3
    assert result["skipped_malformed"] == 1
    assert result["date_range"] == ["2025-06-01T00:00:00", "2025-06-02T00:00:00"]
    assert result["created"] == 0  # nothing written


def test_replay_ingests_idempotently(tmp_path, monkeypatch):
    """Full replay through the real ingestion path, then re-run → all updates."""
    monkeypatch.setattr("cli.aap_replay.STATE_FILE", tmp_path / "state.json")
    records = [
        {"job_id": i, "error": "Connection refused", "failing_task": "do thing",
         "finished": "2025-06-15T10:00:00Z", "guid": f"lab-{i}"}
        for i in range(1, 6)
    ]
    f = tmp_path / "extract.jsonl"
    _write_jsonl(f, records)

    from db.database import Base
    from tests.conftest import TestSession, test_engine
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()

    import cli.aap_replay as replay_mod
    monkeypatch.setattr(
        "db.database.get_session_factory", lambda: (lambda: db))

    result = run([f], controller="prod0", dry_run=False)
    assert result["records"] == 5
    assert result["created"] == 5
    assert result["evaluations"] == 5

    # verify DB state: source_events with historical occurred_at
    from db.models import SourceEvent, EvaluationRecord
    events = db.query(SourceEvent).filter_by(source_instance="prod0").all()
    assert len(events) == 5
    assert all(e.occurred_at is not None for e in events)
    assert events[0].occurred_at.year == 2025  # historical timestamp preserved
    evals = db.query(EvaluationRecord).filter(EvaluationRecord.source_event_id.isnot(None)).all()
    assert len(evals) == 5
    # historical mode: evaluations land in the JOB's period, not replay day
    assert all(e.evaluated_at.year == 2025 for e in evals)

    # re-run WITHOUT resume → same records, zero new creates (idempotent)
    result2 = run([f], controller="prod0", dry_run=False)
    assert result2["records"] == 5
    assert result2["created"] == 0
    assert result2["updated"] == 5

    db.rollback()
    db.close()
    Base.metadata.drop_all(bind=test_engine)


def test_outcome_vocabulary_normalized():
    """AAP statuses (failed/successful/canceled) must normalize to the
    ingestion path's fail/pass vocabulary — raw 'failed' silently
    suppresses evaluation creation (found live during the partner replay)."""
    from cli.aap_replay import adapt_etl_extract
    for status, expected in (("failed", "fail"), ("error", "fail"),
                             ("successful", "pass"),
                             ("canceled", "canceled"), ("cancelled", "canceled")):
        raw = {"job_id": 1, "metadata": {"job_metadata": {"job_id": 1, "status": status}}}
        a = adapt_etl_extract(raw, "partner")
        assert a["outcome"] == expected, f"{status} → {a['outcome']}, want {expected}"


def test_gzip_detected_by_magic_not_suffix(tmp_path):
    """ETL names mix suffixes (job_N.json.gz.transform-ignored) — gzip must
    be detected by magic bytes, not the filename."""
    import gzip as gz
    record = '{"job_id": 7, "metadata": {"job_metadata": {"job_id": 7, "status": "failed"}}}'
    weird = tmp_path / "job_7.json.gz.transform-ignored"
    with gz.open(weird, "wt") as f:
        f.write(record)
    out = list(iter_records(weird))
    assert len(out) == 1 and out[0]["job_id"] == 7
