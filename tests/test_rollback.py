"""Unit tests for engine/rollback.py — namespace state capture, restore, verify."""

import json
from unittest.mock import patch, call

import pytest


DEPLOY_LIST = {
    "kind": "DeploymentList",
    "items": [
        {
            "metadata": {
                "name": "showroom",
                "namespace": "sandbox-abc12-ocp4",
                "managedFields": [{"manager": "kubectl"}],
                "resourceVersion": "99999",
                "uid": "abc-123",
                "creationTimestamp": "2025-01-01T00:00:00Z",
                "generation": 3,
            },
            "spec": {"replicas": 1},
            "status": {"readyReplicas": 1},
        },
    ],
}

SVC_LIST = {
    "kind": "ServiceList",
    "items": [
        {
            "metadata": {
                "name": "showroom-svc",
                "namespace": "sandbox-abc12-ocp4",
                "managedFields": [{"manager": "kubectl"}],
                "resourceVersion": "88888",
                "uid": "def-456",
                "creationTimestamp": "2025-01-01T00:00:00Z",
                "generation": 1,
            },
            "spec": {"ports": [{"port": 8080}]},
            "status": {},
        },
    ],
}

POD_LIST = {
    "kind": "PodList",
    "items": [
        {"metadata": {"name": "showroom-abc"}, "status": {"phase": "Running"}},
        {"metadata": {"name": "showroom-def"}, "status": {"phase": "Pending"}},
    ],
}


def _oc_side_effect(args, kubeconfig="", timeout=30):
    if "deployments" in args:
        return json.dumps(DEPLOY_LIST)
    if "services" in args:
        return json.dumps(SVC_LIST)
    if "pods" in args:
        return json.dumps(POD_LIST)
    return ""


class TestCaptureState:

    @patch("engine.rollback._run_oc", side_effect=_oc_side_effect)
    def test_captures_deployments_services_pods(self, mock_oc):
        from engine.rollback import capture_state
        snap = capture_state("sandbox-abc12-ocp4", "")

        assert snap["namespace"] == "sandbox-abc12-ocp4"
        assert len(snap["deployments"]) == 1
        assert snap["deployments"][0]["metadata"]["name"] == "showroom"
        assert len(snap["services"]) == 1
        assert snap["services"][0]["metadata"]["name"] == "showroom-svc"
        assert len(snap["pods"]) == 2

    @patch("engine.rollback._run_oc", side_effect=_oc_side_effect)
    def test_strips_managed_fields(self, mock_oc):
        from engine.rollback import capture_state
        snap = capture_state("ns", "")

        meta = snap["deployments"][0]["metadata"]
        assert "managedFields" not in meta
        assert "resourceVersion" not in meta
        assert "uid" not in meta
        assert "creationTimestamp" not in meta
        assert "generation" not in meta
        assert "name" in meta

    @patch("engine.rollback._run_oc", side_effect=_oc_side_effect)
    def test_clears_status_on_deployments_services(self, mock_oc):
        from engine.rollback import capture_state
        snap = capture_state("ns", "")

        assert snap["deployments"][0].get("status") == {}
        assert snap["services"][0].get("status") == {}

    @patch("engine.rollback._run_oc", side_effect=_oc_side_effect)
    def test_pods_are_name_phase_only(self, mock_oc):
        from engine.rollback import capture_state
        snap = capture_state("ns", "")

        assert snap["pods"] == [
            {"name": "showroom-abc", "phase": "Running"},
            {"name": "showroom-def", "phase": "Pending"},
        ]

    @patch("engine.rollback._run_oc", return_value="")
    def test_handles_empty_oc_output(self, mock_oc):
        from engine.rollback import capture_state
        snap = capture_state("ns", "")

        assert snap["deployments"] == []
        assert snap["services"] == []
        assert snap["pods"] == []

    @patch("engine.rollback._run_oc", return_value="error: connection refused")
    def test_handles_error_output(self, mock_oc):
        from engine.rollback import capture_state
        snap = capture_state("ns", "")

        assert snap["deployments"] == []
        assert snap["services"] == []

    @patch("engine.rollback._run_oc", side_effect=_oc_side_effect)
    def test_timestamp_present(self, mock_oc):
        from engine.rollback import capture_state
        snap = capture_state("ns", "")
        assert "timestamp" in snap

    @patch("engine.rollback._run_oc", side_effect=_oc_side_effect)
    def test_passes_kubeconfig(self, mock_oc):
        from engine.rollback import capture_state
        capture_state("ns", "/path/to/kube")
        for c in mock_oc.call_args_list:
            assert c[0][1] == "/path/to/kube" or c.kwargs.get("kubeconfig") == "/path/to/kube" or "/path/to/kube" in c[0]


