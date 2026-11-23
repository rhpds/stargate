"""The scheduler said "Tier 1 (nodes): every 300s" and did not do that.

`WorkerThread._run` is one loop: tick, then sleep `TIER1_INTERVAL`. Tier 3
(namespace evidence) runs *inside* the tick, so the real tier-1 period is
`tick_duration + TIER1_INTERVAL`, not `TIER1_INTERVAL`.

Measured on the live scheduler pod, 2026-11-21 05:59Z to 2026-11-22 03:25Z
(21.4 h), counting dashboard ticks against the pod's age:

    ocpv03   146 ticks   -> ~528 s per tick   (1.8x the configured 300 s)
    ocpv06    95 ticks   -> ~811 s per tick   (2.7x)
    ocpv07    91 ticks   -> ~847 s per tick   (2.8x)

The banner claimed 300 s the whole time and nothing reported the difference.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

from cli.scheduler import WorkerThread, cadence_warning


def test_a_fast_tick_says_nothing():
    assert cadence_warning("ocpv03", 40, 300, 25) is None


def test_a_tick_that_fits_the_interval_is_silent():
    """300 s of work plus a 300 s sleep is 2x — that is already a violation."""
    assert cadence_warning("ocpv03", 0, 300, 25) is None
    assert cadence_warning("ocpv03", 149, 300, 25) is None


def test_crossing_one_and_a_half_times_is_reported():
    """450 s total against a 300 s interval is the last silent point."""
    assert cadence_warning("ocpv06", 150, 300, 25) is None

    message = cadence_warning("ocpv06", 151, 300, 25)

    assert message is not None
    assert "ocpv06" in message
    assert "~451s" in message
    assert "300s" in message


def test_the_live_numbers_reproduce():
    """ocpv07 measured 547 s of work per tick."""
    message = cadence_warning("ocpv07", 547, 300, 25)

    assert message is not None
    assert "~847s" in message
    assert "2.8x" in message
    assert "batch of 25 namespaces" in message


def test_an_unset_interval_is_not_a_division_by_zero():
    assert cadence_warning("ocpv03", 5000, 0, 25) is None


def _stub_worker(cluster="ocpv07", interval=300, batch=25):
    return SimpleNamespace(
        state=SimpleNamespace(name=cluster),
        TIER1_INTERVAL=interval,
        TIER3_BATCH_SIZE=batch,
    )


def test_the_warning_is_rate_limited_to_one_per_half_hour(caplog):
    thread = WorkerThread(_stub_worker(), offset_seconds=0)

    with caplog.at_level(logging.WARNING, logger="stargate.scheduler"):
        thread._report_cadence(547)
        thread._report_cadence(547)
        thread._report_cadence(547)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1, "a standing condition must not flood the log"


def test_the_rate_limit_expires(caplog):
    thread = WorkerThread(_stub_worker(), offset_seconds=0)
    thread._last_cadence_warning = 0.0

    with caplog.at_level(logging.WARNING, logger="stargate.scheduler"):
        thread._report_cadence(547)
        thread._last_cadence_warning -= WorkerThread.CADENCE_WARNING_INTERVAL + 1
        thread._report_cadence(547)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2


def test_a_healthy_tick_never_warns(caplog):
    thread = WorkerThread(_stub_worker(), offset_seconds=0)

    with caplog.at_level(logging.WARNING, logger="stargate.scheduler"):
        thread._report_cadence(40)
        thread._report_cadence(41)

    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []
