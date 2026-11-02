"""Tests for storage headroom + OLM catalog freshness monitoring.

The checks implement the ops team's own gap table (Confluence 501907733,
issues 5-6): Ceph alerts wanted at 70% not near-full; OLM snapshots go
stale silently. Data shapes captured live from ocpv03 (Nov 1 2026):
cephcluster .status.ceph.capacity = {bytesTotal, bytesUsed, lastUpdated}.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from cli.worker import ClusterWorker, ClusterState


def _worker(storage_data=None, node_data=None):
    w = ClusterWorker.__new__(ClusterWorker)
    w.state = ClusterState(name="ocpv03", kubeconfig="kubeconfig-ocpv03")
    w.state.node_data = node_data or {"avg_cpu": 30, "status": "ok", "hot_nodes": 0}
    w.state.storage_catalog_data = storage_data
    w.api_url = None
    w._env = {}  # subprocess env (skipped __init__)
    return w


def _oc_result(stdout="", returncode=0):
    r = MagicMock()
    r.stdout = stdout
    r.returncode = returncode
    return r


CEPH_JSON = json.dumps({
    "items": [{
        "metadata": {"name": "ocs-storagecluster-cephcluster"},
        "status": {
            "phase": "Ready",
            "ceph": {
                "capacity": {
                    "bytesTotal": 192010755858432,
                    "bytesUsed": 26750210547712,   # 13.9%
                    "lastUpdated": "2026-11-02T05:15:14Z",
                }
            },
        },
    }]
})

CEPH_FULL_JSON = json.dumps({
    "items": [{
        "metadata": {"name": "ocs-storagecluster-cephcluster"},
        "status": {
            "phase": "Ready",
            "ceph": {
                "capacity": {
                    "bytesTotal": 1000000,
                    "bytesUsed": 750000,            # 75% — above the 70% threshold
                    "lastUpdated": "2026-11-02T05:15:14Z",
                }
            },
        },
    }]
})

NO_CEPH_JSON = json.dumps({"items": []})  # non-ODF cluster

PENDING_PVC_JSON = json.dumps({
    "items": [
        {"metadata": {"name": "p1", "creationTimestamp":
         (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()},
         "status": {"phase": "Pending"}},
        {"metadata": {"name": "p2", "creationTimestamp":
         (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()},
         "status": {"phase": "Pending"}},
        {"metadata": {"name": "p3", "creationTimestamp":
         (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()},
         "status": {"phase": "Bound"}},
    ]
})

NO_PENDING_JSON = json.dumps({"items": [
    {"metadata": {"name": "ok1", "creationTimestamp": "2026-01-01T00:00:00Z"},
     "status": {"phase": "Bound"}},
]})

CATALOGS_JSON = json.dumps({
    "items": [
        {"metadata": {"name": "redhat-operators", "namespace": "openshift-marketplace",
                      "creationTimestamp": "2024-10-22T12:31:18Z"},
         "status": {"connectionState": {"lastObservedState": "READY"}}},
        {"metadata": {"name": "custom-snapshot", "namespace": "lab-ns",
                      "creationTimestamp": "2026-01-01T00:00:00Z"},  # >45 days old
         "status": {"connectionState": {"lastObservedState": "READY"}}},
    ]
})

CATALOGS_NOT_READY_JSON = json.dumps({
    "items": [
        {"metadata": {"name": "redhat-operators", "namespace": "openshift-marketplace",
                      "creationTimestamp": "2026-10-01T00:00:00Z"},
         "status": {"connectionState": {"lastObservedState": "CONNECTING"}}},
    ]
})


def _mock_oc(responses):
    """responses: list of _oc_result, matched to subprocess.run call order."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return responses[len(calls) - 1] if len(calls) <= len(responses) else _oc_result()

    return fake_run, calls