class TestRestoreState:

    def _snapshot(self, deploys=None, services=None):
        return {
            "namespace": "ns",
            "timestamp": "2025-01-01T00:00:00Z",
            "deployments": deploys or [],
            "services": services or [],
            "pods": [],
        }

    @patch("engine.rollback._run_oc", return_value='{"items": []}')
    @patch("engine.rollback._run_oc_stdin", return_value="deployment/showroom configured")
    def test_restores_resource(self, mock_stdin, mock_oc):
        from engine.rollback import restore_state
        snap = self._snapshot(deploys=[{"metadata": {"name": "showroom"}, "spec": {"replicas": 1}}])
        result = restore_state(snap, "ns", "")

        assert result["restored"] == 1
        assert result["errors"] == []
        mock_stdin.assert_called_once()

    @patch("engine.rollback._run_oc", return_value='{"items": []}')
    @patch("engine.rollback._run_oc_stdin", return_value="deployment/a configured\nservice/b configured")
    def test_counts_both_kinds(self, mock_stdin, mock_oc):
        from engine.rollback import restore_state
        snap = self._snapshot(
            deploys=[{"metadata": {"name": "a"}}],
            services=[{"metadata": {"name": "b"}}],
        )
        result = restore_state(snap, "ns", "")
        assert result["restored"] == 2

    @patch("engine.rollback._run_oc")
    @patch("engine.rollback._run_oc_stdin", return_value="deployment/showroom configured")
    def test_deletes_extra_resources(self, mock_stdin, mock_oc):
        extra_deploy = {"items": [
            {"metadata": {"name": "showroom"}},
            {"metadata": {"name": "stale-leftover"}},
        ]}
        mock_oc.return_value = json.dumps(extra_deploy)

        from engine.rollback import restore_state
        snap = self._snapshot(deploys=[{"metadata": {"name": "showroom"}}])
        result = restore_state(snap, "ns", "")

        assert result["deleted"] >= 1
        delete_calls = [c for c in mock_oc.call_args_list if "delete" in c[0][0]]
        assert any("stale-leftover" in str(c) for c in delete_calls)

    @patch("engine.rollback._run_oc", return_value='{"items": []}')
    @patch("engine.rollback._run_oc_stdin", return_value="error: resource not found")
    def test_records_errors_on_apply_failure(self, mock_stdin, mock_oc):
        from engine.rollback import restore_state
        snap = self._snapshot(deploys=[{"metadata": {"name": "broken"}}])
        result = restore_state(snap, "ns", "")

        assert result["restored"] == 0
        assert len(result["errors"]) == 1

    @patch("engine.rollback._run_oc", return_value='{"items": []}')
    @patch("engine.rollback._run_oc_stdin", side_effect=Exception("connection refused"))
    def test_handles_apply_exception(self, mock_stdin, mock_oc):
        from engine.rollback import restore_state
        snap = self._snapshot(deploys=[{"metadata": {"name": "x"}}])
        result = restore_state(snap, "ns", "")

        assert len(result["errors"]) == 1
        assert "connection refused" in result["errors"][0]

    @patch("engine.rollback._run_oc", return_value="not json")
    @patch("engine.rollback._run_oc_stdin", return_value="deployment/a configured")
    def test_handles_non_json_get_for_cleanup(self, mock_stdin, mock_oc):
        from engine.rollback import restore_state
        snap = self._snapshot(deploys=[{"metadata": {"name": "a"}}])
        result = restore_state(snap, "ns", "")
        assert result["restored"] == 1
        assert result["deleted"] == 0

    @patch("engine.rollback._run_oc", return_value='{"items": []}')
    @patch("engine.rollback._run_oc_stdin", return_value="deployment/showroom created")
    def test_created_counts_as_restored(self, mock_stdin, mock_oc):
        from engine.rollback import restore_state
        snap = self._snapshot(deploys=[{"metadata": {"name": "showroom"}}])
        result = restore_state(snap, "ns", "")
        assert result["restored"] == 1


class TestVerifyRestore:

    def _snapshot(self, deploy_names=None, svc_names=None, replicas=None):
        deploys = [
            {"metadata": {"name": n}, "spec": {"replicas": (replicas or {}).get(n, 1)}}
            for n in (deploy_names or [])
        ]
        svcs = [{"metadata": {"name": n}} for n in (svc_names or [])]
        return {
            "namespace": "ns",
            "timestamp": "2025-01-01T00:00:00Z",
            "deployments": deploys,
            "services": svcs,
            "pods": [],
        }

    @patch("engine.rollback.capture_state")
    def test_matching_state_passes(self, mock_capture):
        snap = self._snapshot(deploy_names=["web"], svc_names=["web-svc"], replicas={"web": 2})
        mock_capture.return_value = snap.copy()

        from engine.rollback import verify_restore
        assert verify_restore(snap, "ns", "") is True

    @patch("engine.rollback.capture_state")
    def test_missing_deployment_fails(self, mock_capture):
        snap = self._snapshot(deploy_names=["web", "worker"])
        current = self._snapshot(deploy_names=["web"])
        mock_capture.return_value = current

        from engine.rollback import verify_restore
        assert verify_restore(snap, "ns", "") is False

    @patch("engine.rollback.capture_state")
    def test_extra_deployment_fails(self, mock_capture):
        snap = self._snapshot(deploy_names=["web"])
        current = self._snapshot(deploy_names=["web", "rogue"])
        mock_capture.return_value = current

        from engine.rollback import verify_restore
        assert verify_restore(snap, "ns", "") is False

    @patch("engine.rollback.capture_state")
    def test_replica_mismatch_fails(self, mock_capture):
        snap = self._snapshot(deploy_names=["web"], replicas={"web": 3})
        current = self._snapshot(deploy_names=["web"], replicas={"web": 1})
        mock_capture.return_value = current

        from engine.rollback import verify_restore
        assert verify_restore(snap, "ns", "") is False

    @patch("engine.rollback.capture_state")
    def test_service_mismatch_fails(self, mock_capture):
        snap = self._snapshot(svc_names=["svc-a", "svc-b"])
        current = self._snapshot(svc_names=["svc-a"])
        mock_capture.return_value = current

        from engine.rollback import verify_restore
        assert verify_restore(snap, "ns", "") is False

    @patch("engine.rollback.capture_state")
    def test_empty_snapshot_matches_empty_current(self, mock_capture):
        snap = self._snapshot()
        mock_capture.return_value = self._snapshot()

        from engine.rollback import verify_restore
        assert verify_restore(snap, "ns", "") is True
