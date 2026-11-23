"""The fleet view must not shrink because a snapshot was written mid-cycle.

`scan-*.json` is written every 5 minutes from whatever the workers have
reported so far. One minute after a scheduler restart that is a subset of the
fleet, and the loader used to accept it as "the scan" because its only test was
`len(data) > 1` — so the frontend reported a two-cluster fleet while a complete
snapshot from five minutes earlier sat on the same volume.

These tests pin the rule that replaced it: prefer the newest snapshot that is
not missing clusters its recent neighbours have.
"""

import json

from api.routers import _shared


FLEET = ["ocpv03", "ocpv06", "ocpv07", "ocpv08", "ocpv09"]


def _snapshot(scan_dir, stamp, clusters):
    """Write one snapshot the way the scheduler names them, newest-agnostic."""
    rows = [{"cluster": c, "health_rate": 99.0, "sandbox_active": 10} for c in clusters]
    path = scan_dir / f"scan-20261123-{stamp}.json"
    path.write_text(json.dumps(rows))
    return path


def test_a_restart_snapshot_does_not_shrink_the_fleet(tmp_path):
    """The exact shape of 2026-11-23 18:57: two workers done, five configured."""
    _snapshot(tmp_path, "184700", FLEET)
    _snapshot(tmp_path, "185200", FLEET)
    _snapshot(tmp_path, "185702", ["ocpv03", "ocpv06"])  # written after restart

    data = _shared._newest_complete_scan(tmp_path)

    assert [row["cluster"] for row in data] == FLEET


def test_the_newest_complete_snapshot_wins(tmp_path):
    _snapshot(tmp_path, "184700", FLEET)
    newest = _snapshot(tmp_path, "185200", FLEET)

    data = _shared._newest_complete_scan(tmp_path)

    assert data == json.loads(newest.read_text())


def test_partial_snapshots_are_not_preferred_over_the_newest_of_equals(tmp_path):
    """Two partials, then a complete one: the complete one is the answer."""
    _snapshot(tmp_path, "184700", FLEET)
    _snapshot(tmp_path, "185200", ["ocpv03"])
    _snapshot(tmp_path, "185702", ["ocpv03", "ocpv06"])

    assert len(_shared._newest_complete_scan(tmp_path)) == len(FLEET)


def test_a_single_cluster_fleet_is_used_when_that_is_all_there_is(tmp_path):
    """Previously the loop never broke, so it returned the *oldest* file."""
    _snapshot(tmp_path, "184700", ["ocpv03"])
    newest = _snapshot(tmp_path, "185200", ["ocpv06"])

    data = _shared._newest_complete_scan(tmp_path)

    assert data == json.loads(newest.read_text())


def test_an_empty_snapshot_is_ignored(tmp_path):
    _snapshot(tmp_path, "184700", FLEET)
    (tmp_path / "scan-20261123-185200.json").write_text("[]")

    assert len(_shared._newest_complete_scan(tmp_path)) == len(FLEET)


def test_malformed_json_is_skipped_not_fatal(tmp_path):
    """A half-written file must not take the fleet view down with it."""
    _snapshot(tmp_path, "184700", FLEET)
    (tmp_path / "scan-20261123-185200.json").write_text('{"truncated": ')

    assert len(_shared._newest_complete_scan(tmp_path)) == len(FLEET)


def test_no_snapshots_returns_empty(tmp_path):
    assert _shared._newest_complete_scan(tmp_path) == []


def test_rows_without_a_cluster_name_still_count():
    """A row with no cluster name must not create a phantom cluster."""
    assert _shared._snapshot_clusters([{"cluster": "a"}, {"cluster": None}, "junk", {}]) == {"a"}


def test_the_lookback_window_is_bounded(tmp_path):
    """The deliberate other half of the trade-off.

    A complete snapshot older than the window is not consulted, so a cluster
    that is genuinely dropped cannot hide behind yesterday's fleet forever: it
    becomes visible once the window rolls past. The window is ~30 minutes, and
    this test fails loudly if someone widens it without deciding to.
    """
    _snapshot(tmp_path, "170000", FLEET)  # complete, but stale
    for i in range(_shared.SCAN_LOOKBACK_FILES):
        _snapshot(tmp_path, f"1852{i:02d}", ["ocpv03", "ocpv06"])

    data = _shared._newest_complete_scan(tmp_path)

    assert len(data) == 2, "the window should have rolled past the stale snapshot"
    assert _shared.SCAN_LOOKBACK_FILES == 6
