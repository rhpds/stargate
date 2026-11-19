#!/usr/bin/env python3
"""Weekly precision digest — a document about the numbers.

RAG over live tables produces confident fiction, so the numbers stay behind
tools (`get_failure_precision`). What is safe to index is a *narrative* of the
week: which classes fired, how much of it self-resolved, and what moved.

Writes docs/generated/precision/<year>-W<week>.md and a stable latest.md that
the `ask` corpus indexes.

Usage:
  python3 -m scripts.precision_digest            # last full week + previous
  python3 -m scripts.precision_digest --dry-run  # print without writing
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

from engine.precision_digest import build_digest

OUTPUT_DIR = Path(__file__).parent.parent / "docs" / "generated" / "precision"

def write_digest(markdown: str, generated_at: datetime, dry_run: bool = False) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    week = generated_at.strftime("%G-W%V")
    path = OUTPUT_DIR / f"{week}.md"
    latest = OUTPUT_DIR / "latest.md"
    if not dry_run:
        path.write_text(markdown)
        latest.write_text(markdown)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weeks-back", type=int, default=0,
                        help="0 = the last seven days; 1 = the week before, etc.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from db.database import background_session
    from db.repository import failure_precision

    now = datetime.now(timezone.utc)
    window_end = now - timedelta(weeks=args.weeks_back)
    window_start = window_end - timedelta(days=7)
    previous_start = window_start - timedelta(days=7)

    with background_session() as db:
        current = failure_precision(db, since=window_start, until=window_end)
        previous = failure_precision(db, since=previous_start, until=window_start)

    markdown = build_digest(current, previous, window_end)
    if args.dry_run:
        print(markdown)
        return 0
    path = write_digest(markdown, window_end)
    print(f"wrote {path} and latest.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
