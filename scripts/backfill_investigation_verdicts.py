#!/usr/bin/env python3
"""Re-derive verdict, confidence and evidence sufficiency for stored investigations.

The extractor used to require the verdict word to sit directly beside
"Verdict", so the agent's dominant output shape —

    ### 6. Verdict

    > **TRANSIENT**

— produced a NULL verdict on about 45% of investigations. The fix in
`tasks/maintenance.py` is forward-only, so those rows stay NULL and the things
that read the verdict stay blind for them: learned suppression (needs three
TRANSIENT), tri-state reporting, and the Slack transient filter.

This backfills from data already stored, and only from that:

- `analysis`   -> verdict, confidence (same parser as the live path)
- `tool_calls` -> evidence_sufficient (same predicate as the live path)

Nothing is invented. A row whose analysis contains no verdict stays NULL. A
field that already holds a value is never overwritten, and rows that already
carry a verdict are not in scope at all, so the run is idempotent and narrow.

Usage:
  python3 -m scripts.backfill_investigation_verdicts --dry-run
  python3 -m scripts.backfill_investigation_verdicts --apply --backup /tmp/verdicts.jsonl

`--apply` prints one JSON line per changed row (id, job_id, before, after)
before writing it, so the run has a rollback record without needing a new
table. Point `--backup` at a file to keep that record; without it the lines go
to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

BATCH = 200


def _needs_backfill(investigation) -> bool:
    """Only rows with no verdict. Everything else is left exactly as it was."""
    return not (investigation.trust_dimensions or {}).get("verdict")


def backfill(
    db,
    apply: bool = False,
    limit: int = 0,
    batch_size: int = BATCH,
    backup=sys.stdout,
) -> dict:
    from db.models import InvestigationRecord
    from engine.investigation_agent import _evidence_sufficient
    from tasks.maintenance import _extract_structured_fields

    summary = {
        "examined": 0, "scanned": 0, "verdict": 0, "confidence": 0,
        "evidence": 0, "changed": 0,
    }

    last_id = 0
    while limit == 0 or summary["examined"] < limit:
        room = batch_size if limit == 0 else min(batch_size, limit - summary["examined"])
        rows = (
            db.query(InvestigationRecord)
            .filter(
                InvestigationRecord.status == "complete",
                InvestigationRecord.id > last_id,
            )
            .order_by(InvestigationRecord.id)
            .limit(room)
            .all()
        )
        if not rows:
            break

        for record in rows:
            summary["examined"] += 1
            if not _needs_backfill(record):
                continue
            summary["scanned"] += 1

            fields = _extract_structured_fields(record.analysis or "")
            prior = dict(record.trust_dimensions or {})
            updated = dict(prior)

            if fields.get("verdict"):
                updated["verdict"] = fields["verdict"]
                summary["verdict"] += 1
            if updated.get("confidence") is None and fields.get("confidence") is not None:
                updated["confidence"] = fields["confidence"]
                summary["confidence"] += 1

            derived_evidence = _evidence_sufficient(
                record.failure_class or "", record.tool_calls or []
            )
            if bool(prior.get("evidence_sufficient")) != derived_evidence:
                updated["evidence_sufficient"] = derived_evidence
                summary["evidence"] += 1

            if updated == prior:
                continue

            summary["changed"] += 1
            if apply:
                backup.write(json.dumps({
                    "id": record.id,
                    "job_id": record.job_id,
                    "before": prior,
                    "after": updated,
                }) + "\n")
                record.trust_dimensions = updated
            elif summary["changed"] <= 5:
                print(
                    f"  would set {record.job_id}: verdict={updated.get('verdict')!r} "
                    f"confidence={updated.get('confidence')!r} "
                    f"evidence_sufficient={updated.get('evidence_sufficient')}",
                    file=sys.stderr,
                )

        last_id = rows[-1].id
        # One transaction per batch: a partial run leaves whole batches
        # committed, and the rollback file covers exactly those.
        if apply:
            db.commit()
        else:
            db.rollback()

    return summary


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-derive verdict/confidence/evidence for stored investigations.",
    )
    parser.add_argument("--apply", action="store_true", help="write changes (default is a dry run)")
    parser.add_argument("--dry-run", action="store_true",
                        help="explicit dry run; the default, and refused together with --apply")
    parser.add_argument("--limit", type=int, default=0,
                        help="examine at most N complete investigations (0 = all)")
    parser.add_argument("--batch-size", type=int, default=BATCH,
                        help=f"rows per transaction (default {BATCH})")
    parser.add_argument("--backup", default="",
                        help="file for per-row rollback records (apply only; default stdout)")
    args = parser.parse_args(argv)

    if args.dry_run and args.apply:
        parser.error("--dry-run and --apply are mutually exclusive")

    from db.database import get_session_factory

    db = get_session_factory()()
    try:
        if args.apply and args.backup:
            with open(args.backup, "w") as fh:
                summary = backfill(db, apply=True, limit=args.limit,
                                   batch_size=args.batch_size, backup=fh)
        else:
            summary = backfill(db, apply=args.apply, limit=args.limit,
                               batch_size=args.batch_size)
    finally:
        db.close()

    mode = "applied" if args.apply else "dry run"
    print(
        f"{mode}: examined {summary['examined']} complete investigations, "
        f"{summary['scanned']} without a verdict, {summary['changed']} changed "
        f"(verdict {summary['verdict']}, confidence {summary['confidence']}, "
        f"evidence_sufficient {summary['evidence']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
