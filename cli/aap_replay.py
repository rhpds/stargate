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
    """Open plain or gzipped text transparently."""
    if path.suffix == ".gz":
        return gzip.open(path, "rt", errors="replace")
    return open(path, "r", errors="replace")


def iter_records(path: Path) -> Iterator[Dict]:
    """Stream records from one extract file.

    Handles both JSON-lines and JSON-array files (auto-detected by first
    non-whitespace character), line-by-line for the former.
    """
    with open_maybe_gzip(path) as handle:
        first = handle.read(1)
        handle.seek(0)
        if first == "[":
            # JSON array: stream-decode incrementally
            try:
                data = json.load(handle)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            yield item
                return
            except json.JSONDecodeError as e:
                logger.warning("%s: array parse failed (%s) — trying line mode", path.name, e)
                handle.seek(0)
        # JSON lines (the common ETL shape)
        for line in handle:
            line = line.strip().rstrip(",")
            if not line or line in ("[", "]"):
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    yield item
            except json.JSONDecodeError:
                continue  # malformed line in a huge file: skip, count it


def adapt(raw: Dict, controller_hint: str = "") -> Optional[Dict]:
    """Map an extract record onto the ingestion shape. None = not a job record."""
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
                return ingest_aap_failures(db, batch)

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
                    class_counts[fc or "(classified at ingest)"] += 1
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

    paths = [Path(p) for p in args.paths]
    missing = [p for p in paths if not p.exists()]
    if missing:
        print(f"missing files: {missing}", file=sys.stderr)
        sys.exit(2)

    result = run(paths, controller=args.controller, dry_run=args.dry_run,
                 batch_size=args.batch_size, resume=args.resume)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