class TestTier1StorageCatalog:
    def test_healthy_cluster(self):
        w = _worker()
        fake_run, _ = _mock_oc([
            _oc_result(CEPH_JSON), _oc_result(NO_PENDING_JSON), _oc_result(CATALOGS_JSON.replace("2026-01-01T00:00:00Z", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))),
        ])
        with patch("cli.worker.subprocess.run", side_effect=fake_run):
            data = w._tier1_storage_catalog()
        assert data["ceph"]["utilization_pct"] == 13.9
        assert data["pending_pvcs"]["count"] == 0
        assert data["catalogs"]["not_ready"] == []
        assert data["catalogs"]["stale_custom"] == []

    def test_ceph_over_threshold(self):
        w = _worker()
        fake_run, _ = _mock_oc([
            _oc_result(CEPH_FULL_JSON), _oc_result(NO_PENDING_JSON), _oc_result(NO_PENDING_JSON and json.dumps({"items": []})),
        ])
        with patch("cli.worker.subprocess.run", side_effect=fake_run):
            data = w._tier1_storage_catalog()
        assert data["ceph"]["utilization_pct"] == 75.0

    def test_non_odf_cluster_marks_not_installed(self):
        """No cephcluster → not_installed → vacuously healthy, not indeterminate."""
        w = _worker()
        fake_run, _ = _mock_oc([
            _oc_result(NO_CEPH_JSON), _oc_result(NO_PENDING_JSON), _oc_result(json.dumps({"items": []})),
        ])
        with patch("cli.worker.subprocess.run", side_effect=fake_run):
            data = w._tier1_storage_catalog()
        assert data["ceph"] == {"not_installed": True, "utilization_pct": None}
        assert data["pending_pvcs"] == {"count": 0, "max_age_seconds": 0}
        assert data["catalogs"] == {"total": 0, "not_ready": [], "stale_custom": []}

    def test_collection_failure_inherits_previous(self):
        """A transient oc failure keeps the last good signal (no clobber)."""
        w = _worker(storage_data={
            "ceph": {"utilization_pct": 13.9},
            "pending_pvcs": {"count": 0, "max_age_seconds": 0},
            "catalogs": {"total": 4, "not_ready": [], "stale_custom": []},
        })
        failed = _oc_result("", returncode=1)

        def fake_run(cmd, **kwargs):
            return failed

        with patch("cli.worker.subprocess.run", side_effect=fake_run):
            data = w._tier1_storage_catalog()
        assert data["ceph"] == {"utilization_pct": 13.9}
        assert data["catalogs"]["total"] == 4

    def test_stale_custom_catalog_detected(self):
        w = _worker()
        fake_run, _ = _mock_oc([
            _oc_result(NO_CEPH_JSON), _oc_result(NO_PENDING_JSON), _oc_result(CATALOGS_JSON),
        ])
        with patch("cli.worker.subprocess.run", side_effect=fake_run):
            data = w._tier1_storage_catalog()
        assert "lab-ns/custom-snapshot" in data["catalogs"]["stale_custom"]

    def test_catalog_not_ready_detected(self):
        w = _worker()
        fake_run, _ = _mock_oc([
            _oc_result(NO_CEPH_JSON), _oc_result(NO_PENDING_JSON), _oc_result(CATALOGS_NOT_READY_JSON),
        ])
        with patch("cli.worker.subprocess.run", side_effect=fake_run):
            data = w._tier1_storage_catalog()
        assert "openshift-marketplace/redhat-operators" in data["catalogs"]["not_ready"]

    def test_pending_pvc_age_tracked(self):
        """The documented '24 PVCs stuck 8 days' signature (GPTEINFRA-17674)."""
        w = _worker()
        fake_run, _ = _mock_oc([
            _oc_result(NO_CEPH_JSON), _oc_result(PENDING_PVC_JSON), _oc_result(json.dumps({"items": []})),
        ])
        with patch("cli.worker.subprocess.run", side_effect=fake_run):
            data = w._tier1_storage_catalog()
        assert data["pending_pvcs"]["count"] == 2  # Bound PVCs filtered out
        assert data["pending_pvcs"]["max_age_seconds"] > 7 * 86400


