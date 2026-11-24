"""Tier-3 picks namespaces by how long they have waited, not by list position.

Two defects are recorded here, because the second one is what the first
masked.

The original selection was:

    failing = sorted(state.failing_namespaces)
    healthy = [ns for ns in all_sandbox if ns not in state.failing_namespaces]
    batch = failing[:BATCH // 2]
    batch += healthy[idx : idx + BATCH - len(batch)]

`healthy` excludes every failing namespace, so a failing namespace past
`BATCH // 2` in sort order is in neither list. With the live batch of 25 that
cutoff is 12: a cluster with 16 failing namespaces re-scanned the same 12
forever and never once looked at the other 4, for as long as they stayed
broken.

The fix kept the lists but rotated an *index* through them. That is stable
only while the list is, and `all_sandbox_namespaces` is rebuilt from the pods
collector every tier-2 tick. Measured 2026-11-23 22:45Z: nine live namespaces
were 5–6 h old on clusters whose aggregate throughput implied a one-hour
sweep. The aggregate rate averages over the labs that were picked, so it
cannot see the ones that were not.

Selection now orders by the last *attempt* timestamp. A namespace attempted
longest ago is selected first, whatever the list does in between, so no lab
can be skipped indefinitely.
"""

from __future__ import annotations

import math

from cli.worker import select_namespace_batch


def _names(prefix: str, n: int) -> list:
    return [f"{prefix}-{i:03d}" for i in range(n)]


def _tick(failing, healthy, last, batch_size=25, now=None):
    """One selection followed by the caller's attempt stamping."""
    batch = select_namespace_batch(failing, healthy, batch_size, last)
    stamp = now if now is not None else max(last.values(), default=0.0) + 1.0
    for ns in batch:
        last[ns] = stamp
    return batch


def test_a_small_failing_set_is_taken_whole():
    failing = _names("sandbox-bad", 3)
    healthy = _names("sandbox-ok", 40)

    batch = select_namespace_batch(failing, healthy, batch_size=25)

    assert set(failing) <= set(batch)
    assert len(batch) == 25


def test_the_batch_is_exactly_the_requested_size():
    batch = select_namespace_batch(
        _names("sandbox-bad", 6), _names("sandbox-ok", 200), batch_size=25
    )

    assert len(batch) == 25
    assert len(set(batch)) == 25, "no namespace should appear twice in one batch"


def test_failing_names_past_the_reserved_half_are_not_starved():
    """The original defect: 16 failing, 12 reserved, the other 4 never selected."""
    failing = _names("sandbox-bad", 16)
    healthy = _names("sandbox-ok", 90)

    last: dict = {}
    seen = set()
    for _ in range(3):
        seen.update(_tick(failing, healthy, last))

    assert set(failing) <= seen, "every failing namespace must be reachable"


def test_every_failing_namespace_is_reached_within_the_stated_bound():
    failing = _names("sandbox-bad", 30)
    healthy = _names("sandbox-ok", 500)
    cap = 25 // 2
    ticks = math.ceil(len(failing) / cap)

    last: dict = {}
    seen = set()
    for _ in range(ticks):
        seen.update(_tick(failing, healthy, last))

    assert set(failing) <= seen


def test_an_all_failing_cluster_still_fills_its_batch():
    """No healthy namespaces at all: the original code emitted 12 and stopped."""
    failing = _names("sandbox-bad", 40)

    batch = select_namespace_batch(failing, [], batch_size=25)

    assert len(batch) == 25
    assert set(batch) <= set(failing)


def test_the_longest_waiting_namespace_is_selected_first():
    healthy = _names("sandbox-ok", 40)
    last = {ns: 1000.0 for ns in healthy}
    last["sandbox-ok-031"] = 10.0
    last["sandbox-ok-000"] = 5000.0

    batch = select_namespace_batch([], healthy, batch_size=25, last_scanned=last)

    assert batch[0] == "sandbox-ok-031"
    assert "sandbox-ok-000" not in batch


def test_never_attempted_namespaces_sort_ahead_of_attempted_ones():
    healthy = _names("sandbox-ok", 10)
    last = {ns: 1000.0 for ns in healthy}
    last.pop("sandbox-ok-007")

    batch = select_namespace_batch([], healthy, batch_size=5, last_scanned=last)

    assert batch[0] == "sandbox-ok-007"


def test_a_full_pass_reaches_every_live_namespace():
    live = _names("sandbox-ok", 120)
    last: dict = {}

    seen = set()
    for _ in range(math.ceil(len(live) / 25)):
        seen.update(_tick([], live, last))

    assert seen == set(live)


def test_churn_between_ticks_does_not_skip_a_namespace():
    """The index rotation's failure mode: the list moves under the cursor."""
    live = _names("sandbox-ok", 100)
    last: dict = {}
    seen = set()

    for i in range(math.ceil(len(live) / 25) + 2):
        # A lab is created (sorted before everything) and one destroyed each
        # tick — exactly what the pods collector does to the list.
        live = [f"sandbox-new-{i:03d}"] + live[:-1]
        seen.update(_tick([], live, last))

    assert set(live) <= seen


def test_a_failing_namespace_is_retried_even_though_it_keeps_failing():
    last = {"sandbox-bad-000": 0.0, "sandbox-bad-001": 50.0}
    failing = ["sandbox-bad-000", "sandbox-bad-001"]

    first = select_namespace_batch(failing, [], batch_size=25, last_scanned=last)
    for ns in first:
        last[ns] = 100.0          # attempted, still broken
    second = select_namespace_batch(failing, [], batch_size=25, last_scanned=last)

    assert first == ["sandbox-bad-000", "sandbox-bad-001"]
    assert second == ["sandbox-bad-000", "sandbox-bad-001"]


def test_a_namespace_in_both_lists_is_emitted_once():
    overlap = "sandbox-shared"
    failing = ["sandbox-bad-000", overlap]
    healthy = [overlap, "sandbox-ok-000", "sandbox-ok-001"]

    batch = select_namespace_batch(failing, healthy, batch_size=10)

    assert batch.count(overlap) == 1
    assert len(batch) == 4, "three real namespaces plus the shared one"


def test_an_empty_fleet_yields_an_empty_batch():
    assert select_namespace_batch([], [], 25) == []


def test_a_zero_batch_size_is_not_a_crash():
    assert select_namespace_batch(_names("sandbox-bad", 3), _names("sandbox-ok", 3), 0) == []


def test_the_selection_is_deterministic_for_the_same_inputs():
    failing = _names("sandbox-bad", 9)
    healthy = _names("sandbox-ok", 50)

    a = select_namespace_batch(failing, healthy, 25)
    b = select_namespace_batch(list(reversed(failing)), list(reversed(healthy)), 25)

    assert a == b, "list order and set iteration order must not matter"
