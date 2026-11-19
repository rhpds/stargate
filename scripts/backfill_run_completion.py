#!/usr/bin/env python3
"""Close historical runs that were never completed.

Before Nov 19 the CLI and the tier-1 worker created runs but never posted a
completion, so ~551k rows sat in `running`. This backfills them from their own
evaluations: `completed_at` = the last evaluation, status = failed if any stage
failed. A run with no evaluations is left alone unless --status-only is given,
because inventing a completion time is worse than admitting we do not know it.

Usage:
  python3 -m scripts.backfill_run_completion --dry-run
  python3 -m scripts.backfill_run_completion --batch-size 10000
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func


def backfill(
    db,
    older_than_hours: int = 24,
    batch_size: int = 10000,
    limit: int = 0,
    status_only: bool = False,
    dry_run: bool = False,
) -> dict:
    from db.models import EvaluationRecord, RunRecord

    cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    updated = skipped = 0
    last_id = 0

    while True:
        batch = (
            db.query(RunRecord)
            .filter(
                RunRecord.status == "running",
                RunRecord.started_at < cutoff,
                RunRecord.id > last_id,
            )
            .order_by(RunRecord.id)
            .limit(batch_size)
            .all()
        )
        if not batch:
            break

        run_ids = [run.run_id for run in batch]
        aggregates = {
            run_id: (last_eval, failures or 0)
            for run_id, last_eval, failures in (
                db.query(
                    EvaluationRecord.run_id,
                    func.max(EvaluationRecord.evaluated_at),
                    func.sum(case((EvaluationRecord.outcome == "fail", 1), else_=0)),
                )
                .filter(EvaluationRecord.run_id.in_(run_ids))
                .group_by(EvaluationRecord.run_id)
                .all()
            )
        }

        for run in batch:
            if run.run_id in aggregates:
                last_eval, failures = aggregates[run.run_id]
                run.status = "failed" if failures else "completed"
                run.completed_at = last_eval
                updated += 1
            elif status_only:
                run.status = "completed"
                run.completed_at = None
                updated += 1
            else:
                skipped += 1

        last_id = batch[-1].id
        if not dry_run:
            db.commit()
        if limit and updated + skipped >= limit:
            break

    if dry_run:
        db.rollback()
    return {"updated": updated, "skipped_no_evaluations": skipped, "dry_run": dry_run}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--older-than-hours", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=10000)
    parser.add_argument("--limit", type=int, default=0, help="stop after N runs (0 = all)")
    parser.add_argument("--status-only", action="store_true",
                        help="also close runs with no evaluations (completed_at stays NULL)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from db.database import background_session
    with background_session() as db:
        report = backfill(
            db,
            older_than_hours=args.older_than_hours,
            batch_size=args.batch_size,
            limit=args.limit,
            status_only=args.status_only,
            dry_run=args.dry_run,
        )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