class TestStorageCatalogEvidence:
    def test_never_collected_is_unobserved(self):
        """No storage data at all → None (unobserved), NOT vacuous pass."""
        w = _worker(storage_data=None)
        ev = w._storage_catalog_evidence()
        assert ev["ceph_headroom_ok"] is None
        assert ev["pvc_pending_ok"] is None
        assert ev["olm_catalogs_ready"] is None

    def test_not_installed_is_vacuously_healthy(self):
        w = _worker(storage_data={
            "ceph": {"not_installed": True, "utilization_pct": None},
            "pending_pvcs": None, "catalogs": None,
        })
        ev = w._storage_catalog_evidence()
        assert ev["ceph_headroom_ok"] is True

    def test_healthy_storage(self):
        w = _worker(storage_data={
            "ceph": {"utilization_pct": 13.9},
            "pending_pvcs": {"count": 0, "max_age_seconds": 0},
            "catalogs": {"total": 4, "not_ready": [], "stale_custom": []},
        })
        ev = w._storage_catalog_evidence()
        assert ev["ceph_headroom_ok"] is True
        assert ev["pvc_pending_ok"] is True
        assert ev["olm_catalogs_ready"] is True

    def test_degraded_storage(self):
        w = _worker(storage_data={
            "ceph": {"utilization_pct": 75.0},
            "pending_pvcs": {"count": 24, "max_age_seconds": 8 * 86400},
            "catalogs": {"total": 5, "not_ready": ["ns/x"], "stale_custom": []},
        })
        ev = w._storage_catalog_evidence()
        assert ev["ceph_headroom_ok"] is False
        assert ev["pvc_pending_ok"] is False
        assert ev["olm_catalogs_ready"] is False

    def test_short_pending_pvcs_still_ok(self):
        """Recent Pending PVCs (normal provisioning churn) do not warn."""
        w = _worker(storage_data={
            "ceph": None,
            "pending_pvcs": {"count": 3, "max_age_seconds": 300},
            "catalogs": None,
        })
        ev = w._storage_catalog_evidence()
        assert ev["pvc_pending_ok"] is True


class TestRubricEvaluation:
    def _evaluate(self, evidence):
        from pathlib import Path
        from engine.rubric_loader import load_rubric
        from engine.rubric_evaluator import evaluate_rubric

        rubric = load_rubric(Path(__file__).parent.parent / "rubrics" / "platform" / "storage-catalog-health.yaml")
        assert rubric is not None, "storage-catalog-health rubric must load"
        return evaluate_rubric(rubric, evidence)

    def test_all_healthy_passes(self):
        result = self._evaluate({
            "cluster_reachable": True, "cpu_usage_acceptable": True,
            "memory_usage_acceptable": True, "no_critical_alerts": True,
            "nodes_healthy": True,
            "ceph_headroom_ok": True, "pvc_pending_ok": True, "olm_catalogs_ready": True,
        })
        assert result.outcome.value == "pass"

    def test_ceph_over_70_warns_with_class(self):
        result = self._evaluate({
            "cluster_reachable": True, "cpu_usage_acceptable": True,
            "memory_usage_acceptable": True, "no_critical_alerts": True,
            "nodes_healthy": True,
            "ceph_headroom_ok": False, "pvc_pending_ok": True, "olm_catalogs_ready": True,
        })
        assert result.outcome.value == "warn"
        assert result.failure_class == "ceph_near_full"

    def test_stale_catalog_warns(self):
        result = self._evaluate({
            "cluster_reachable": True, "cpu_usage_acceptable": True,
            "memory_usage_acceptable": True, "no_critical_alerts": True,
            "nodes_healthy": True,
            "ceph_headroom_ok": True, "pvc_pending_ok": True, "olm_catalogs_ready": False,
        })
        assert result.outcome.value == "warn"
        assert result.failure_class == "olm_catalog_stale"

    def test_stuck_pvcs_warn(self):
        result = self._evaluate({
            "cluster_reachable": True, "cpu_usage_acceptable": True,
            "memory_usage_acceptable": True, "no_critical_alerts": True,
            "nodes_healthy": True,
            "ceph_headroom_ok": True, "pvc_pending_ok": False, "olm_catalogs_ready": True,
        })
        assert result.outcome.value == "warn"
        assert result.failure_class == "pvc_binding_stuck"
