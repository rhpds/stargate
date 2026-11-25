#!/usr/bin/env python3
"""Null stored verdicts that the report text does not substantiate.

The extractor used to fall back to a document-wide scan for a bare enum, and it
parsed the appended model-adjudication summary as if it were the report. Both
invented verdicts for investigations that never stated one: 48 came from the
review block ("Blind reviewer 2: ACTIONABLE (75% model confidence)") and 2 from
upper-case prose ("the PVC is primary — ACTIONABLE").

`_extract_structured_fields` no longer does either, but the fix is forward-only,
so rows written before it keep a verdict the agent never gave. This repairs
them: a stored verdict with no Verdict section that states an enum is set to
null, which is exactly what the writer stores for a verdict-less investigation.

Only `verdict` is touched. `confidence` and `evidence_sufficient` come from the
report and the tool calls and are left as they are. A row whose report states a
different verdict from the stored one is *reported*, never rewritten — that
would be a judgement call no script should make silently.

This must run on an image that has the extraction fix, so it uses the same
parser as the live path; it refuses on an older one.

Usage:
  python3 -m scripts.repair_unsupported_verdicts --dry-run
  python3 -m scripts.repair_unsupported_verdicts --apply --backup /tmp/repair.jsonl

`--apply` writes one JSON line per changed row (id, job_id, before, after) so
the run has a rollback record. The run is idempotent: a second `--apply` changes
nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

BATCH = 200


def repair(db, apply: bool = False, backup=sys.stdout, list_file=None) -> dict:
    from db.models import InvestigationRecord
    from tasks import maintenance

    if not hasattr(maintenance, "_strip_adjudication_summary"):
        raise SystemExit(
            "This image predates the extraction fix; deploy the fix first so the "
            "repair and the live path use the same parser."
        )

    summary = {
        "examined": 0, "with_verdict": 0, "unsupported": 0,
        "disagreed": 0, "changed": 0,
    }
    unsupported_ids, disagreements = [], []

    last_id = 0
    while True:
        rows = (
            db.query(InvestigationRecord)
            .filter(
                InvestigationRecord.status == "complete",
                InvestigationRecord.id > last_id,
            )
            .order_by(InvestigationRecord.id)
            .limit(BATCH)
            .all()
        )
        if not rows:
            break

        for record in rows:
            summary["examined"] += 1
            prior = dict(record.trust_dimensions or {})
            stored = prior.get("verdict")
            if not stored:
                continue
            summary["with_verdict"] += 1

            derived = maintenance._extract_structured_fields(
                record.analysis or ""
            )["verdict"]
            if derived:
                if derived != stored:
                    summary["disagreed"] += 1
                    if len(disagreements) < 10:
                        disagreements.append((record.job_id, stored, derived))
                continue

            summary["unsupported"] += 1
            unsupported_ids.append(record.id)
            if apply:
                updated = dict(prior)
                updated["verdict"] = None
                record.trust_dimensions = updated
                backup.write(json.dumps({
                    "id": record.id,
                    "job_id": record.job_id,
                    "before": prior,
                    "after": updated,
                }) + "\n")
                summary["changed"] += 1

        last_id = rows[-1].id
        # One transaction per batch, matching the backfill: a partial run leaves
        # whole batches committed and the rollback record covers exactly those.
        if apply:
            db.commit()
        else:
            db.rollback()

    if list_file:
        list_file.write("\n".join(str(i) for i in unsupported_ids) + "\n")

    for job_id, stored, derived in disagreements:
        print(
            f"  disagrees (left untouched) {job_id}: stored={stored} derived={derived}",
            file=sys.stderr,
        )
    return summary


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Null stored verdicts that the report text does not substantiate.",
    )
    parser.add_argument("--apply", action="store_true",
                        help="write changes (default is a dry run)")
    parser.add_argument("--dry-run", action="store_true",
                        help="explicitly write nothing (this is the default)")
    parser.add_argument("--backup", default="",
                        help="file for per-row rollback records (apply only; default stdout)")
    parser.add_argument("--list", default="",
                        help="write the affected investigation ids to this file")
    args = parser.parse_args(argv)
    if args.apply and args.dry_run:
        parser.error("--dry-run and --apply are mutually exclusive")

    from db.database import get_session_factory

    db = get_session_factory()()
    try:
        list_fh = open(args.list, "w") if args.list else None
        try:
            if args.apply and args.backup:
                with open(args.backup, "w") as backup_fh:
                    summary = repair(db, apply=True, backup=backup_fh, list_file=list_fh)
            else:
                summary = repair(db, apply=args.apply, list_file=list_fh)
        finally:
            if list_fh:
                list_fh.close()
    finally:
        db.close()

    mode = "applied" if args.apply else "dry run"
    verb = "nulled" if args.apply else "would null"
    print(
        f"{mode}: examined {summary['examined']} complete investigations, "
        f"{summary['with_verdict']} with a verdict, {verb} {summary['unsupported']} "
        f"as unsubstantiated by the report "
        f"({summary['changed']} written, {summary['disagreed']} disagree and were left alone)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
