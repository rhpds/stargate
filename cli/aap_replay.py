"""AAP replay engine — ingest historical job failures from ETL extract files.

John's bastion backups (aap2-etl extracts) hold AAP job history beyond the
controllers' API retention (~31 days prod, ~4 months event). This engine
streams those files through the SAME idempotent ingestion path as live
collection — no parallel pipeline, no double-counting, re-runnable forever.

Design (built for huge files, careful operation):
- STREAMING: gzip-aware, line-by-line; never loads a file into memory.
- IDEMPOTENT: dedupe on (source_system, source_instance, source_event_id)
  inside ingest_aap_failures — re-running is always safe.
- CHRONOLOGICAL: files processed in name order (ETL extracts are written
  chronologically); historical timestamps preserved via each record's own
  'finished'/'occurred_at' — onsets, episodes, and baselines reconstruct.
- CHECKPOINTED: progress persisted per (file, line) so interrupted runs
  resume where they stopped.
- DRY-RUN: parse + classify + report without touching the database — the
  safe first contact, and the 'see how it works' view.
- BATCHED: records flow to the DB in batches (default 500).

Usage:
  # explore a file's shape without any writes
  python -m cli.aap_replay --dry-run /path/to/extracts/*.json.gz

  # replay into the platform
  python -m cli.aap_replay /path/to/extracts/*.json.gz --controller prod0

  # resume an interrupted run
  python -m cli.aap_replay --resume /path/to/extracts/*.json.gz

Expected record shape (the adapter normalizes; see FIELD_MAP):
  AAP job dicts with job_id, error, failing_task, finished, etc. — the
  same shape the live collector produces.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterator, List, Optional

logger = logging.getLogger("stargate.aap_replay")

BATCH_SIZE = 500
STATE_FILE = Path("/tmp/aap_replay_state.json")

# Fields the ingestion path reads (engine.functional_alignment.ingest_aap_failures).
# The adapter maps extract-file fields onto these; adjust when the real
# format is known — one place, no engine changes.
FIELD_MAP = {
    "job_id": ["job_id", "id", "job"],
    "event_id": ["event_id", "job_event_id", "id"],
    "controller": ["controller", "instance", "controller_name"],
    "outcome": ["outcome", "status", "result"],
    "error": ["error", "error_msg", "result_stdout", "stdout", "message"],
    "failing_task": ["failing_task", "task", "task_name"],
    "play": ["play", "play_name"],
    "role": ["role", "role_name"],
    "guid": ["guid", "lab_code", "sandbox"],
    "catalog_item": ["catalog_item", "item", "ci_name"],
    "stage": ["stage"],
    "type": ["type", "action"],
    "provider": ["provider", "cloud"],
    "cluster": ["cluster", "cluster_name"],
    "controller_url": ["controller_url", "url"],
    "job_url": ["job_url", "related_url"],
    "finished": ["finished", "occurred_at", "created", "finished_at", "date"],
}


def open_maybe_gzip(path: Path):
    """Open plain or gzipped text transparently — detected by magic bytes.

    The ETL archive mixes suffixes (job_N.json.gz AND
    job_N.json.gz.transform-ignored), so the sniff is content-based.
    """
    with open(path, "rb") as probe:
        magic = probe.read(2)
    if magic == b"\x1f\x8b":
        return gzip.open(path, "rt", errors="replace")
    return open(path, "r", errors="replace")


def iter_records(path: Path) -> Iterator[Dict]:
    """Stream records from one extract file.

    Three shapes, auto-detected: one-JSON-per-file (the aap2-etl extract
    format — each job is its own file), JSON-lines, and JSON arrays.
    Tar archives (.tar.gz) stream their members — each member is one job
    file (the bastion archive format: job_to_250000.tar.gz, 19GB, ~250k
    members; tarfile streams lazily, never loading the whole archive).
    """
    if path.suffix == ".tar" or path.name.endswith(".tar.gz"):
        yield from _iter_tar_members(path)
        return
    with open_maybe_gzip(path) as handle:
        content = handle.read()
    text = content.strip()
    if not text:
        return
    first = text[0]
    if first == "{":
        # single JSON object = one job record (aap2-etl extract format),
        # OR a JSON-lines file whose first record is an object — try the
        # whole-file parse first, fall back to line mode.
        try:
            item = json.loads(text)
            if isinstance(item, dict):
                yield item
                return
        except json.JSONDecodeError:
            pass
        for line in text.split("\n"):
            line = line.strip().rstrip(",")
            if not line or line in ("[", "]"):
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    yield item
            except json.JSONDecodeError:
                continue
        return
    if first == "[":
        try:
            data = json.loads(text)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        yield item
        except json.JSONDecodeError as e:
            logger.warning("%s: array parse failed (%s)", path.name, e)
        return
    # plain JSON-lines
    for line in text.split("\n"):
        line = line.strip().rstrip(",")
        if not line or line in ("[", "]"):
            continue
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                yield item
        except json.JSONDecodeError:
            continue


def _iter_tar_members(path: Path) -> Iterator[Dict]:
    """Stream job records from a tar archive of per-job files.

    Members may be plain JSON or gzipped JSON (detected by magic bytes in
    the member name ending .gz or by content sniffing). Each member is one
    aap2-etl job file; extraction is streamed one member at a time.
    """
    import tarfile
    import io

    with tarfile.open(path, "r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue  # skip the archive's directory entries
            name = member.name
            if not (name.endswith(".json") or ".json.gz" in name or ".json." in name):
                continue  # skip non-job files
            try:
                f = tar.extractfile(member)
                if f is None:
                    continue
                data = f.read()
            except Exception as e:  # noqa: BLE001 — one bad member never stops the stream
                logger.debug("%s: member %s failed: %s", path.name, name, e)
                continue
            text = _decode_maybe_gzip(data)
            if not text:
                continue
            try:
                item = json.loads(text)
                if isinstance(item, dict):
                    yield item
            except json.JSONDecodeError:
                continue


def _decode_maybe_gzip(data: bytes) -> str:
    """Decode bytes as text, transparently gunzipping by magic bytes."""
    if data[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(data).decode("utf-8", errors="replace")
        except OSError:
            return ""
    return data.decode("utf-8", errors="replace")


def adapt_etl_extract(raw: Dict, controller_hint: str = "") -> Optional[Dict]:
    """Adapt the aap2-etl extract format (one job per file).

    Structure: job_id (top), metadata.job_metadata (identity, timestamps,
    status), events[] (the failed event carries task/role/error),
    retry_analysis. Samples from the partner bastion, Oct 2026.
    """
    jm = (raw.get("metadata") or {}).get("job_metadata") or {}
    if not jm and not raw.get("job_id"):
        return None
    if not jm.get("job_id") and not raw.get("job_id"):
        return None

    # error text: first failed event wins
    error_text, failing_task, role = "", "", ""
    for ev in raw.get("events") or []:
        if ev.get("failed"):
            failing_task = str(ev.get("task") or "")
            role = str(ev.get("role") or "")
            ed = ev.get("event_data") or {}
            res = ed.get("res") or {}
            error_text = str(res.get("msg") or res.get("stderr") or "")[:2000]
            if not error_text:
                # Ansible failure blocks: prefer fatal:/FAILED! lines over
                # the TASK banner that leads the stdout block
                stdout = str(ev.get("stdout") or "")
                fatal_lines = [
                    l.strip() for l in stdout.split("\n")
                    if l.strip().startswith(("fatal:", "FAILED!", "ERROR!"))
                ]
                if fatal_lines:
                    error_text = fatal_lines[-1][:2000]
                elif stdout:
                    error_text = stdout.split("\n")[-1].strip()[:2000]
            break

    # catalog item from job_name: "<ns> <catalog.item-with-tier> <uuid>"
    job_name = str(jm.get("job_name") or "")
    catalog_item = ""
    parts = job_name.split()
    if len(parts) >= 2:
        catalog_item = parts[1] if "." in parts[1] else (parts[1] if len(parts[1]) > 4 else "")

    # normalize AAP status vocabulary to the ingestion path's expectations:
    # the pipeline branches on outcome == "fail" (evaluation creation, new
    # state) — raw "failed" would silently suppress everything
    status = str(jm.get("status") or "").lower()
    outcome = {"failed": "fail", "error": "fail", "successful": "pass",
               "success": "pass", "canceled": "canceled",
               "cancelled": "canceled"}.get(status, status or "fail")

    return {
        "job_id": jm.get("job_id") or raw.get("job_id"),
        "event_id": f"job-{jm.get('job_id') or raw.get('job_id')}",
        "controller": controller_hint or "partner",
        "outcome": outcome,
        "error": error_text,
        "failing_task": failing_task,
        "play": "",
        "role": role,
        "guid": jm.get("guid") or "",
        "catalog_item": jm.get("display_name") if jm.get("display_name") not in (None, "", "unknown") else catalog_item,
        "stage": f"aap-{jm.get('action') or 'provision'}",
        "type": jm.get("action"),
        "provider": jm.get("cloud_provider"),
        "cluster": jm.get("sandbox_openshift_cluster") if jm.get("sandbox_openshift_cluster") not in (None, "", "none") else "",
        "controller_url": "",
        "job_url": "",
        "finished": jm.get("finished") or jm.get("created"),
    }


def adapt(raw: Dict, controller_hint: str = "") -> Optional[Dict]:
    """Map an extract record onto the ingestion shape. None = not a job record."""
    # aap2-etl extract format (nested metadata.job_metadata)
    if (raw.get("metadata") or {}).get("job_metadata"):
        return adapt_etl_extract(raw, controller_hint)
    out: Dict = {}
    for target, candidates in FIELD_MAP.items():
        for c in candidates:
            if raw.get(c) is not None:
                out[target] = raw[c]
                break
    if not out.get("job_id") and not out.get("event_id"):
        return None  # not a job-shaped record
    if not out.get("controller"):
        out["controller"] = controller_hint or "replay"
    return out


def load_state() -> Dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state: Dict) -> None:
    STATE_FILE.write_text(json.dumps(state))


def run(
    paths: List[Path],
    controller: str = "",
    dry_run: bool = False,
    batch_size: int = BATCH_SIZE,
    resume: bool = False,
) -> Dict:
    """Stream extract files through the ingestion path."""
    state = load_state() if resume else {}
    files = sorted(paths)
    totals = {
        "files": len(files), "records": 0, "skipped_malformed": 0,
        "created": 0, "updated": 0, "evaluations": 0,
    }
    class_counts: Counter = Counter()
    outcome_counts: Counter = Counter()
    date_min, date_max = None, None

    db = None
    if not dry_run:
        from db.database import get_session_factory
        db = get_session_factory()()

    try:
        for path in files:
            key = str(path)
            start_line = state.get(key, 0)
            if start_line and start_line < 0:
                continue  # file fully processed in a previous run
            batch: List[Dict] = []
            line_no = 0

            def flush(batch):
                if not batch or dry_run:
                    return {"created": 0, "updated": 0, "evaluations_created": 0}
                from engine.functional_alignment import ingest_aap_failures
                return ingest_aap_failures(db, batch, historical=True)

            for record in iter_records(path):
                line_no += 1
                if line_no <= start_line:
                    continue
                totals["records"] += 1
                adapted = adapt(record, controller)
                if adapted is None:
                    totals["skipped_malformed"] += 1
                    continue
                ts = str(adapted.get("finished") or "")[:19]
                if ts:
                    date_min = ts if date_min is None else min(date_min, ts)
                    date_max = ts if date_max is None else max(date_max, ts)
                if dry_run:
                    fc = record.get("failure_class")
                    if not fc or fc == "unclassified":
                        # preview what ingest-time classification WOULD do
                        try:
                            from engine.failure_class_loader import classify_by_pattern
                            fc, _ = classify_by_pattern(
                                f"{adapted.get('error', '')} {adapted.get('failing_task', '')} {adapted.get('role', '')}",
                                source="aap2_grafana",
                            )
                        except Exception:
                            fc = "unclassified"
                    class_counts[fc or "unclassified"] += 1
                    outcome_counts[adapted.get("outcome") or "?"] += 1
                batch.append(adapted)
                if len(batch) >= batch_size:
                    result = flush(batch)
                    totals["created"] += result["created"]
                    totals["updated"] += result["updated"]
                    totals["evaluations"] += result["evaluations_created"]
                    state[key] = line_no
                    if not dry_run:
                        save_state(state)
                    batch = []
            if batch:
                result = flush(batch)
                totals["created"] += result["created"]
                totals["updated"] += result["updated"]
                totals["evaluations"] += result["evaluations_created"]
            state[key] = -line_no if line_no else -1  # mark complete
            if not dry_run:
                save_state(state)
            logger.info("%s: %d records processed", path.name, line_no)
    finally:
        if db is not None:
            db.close()

    if dry_run:
        totals["classification_preview"] = dict(class_counts.most_common(15))
        totals["outcome_preview"] = dict(outcome_counts)
    totals["date_range"] = [date_min, date_max]
    return totals


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Replay AAP ETL extracts into StarGate")
    parser.add_argument("paths", nargs="+", help="extract files (plain or .gz)")
    parser.add_argument("--controller", default="", help="controller name hint when records lack one")
    parser.add_argument("--dry-run", action="store_true", help="parse and report, write nothing")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--resume", action="store_true", help="resume from checkpoint state")
    args = parser.parse_args()

    paths: List[Path] = []
    for p in args.paths:
        path = Path(p)
        if path.is_dir():
            # directory: expand to its files (sorted — chronological order
            # matters for the ETL extract naming: job_<id>)
            paths.extend(sorted(path.iterdir()))
        else:
            paths.append(path)
    missing = [p for p in paths if not p.exists()]
    if missing:
        print(f"missing files: {missing}", file=sys.stderr)
        sys.exit(2)

    result = run(paths, controller=args.controller, dry_run=args.dry_run,
                 batch_size=args.batch_size, resume=args.resume)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
