"""Evidence must be stored under the namespace it was collected from.

`LabMapping` accumulates one row per namespace that has ever existed, and every
row of a family carries the same wildcard pattern (`sandbox-*-zt-rhelbu`) with
its own namespace as `lab_code`. The scanner resolved a namespace through that
table with `match_namespace_to_lab`, which returns the *first* matching pattern,
so every namespace of a family resolved to one arbitrary sibling.

Measured against the live table (133,346 rows, 16.7 MB):

    all 621 sandbox namespaces -> 6 lab codes
    444 of them -> sandbox-5vpl6-ocp4-cluster

The collected namespace never received its own evaluation, so it aged out of
`live_labs` while a namespace that no longer exists kept looking healthy. That
is the "lab with running pods went dark" symptom — not a scanning gap.

These tests pin the identity rule (the namespace) and the payload shape that
made the endpoint cost 16.7 MB and ~2.9 s of ORM construction per call.
"""

from __future__ import annotations

import inspect
import time

import cli.worker as worker_mod
import api.routers.runs as runs_mod


# --- lab identity -----------------------------------------------------------


def test_scanner_uses_the_namespace_as_the_lab_code():
    source = inspect.getsource(worker_mod.ClusterWorker._tier3_namespaces)
    assert "lab_code=ns" in source, (
        "tier 3 must pass the namespace itself; a wildcard LabMapping match "
        "attributes the evaluation to an arbitrary sibling"
    )


def test_scanner_no_longer_fetches_the_mapping_table():
    """The fetch pulled 16.7 MB per cycle to produce a wrong answer."""
    assert not hasattr(worker_mod.ClusterWorker, "_get_lab_mappings")


# --- endpoint shape ---------------------------------------------------------

ROWS = [
    # (lab_code, namespace_pattern, ci_base, clusters)
    ("guid:c7rd4", "sandbox-c7rd4-*", "zt-imagebuilder-service", None),
    ("guid:4sqhb", "sandbox-4sqhb-*", "zt-imagebuilder-service", None),
    ("sandbox-lhlqc-zt-ansiblebu", "sandbox-*-zt-ansiblebu", "zt-ansiblebu", ["ocpv06"]),
    ("sandbox-6tkr4-zt-ansiblebu", "sandbox-*-zt-ansiblebu", "zt-ansiblebu", ["ocpv07"]),
    ("sandbox-4pxnl-zt-ansiblebu", "sandbox-*-zt-ansiblebu", "zt-ansiblebu", ["ocpv06"]),
    ("sandbox-5vpl6-ocp4-cluster", "sandbox-*-ocp4-cluster", "ocp4-cluster", ["ocpv08"]),
    ("sandbox-99r7v-ocp4-cluster", "sandbox-*-ocp4-cluster", "ocp4-cluster", ["ocpv06"]),
]


def test_payload_drops_guid_rows():
    """Babylon placement ids are not lab codes and are ~76% of the table."""
    patterns = [m["namespace_pattern"] for m in runs_mod._lab_mapping_payload(ROWS)]
    assert "sandbox-c7rd4-*" not in patterns
    assert "sandbox-4sqhb-*" not in patterns


def test_payload_has_one_row_per_pattern():
    payload = runs_mod._lab_mapping_payload(ROWS)
    assert len(payload) == 2
    assert {m["namespace_pattern"] for m in payload} == {
        "sandbox-*-zt-ansiblebu", "sandbox-*-ocp4-cluster",
    }


def test_payload_is_stable_regardless_of_row_order():
    """Insertion order used to decide which alias won. It must not."""
    forward = runs_mod._lab_mapping_payload(ROWS)
    backward = runs_mod._lab_mapping_payload(list(reversed(ROWS)))
    assert forward == backward
    assert [m["lab_code"] for m in forward] == [
        "sandbox-5vpl6-ocp4-cluster", "sandbox-4pxnl-zt-ansiblebu",
    ]


def test_payload_skips_rows_without_a_pattern():
    payload = runs_mod._lab_mapping_payload([
        ("sandbox-x-zt-rhelbu", None, "zt-rhelbu", None),
        ("", "sandbox-*-zt-rhelbu", "zt-rhelbu", None),
        ("sandbox-a-zt-rhelbu", "sandbox-*-zt-rhelbu", "zt-rhelbu", None),
    ])
    assert [m["lab_code"] for m in payload] == ["sandbox-a-zt-rhelbu"]


# --- the endpoint must not block the event loop -----------------------------


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = 0

    def filter(self, *args, **kwargs):
        self.filters += 1
        return self

    def all(self):
        return self.rows


class _FakeDB:
    def __init__(self, rows):
        self.rows = rows
        self.queries = 0
        self.closed = False

    def query(self, *columns):
        self.queries += 1
        return _FakeQuery(self.rows)

    def close(self):
        self.closed = True


def _patch_db(monkeypatch, db):
    def fake_get_db():
        yield db

    monkeypatch.setattr("db.database.get_db", fake_get_db)
    monkeypatch.setattr(runs_mod, "_lab_mappings_cache", {"ts": 0.0, "data": None})
    return db


def test_endpoint_is_synchronous(monkeypatch):
    """A blocking query in an `async def` stalls /health and the readiness probe."""
    assert not inspect.iscoroutinefunction(runs_mod.get_lab_mappings)


def test_endpoint_returns_the_collapsed_payload(monkeypatch):
    db = _patch_db(monkeypatch, _FakeDB(ROWS))
    result = runs_mod.get_lab_mappings()
    assert len(result["mappings"]) == 2
    assert db.closed


def test_endpoint_caches_for_the_ttl(monkeypatch):
    db = _patch_db(monkeypatch, _FakeDB(ROWS))
    runs_mod.get_lab_mappings()
    runs_mod.get_lab_mappings()
    runs_mod.get_lab_mappings()
    assert db.queries == 1


def test_cache_expiry_re_queries(monkeypatch):
    db = _patch_db(monkeypatch, _FakeDB(ROWS))
    runs_mod.get_lab_mappings()
    runs_mod._lab_mappings_cache["ts"] = time.monotonic() - runs_mod._LAB_MAPPINGS_TTL - 1
    runs_mod.get_lab_mappings()
    assert db.queries == 2
