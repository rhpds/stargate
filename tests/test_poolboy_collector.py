"""Poolboy collector tests — ResourcePool, ResourceHandle, ResourceClaim."""

import pytest

from collectors.poolboy.collect_poolboy import (
    collect_resource_pool,
    collect_resource_handle,
    collect_resource_claim,
    summarize_pools,
)


class TestCollectResourcePool:
    def test_healthy_pool(self):
        data = {
            "metadata": {"name": "openshift-4.20-multi", "namespace": "poolboy"},
            "spec": {"minAvailable": 5},
            "status": {
                "resourceHandleCount": {"available": 5, "ready": 3},
                "resourceHandles": [
                    {"name": "guid-abc", "healthy": True, "ready": True},
                    {"name": "guid-def", "healthy": True, "ready": True},
                    {"name": "guid-ghi", "healthy": True, "ready": True},
                    {"name": "guid-jkl", "healthy": True, "ready": False},
                    {"name": "guid-mno", "healthy": True, "ready": False},
                ],
            },
        }
        ev = collect_resource_pool(data)
        assert ev.resource_kind == "ResourcePool"
        assert ev.observed["pool_exists"] is True
        assert ev.observed["min_available"] == 5
        assert ev.observed["total_handles"] == 5
        assert ev.observed["healthy_handles"] == 5
        assert ev.observed["ready_handles"] == 3
        assert ev.observed["pool_exhausted"] is False
        assert ev.observed["pool_low"] is False

    def test_exhausted_pool(self):
        data = {
            "metadata": {"name": "exhausted-pool", "namespace": "poolboy"},
            "spec": {"minAvailable": 2},
            "status": {
                "resourceHandleCount": {"available": 0, "ready": 0},
                "resourceHandles": [],
            },
        }
        ev = collect_resource_pool(data)
        assert ev.observed["pool_exhausted"] is True
        assert ev.observed["total_handles"] == 0

    def test_low_pool(self):
        data = {
            "metadata": {"name": "low-pool", "namespace": "poolboy"},
            "spec": {"minAvailable": 5},
            "status": {
                "resourceHandleCount": {"available": 1, "ready": 0},
                "resourceHandles": [
                    {"name": "guid-last", "healthy": True, "ready": False},
                ],
            },
        }
        ev = collect_resource_pool(data)
        assert ev.observed["pool_low"] is True
        assert ev.observed["pool_exhausted"] is False

    def test_pool_no_min(self):
        data = {
            "metadata": {"name": "no-min", "namespace": "poolboy"},
            "spec": {},
            "status": {
                "resourceHandleCount": {"available": 0, "ready": 0},
                "resourceHandles": [],
            },
        }
        ev = collect_resource_pool(data)
        assert ev.observed["pool_exhausted"] is False
        assert ev.observed["pool_low"] is False


class TestCollectResourceHandle:
    def test_bound_handle(self):
        data = {
            "metadata": {"name": "guid-abc123", "namespace": "poolboy"},
            "spec": {
                "resourceClaim": {"name": "claim-xyz", "namespace": "user-ns"},
                "provider": {"name": "ocp-cluster-cnv"},
                "resources": [
                    {"provider": {"name": "agd-v2.ocp-cluster-cnv-pools.prod"}},
                    {"provider": {"name": "agd-v2.some-workload.prod"}},
                ],
            },
        }
        ev = collect_resource_handle(data)
        assert ev.resource_kind == "ResourceHandle"
        assert ev.observed["handle_exists"] is True
        assert ev.observed["claim_name"] == "claim-xyz"
        assert ev.observed["claim_namespace"] == "user-ns"
        assert ev.observed["provider_name"] == "ocp-cluster-cnv"
        assert len(ev.observed["resource_providers"]) == 2

    def test_unbound_handle(self):
        data = {
            "metadata": {"name": "guid-unbound", "namespace": "poolboy"},
            "spec": {
                "resourceClaim": {},
                "provider": {"name": "some-pool"},
                "resources": [],
            },
        }
        ev = collect_resource_handle(data)
        assert ev.observed["claim_name"] is None
        assert ev.observed["resource_providers"] == []


class TestCollectResourceClaim:
    def test_active_claim(self):
        data = {
            "metadata": {
                "name": "user-claim-123",
                "namespace": "user-ns",
                "labels": {
                    "babylon.gpte.redhat.com/catalogItemName": "lb1088-code-red",
                },
            },
            "spec": {"provider": {"name": "ocp-cluster-cnv"}},
            "status": {
                "resources": [
                    {
                        "state": {
                            "name": "resource-1",
                            "spec": {"vars": {"current_state": "started", "desired_state": "started"}},
                        },
                    },
                ],
            },
        }
        ev = collect_resource_claim(data)
        assert ev.resource_kind == "ResourceClaim"
        assert ev.observed["claim_exists"] is True
        assert ev.observed["provider_name"] == "ocp-cluster-cnv"
        assert ev.observed["resource_count"] == 1
        assert ev.observed["catalog_item"] == "lb1088-code-red"
        assert ev.observed["resource_states"][0]["current_state"] == "started"

    def test_empty_claim(self):
        data = {
            "metadata": {"name": "empty-claim", "namespace": "ns", "labels": {}},
            "spec": {"provider": {}},
            "status": {"resources": []},
        }
        ev = collect_resource_claim(data)
        assert ev.observed["resource_count"] == 0
        assert ev.observed["catalog_item"] == ""


class TestSummarizePools:
    def test_mixed_pools(self):
        pools = [
            {"metadata": {"name": "p1"}, "spec": {"minAvailable": 5},
             "status": {"resourceHandleCount": {"available": 5, "ready": 3}, "resourceHandles": []}},
            {"metadata": {"name": "p2"}, "spec": {"minAvailable": 2},
             "status": {"resourceHandleCount": {"available": 0, "ready": 0}, "resourceHandles": []}},
            {"metadata": {"name": "p3"}, "spec": {"minAvailable": 3},
             "status": {"resourceHandleCount": {"available": 1, "ready": 0}, "resourceHandles": []}},
        ]
        summary = summarize_pools(pools)
        assert summary["total_pools"] == 3
        assert summary["exhausted"] == 1
        assert summary["low"] == 1
        assert summary["healthy"] == 1
        assert summary["capacity_status"] == "critical"

    def test_all_healthy(self):
        pools = [
            {"metadata": {"name": "p1"}, "spec": {"minAvailable": 2},
             "status": {"resourceHandleCount": {"available": 5, "ready": 5}, "resourceHandles": []}},
        ]
        summary = summarize_pools(pools)
        assert summary["capacity_status"] == "healthy"

    def test_empty_pools(self):
        summary = summarize_pools([])
        assert summary["total_pools"] == 0
        assert summary["capacity_status"] == "healthy"
