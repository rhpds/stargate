"""Tier-3 has two namespace lists and used to drop names that fell between them.

The old selection was:

    failing = sorted(state.failing_namespaces)
    healthy = [ns for ns in all_sandbox if ns not in state.failing_namespaces]
    batch = failing[:BATCH // 2]
    batch += healthy[idx : idx + BATCH - len(batch)]

`healthy` excludes every failing namespace, so a failing namespace past
`BATCH // 2` in sort order is in neither list. With the live batch of 25 that
cutoff is 12: a cluster with 16 failing namespaces re-scanned the same 12
forever and never once looked at the other 4, for as long as they stayed
broken. The namespaces most in need of evidence were the ones collection
could not reach, and the cycle still reported a full batch.
"""

from __future__ import annotations

import math

import pytest

from cli.worker import select_namespace_batch


def _names(prefix: str, n: int) -> list:
    return [f"{prefix}-{i:03d}" for i in range(n)]


def test_a_small_failing_set_is_taken_whole():
    failing = _names("sandbox-bad", 3)
    healthy = _names("sandbox-ok", 40)

    batch, _, _ = select_namespace_batch(failing, healthy, batch_size=25)

    assert set(failing) <= set(batch)
    assert len(batch) == 25


def test_the_batch_is_exactly_the_requested_size():
    batch, _, _ = select_namespace_batch(
        _names("sandbox-bad", 6), _names("sandbox-ok", 200), batch_size=25
    )

    assert len(batch) == 25
    assert len(set(batch)) == 25, "no namespace should appear twice in one batch"


def test_failing_names_past_the_reserved_half_are_not_starved():
    """The defect: 16 failing, 12 reserved, the other 4 never selected."""
    failing = _names("sandbox-bad", 16)
    healthy = _names("sandbox-ok", 90)

    seen = set()
    failing_index = 0
    ns_index = 0
    for _ in range(4):
        batch, ns_index, failing_index = select_namespace_batch(
            failing, healthy, 25, ns_index=ns_index, failing_index=failing_index
        )
        seen.update(batch)

    assert set(failing) <= seen, "every failing namespace must be reachable"


def test_every_failing_namespace_is_reached_within_the_stated_bound():
    failing = _names("sandbox-bad", 30)
    healthy = _names("sandbox-ok", 500)
    cap = 25 // 2
    ticks = math.ceil(len(failing) / cap)

    seen = set()
    failing_index = 0
    ns_index = 0
    for _ in range(ticks):
        batch, ns_index, failing_index = select_namespace_batch(
            failing, healthy, 25, ns_index=ns_index, failing_index=failing_index
        )
        seen.update(batch)

    assert set(failing) <= seen


def test_an_all_failing_cluster_still_fills_its_batch():
    """No healthy namespaces at all: the old code emitted 12 and stopped."""
    failing = _names("sandbox-bad", 40)

    batch, _, _ = select_namespace_batch(failing, [], batch_size=25)

    assert len(batch) == 25
    assert set(batch) <= set(failing)


def test_no_failing_namespaces_means_pure_rotation():
    healthy = _names("sandbox-ok", 60)

    batch, next_index, _ = select_namespace_batch([], healthy, batch_size=25)

    assert batch == healthy[:25]
    assert next_index == 25


def test_healthy_rotation_wraps_and_stays_even():
    healthy = _names("sandbox-ok", 10)

    first, idx, _ = select_namespace_batch([], healthy, 6, ns_index=0)
    second, idx, _ = select_namespace_batch([], healthy, 6, ns_index=idx)

    assert first == healthy[:6]
    assert second == healthy[6:] + healthy[:2]
    assert idx == 2


def test_a_namespace_in_both_lists_is_emitted_once():
    overlap = "sandbox-shared"
    failing = ["sandbox-bad-000", overlap]
    healthy = [overlap, "sandbox-ok-000", "sandbox-ok-001"]

    batch, _, _ = select_namespace_batch(failing, healthy, batch_size=10)

    assert batch.count(overlap) == 1
    assert len(batch) == 4, "three real namespaces plus the shared one"


def test_an_empty_fleet_yields_an_empty_batch():
    batch, ns_index, failing_index = select_namespace_batch([], [], 25)

    assert batch == []
    assert (ns_index, failing_index) == (0, 0)


def test_a_zero_batch_size_is_not_a_crash():
    batch, ns_index, failing_index = select_namespace_batch(
        _names("sandbox-bad", 3), _names("sandbox-ok", 3), 0
    )

    assert batch == []
    assert (ns_index, failing_index) == (0, 0)


def test_the_rotation_is_deterministic_for_the_same_inputs():
    failing = _names("sandbox-bad", 9)
    healthy = _names("sandbox-ok", 50)

    a = select_namespace_batch(failing, healthy, 25, ns_index=7, failing_index=3)
    b = select_namespace_batch(list(reversed(failing)), healthy, 25, ns_index=7, failing_index=3)

    assert a[0] == b[0], "sorting must not depend on set iteration order"
