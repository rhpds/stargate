"""A run must be named after the namespace it was collected from.

Two defects lived in the write path, both invisible until #157 started logging
lost writes:

1. ``collect-dir`` used the *directory* name as the namespace. The scanner
   collects into ``mkdtemp(prefix="sg-<cluster>-")``, so 527,133 of 571,563 runs
   in the live store carry a random temp-dir name in ``runs.namespace``. Only
   one run in the whole table holds a real ``sandbox-*`` namespace.

2. ``run_id`` was ``{demo_id}-{second}``. Every namespace in a family shares one
   ``demo_id`` (``sandbox-47sld-ocp4-cluster`` and ``sandbox-z9cxn-ocp4-cluster``
   are both ``ocp4-cluster``), so two of them collected in the same second
   produced the *same* id. The loser got a 409 and its entire evaluation was
   dropped — observed live as "evaluated but not persisted: HTTP 409: Conflict".
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from types import SimpleNamespace

import cli.stargate as sg
import cli.worker as worker_mod
from api.routers.runs import build_run_id


# ---------------------------------------------------------------------------
# run identity
# ---------------------------------------------------------------------------

def test_namespaces_sharing_a_demo_id_do_not_collide_in_the_same_second():
    """The 409: two members of one family, one second."""
    now = datetime(2026, 11, 21, 5, 24, 9, tzinfo=timezone.utc)

    a = build_run_id("ocp4-cluster", "sandbox-47sld-ocp4-cluster", now)
    b = build_run_id("ocp4-cluster", "sandbox-z9cxn-ocp4-cluster", now)

    assert a != b


def test_retrying_the_same_namespace_in_the_same_second_is_still_idempotent():
    """The retry path relies on the id repeating: a slow first attempt that
    already committed must land on the same run, not a second one."""
    now = datetime(2026, 11, 21, 5, 24, 9, tzinfo=timezone.utc)

    assert build_run_id("ocp4-cluster", "sandbox-abc12-ocp4-cluster", now) == build_run_id(
        "ocp4-cluster", "sandbox-abc12-ocp4-cluster", now
    )


def test_run_id_keeps_the_readable_demo_prefix():
    """Operators read these; the timestamp and demo stay legible."""
    now = datetime(2026, 11, 21, 5, 24, 9, tzinfo=timezone.utc)
    run_id = build_run_id("zt-rhel", "sandbox-abc12-zt-rhelbu", now)

    assert run_id.startswith("zt-rhel-20261121-052409-")


# ---------------------------------------------------------------------------
# the namespace a run is attributed to
# ---------------------------------------------------------------------------

def _namespace_fixture(tmp_path):
    (tmp_path / "namespace.json").write_text(json.dumps({
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {"name": "sandbox-abc12-zt-rhelbu"},
        "status": {"phase": "Active"},
    }))
    return tmp_path


def _collect_dir(monkeypatch, tmp_path, *extra):
    seen = {}
    monkeypatch.setattr(
        sg, "_persist_to_api",
        lambda **kwargs: seen.update(kwargs) or ("run-123", None),
    )
    sg.main([
        "collect-dir", str(tmp_path),
        "--stages", "namespace-ready",
        "--api-url", "http://stargate-api:8090",
        "--format", "json",
        *extra,
    ])
    return seen


def test_collect_dir_records_the_namespace_it_was_collected_from(monkeypatch, tmp_path):
    seen = _collect_dir(
        monkeypatch, _namespace_fixture(tmp_path),
        "--namespace", "sandbox-abc12-zt-rhelbu",
    )

    assert seen["namespace"] == "sandbox-abc12-zt-rhelbu"


def test_collect_dir_still_falls_back_to_the_directory_name(monkeypatch, tmp_path):
    """Callers that do not know the namespace keep working."""
    seen = _collect_dir(monkeypatch, _namespace_fixture(tmp_path))

    assert seen["namespace"] == tmp_path.name


def test_the_scanner_tells_collect_dir_the_namespace(monkeypatch, tmp_path):
    """The scanner used to pass only a temp dir, so every run was misnamed."""
    commands = []

    def _fake_run(cmd, **kwargs):
        commands.append(cmd)
        if "collect-dir" in cmd:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"results": []}), "")
        return subprocess.CompletedProcess(cmd, 1, "", "not found")

    monkeypatch.setattr(worker_mod.subprocess, "run", _fake_run)
    monkeypatch.setattr(worker_mod.tempfile, "mkdtemp", lambda **kw: str(tmp_path))

    cluster = worker_mod.ClusterWorker("ocpv06", kubeconfig="/dev/null", api_url="http://api")
    cluster._check_showroom_health = lambda *a, **kw: None

    cluster._collect_namespace("sandbox-abc12-zt-rhelbu", lab_code="sandbox-abc12-zt-rhelbu")

    collect_cmd = next(c for c in commands if "collect-dir" in c)
    assert "--namespace" in collect_cmd
    assert collect_cmd[collect_cmd.index("--namespace") + 1] == "sandbox-abc12-zt-rhelbu"
