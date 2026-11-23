"""Tier 3 inside the tier-1 tick could not get faster, only the tick could.

Measured on the live scheduler on 2026-11-23, after a CPU limit change halved
per-namespace cost on every cluster:

    ocpv07  c 33.8 s -> 17.1 s      tier-3 tick 1,084 s -> 744 s
    throughput 83/h -> 121/h        (1.46x from a 2x gain in `c`)

The missing half was the 300 s sleep at the end of every tick: 40% of the
744 s cycle. `--tier3-independent` takes tier 3 out of that loop, so the
cadence becomes max(TIER3_INTERVAL, batch duration) and the sweep stops paying
for a sleep it does not use.

Default is off: `tick()` still runs tier 3, so a deployment that does not pass
the flag behaves exactly as before.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import cli.scheduler as scheduler_module
from cli.scheduler import Scheduler, WorkerThread, tier3_sleep
from cli.worker import ClusterWorker


class _CountingWorker:
    """Stands in for ClusterWorker; records which tiers actually ran."""

    TIER1_INTERVAL = 300
    TIER2_INTERVAL = 300
    TIER3_INTERVAL = 600
    TIER3_BATCH_SIZE = 25
    TIER3_INDEPENDENT = False

    def __init__(self, name="ocpv07"):
        self.state = SimpleNamespace(
            name=name,
            last_node_scan=0,
            last_pod_scan=0,
            last_ns_scan=0,
            scan_count=0,
        )
        self.last_tier3_result = None
        self.tick_calls = 0

    def tick(self):
        self.tick_calls += 1
        return {"cluster": self.state.name, "tiers_run": []}

    def run_tier3_batch(self):
        self.last_tier3_result = {"batch_size": self.TIER3_BATCH_SIZE}
        return self.last_tier3_result


def _worker_with_tier3(monkeypatch):
    """A real ClusterWorker with collection stubbed out."""
    worker = ClusterWorker.__new__(ClusterWorker)
    calls = []

    def fake_tier3():
        calls.append(1)
        return {"batch_size": 25, "persisted": 25}

    worker._tier3_namespaces = fake_tier3
    worker.state = SimpleNamespace(name="ocpv07", last_node_scan=0, last_pod_scan=0,
                                   last_ns_scan=0, scan_count=0)
    worker.last_tier3_result = None
    return worker, calls


def test_default_tick_still_runs_tier3():
    """Off by default: nothing changes for a deployment that does not opt in."""
    worker, calls = _worker_with_tier3(None)
    worker.TIER3_INTERVAL = 0  # gate open
    worker.TIER1_INTERVAL = 10**9  # do not run tiers 1/2 in this test
    worker.TIER2_INTERVAL = 10**9
    worker.state.last_node_scan = time.time()
    worker.state.last_pod_scan = time.time()

    assert worker.TIER3_INDEPENDENT is False
    worker.tick()

    assert len(calls) == 1, "without the flag tier 3 must stay inside the tick"


def test_independent_tick_does_not_run_tier3():
    worker, calls = _worker_with_tier3(None)
    worker.TIER3_INTERVAL = 0
    worker.TIER1_INTERVAL = 10**9
    worker.TIER2_INTERVAL = 10**9
    worker.state.last_node_scan = time.time()
    worker.state.last_pod_scan = time.time()
    worker.TIER3_INDEPENDENT = True

    worker.tick()

    assert calls == [], "the tick must not double-run a batch owned by another thread"


def test_run_tier3_batch_stamps_the_start_time():
    """`last_ns_scan` is stamped from the batch start, as tick() did with `now`."""
    worker, calls = _worker_with_tier3(None)
    worker.state.last_ns_scan = 0

    result = worker.run_tier3_batch()

    assert result["batch_size"] == 25
    assert len(calls) == 1
    assert worker.state.last_ns_scan > 0
    assert worker.last_tier3_result is result


def test_a_failing_batch_is_reported_and_does_not_raise():
    worker, _ = _worker_with_tier3(None)

    def boom():
        raise RuntimeError("api down")

    worker._tier3_namespaces = boom

    result = worker.run_tier3_batch()

    assert "api down" in result["error"]


def test_the_sleep_never_goes_negative():
    assert tier3_sleep(600, 100) == 500
    assert tier3_sleep(600, 600) == 0


def test_an_overrunning_batch_does_not_accumulate_debt():
    """max(interval, batch) means a slow batch is followed immediately."""
    assert tier3_sleep(300, 900) == 0


def test_independent_mode_starts_a_second_thread_and_shares_no_tier3():
    worker = _CountingWorker()
    thread = WorkerThread(worker, offset_seconds=0, tier3_independent=True)

    assert thread.tier3_thread is None
    assert thread.thread is None

    thread.start()
    try:
        assert thread.thread is not None
        assert thread.tier3_thread is not None
        assert thread.tier3_thread.name == "worker-ocpv07-t3"
        assert thread.thread.name == "worker-ocpv07"
    finally:
        thread.stop()
        thread.thread.join(timeout=5)
        thread.tier3_thread.join(timeout=5)


def test_default_mode_starts_one_thread():
    worker = _CountingWorker()
    thread = WorkerThread(worker, offset_seconds=0)

    thread.start()
    try:
        assert thread.tier3_thread is None
    finally:
        thread.stop()
        thread.thread.join(timeout=5)


def test_scheduler_wires_the_flag_onto_every_worker(monkeypatch):
    """The flag is per cluster, not per scheduler, so each worker must know."""
    import pathlib

    fake_kc = pathlib.Path("/tmp/stargate-fake-kubeconfig")
    monkeypatch.setattr("cli.scheduler.resolve_kubeconfig", lambda *a, **k: fake_kc)
    monkeypatch.setattr(pathlib.Path, "exists", lambda self: True)

    s = Scheduler(
        clusters={"ocpv07": "kubeconfig-ocpv07", "ocpv08": "kubeconfig-ocpv08"},
        tier3_independent=True,
        include_babylon=False,
    )

    assert [w.tier3_independent for w in s.workers] == [True, True]
    assert [w.worker.TIER3_INDEPENDENT for w in s.workers] == [True, True]


def test_scheduler_default_is_off(monkeypatch):
    import pathlib

    fake_kc = pathlib.Path("/tmp/stargate-fake-kubeconfig")
    monkeypatch.setattr("cli.scheduler.resolve_kubeconfig", lambda *a, **k: fake_kc)
    monkeypatch.setattr(pathlib.Path, "exists", lambda self: True)

    s = Scheduler(clusters={"ocpv07": "kubeconfig-ocpv07"}, include_babylon=False)

    assert s.workers[0].tier3_independent is False
    assert s.workers[0].worker.TIER3_INDEPENDENT is False


def test_the_cli_flag_exists_and_defaults_off():
    parser = scheduler_module.build_parser()

    assert parser.parse_args([]).tier3_independent is False
    assert parser.parse_args(["--tier3-independent"]).tier3_independent is True


def test_the_tier3_thread_waits_for_the_first_tick():
    """A cluster is not hit by a node scan and a namespace batch at once."""
    worker = _CountingWorker()
    worker.TIER3_INTERVAL = 0  # do not sleep in this test
    thread = WorkerThread(worker, offset_seconds=0, tier3_independent=True)
    thread.running = True

    # _run_tier3 polls tick_count in 5 s steps; with tick_count already set it
    # must not block. Drive one iteration by stopping immediately.
    thread.tick_count = 1
    t = threading.Thread(target=thread._run_tier3, daemon=True)
    t.start()
    thread.running = False
    t.join(timeout=5)

    assert not t.is_alive()
