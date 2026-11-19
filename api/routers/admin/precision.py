"""Admin: generate the weekly failure-precision digest for the RAG corpus."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.routers._shared import require_admin
from db.database import get_db

router = APIRouter()


@router.post("/admin/precision-digest")
def generate_precision_digest(
    weeks_back: int = 0,
    db: Session = Depends(get_db),
    _auth=Depends(require_admin),
):
    """Build the digest for one week (0 = the last seven days) and store it.

    Stored rather than written to disk: the corpus reads the latest row, so it
    survives pod restarts and deploys.
    """
    from db import repository
    from engine.precision_digest import build_digest

    now = datetime.now(timezone.utc)
    window_end = now - timedelta(weeks=weeks_back)
    window_start = window_end - timedelta(days=7)

    current = repository.failure_precision(db, since=window_start, until=window_end)
    previous = repository.failure_precision(
        db, since=window_start - timedelta(days=7), until=window_start
    )
    markdown = build_digest(current, previous, window_end)
    period = window_end.strftime("%G-W%V")
    repository.save_precision_digest(db, period, markdown, generated_at=now)

    return {
        "period": period,
        "classes": current["summary"]["classes"],
        "evaluations": current["summary"]["evaluations"],
    }
