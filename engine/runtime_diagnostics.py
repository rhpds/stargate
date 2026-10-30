"""Opt-in, payload-free stage timings; no snapshots, background tasks, or I/O clients.

STARGATE_RUNTIME_TIMING defaults off. Each stage emits at most two records and
retains no history. Thread CPU is a stage-thread counter, not process CPU or
proof of why a stage waited. Diagnostics never impose application deadlines.
"""
import logging
import os
import time
from contextlib import contextmanager

from engine.memory_diagnostics import resident_bytes

logger = logging.getLogger("stargate.runtime")
_STAGES = frozenset({
    "startup.database", "startup.catalog", "startup.consumers",
    "warm.inventory", "warm.aap_collection", "warm.aap_ingestion", "warm.summit",
    "refresh.clusters", "refresh.pipeline", "refresh.labs",
})


def _sample():
    return time.monotonic(), time.thread_time(), resident_bytes()


def _safe_sample():
    try:
        return _sample()
    except Exception:
        return None


def _emit(message, *values):
    try:
        # Alembic may disable existing loggers during startup.
        logger.disabled = False
        logger.info(message, *values)
    except Exception:
        pass  # Observability must not change work or mask its exception.


@contextmanager
def diagnostic_stage(stage):
    if os.environ.get("STARGATE_RUNTIME_TIMING", "false").lower() != "true":
        yield
        return
    name = stage if isinstance(stage, str) and stage in _STAGES else "other"
    before = _safe_sample()
    if before is not None:
        _emit("runtime phase=begin stage=%s monotonic_ms=%.3f rss_bytes=%d",
              name, before[0] * 1000, before[2])
    status = "ok"
    try:
        yield
    except BaseException:
        status = "error"
        raise
    finally:
        after = _safe_sample()
        if before is not None and after is not None:
            _emit("runtime phase=end stage=%s status=%s wall_ms=%.3f thread_cpu_ms=%.3f rss_before_bytes=%d rss_after_bytes=%d",
                  name, status, (after[0]-before[0]) * 1000,
                  (after[1]-before[1]) * 1000, before[2], after[2])
