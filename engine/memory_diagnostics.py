"""Opt-in allocation counters; never log request bodies, locals, or evidence."""
import logging
import os
import threading
import tracemalloc
from pathlib import Path

logger = logging.getLogger("stargate.memory")


def resident_bytes():
    """Read current Linux RSS, not the lifetime high-water mark."""
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def log_memory_sample():
    current, peak = tracemalloc.get_traced_memory()
    rss = resident_bytes()
    logger.info("memory rss_bytes=%d python_bytes=%d python_peak_bytes=%d", rss, current, peak)
    if rss >= 768 * 1024 * 1024:
        # Statistics contain only source locations and sizes, never object data.
        stats = tracemalloc.take_snapshot().statistics("lineno")[:10]
        for stat in stats:
            frame = stat.traceback[0]
            logger.info("allocation file=%s line=%d bytes=%d count=%d",
                        frame.filename, frame.lineno, stat.size, stat.count)


def start_memory_diagnostics(shutdown_event):
    if os.environ.get("STARGATE_MEMORY_DIAGNOSTICS", "false").lower() != "true":
        return
    if not tracemalloc.is_tracing():
        tracemalloc.start(1)
    logger.disabled = False

    def monitor():
        while not shutdown_event.is_set():
            try:
                log_memory_sample()
            except Exception:
                logger.warning("Memory sampling failed", exc_info=False)
            if shutdown_event.wait(300):
                break

    threading.Thread(target=monitor, name="memory-diagnostics", daemon=True).start()
