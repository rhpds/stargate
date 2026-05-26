"""Shared helpers for API routers."""

import time
from pathlib import Path
from typing import Dict, Optional

from api.app.models import Rubric
from api.app.rubric_loader import load_rubrics_from_directory, RubricLoadError

RUBRIC_DIR = Path(__file__).parent.parent.parent.parent / "rubrics" / "platform"

_rubric_cache: Dict[str, Rubric] = {}
_rubric_cache_ts: float = 0
_RUBRIC_CACHE_TTL: int = 300


def load_rubric_for_stage(stage_id: str) -> Optional[Rubric]:
    global _rubric_cache_ts
    if not _rubric_cache or (time.time() - _rubric_cache_ts > _RUBRIC_CACHE_TTL):
        _load_all_rubrics()
        _rubric_cache_ts = time.time()
    return _rubric_cache.get(stage_id)


def _load_all_rubrics():
    _rubric_cache.clear()
    if not RUBRIC_DIR.is_dir():
        return
    try:
        rubrics = load_rubrics_from_directory(RUBRIC_DIR)
        for r in rubrics:
            _rubric_cache[r.stage] = r
    except RubricLoadError:
        pass
