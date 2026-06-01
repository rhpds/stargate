"""EDD tests — Provisioning Intelligence API (api/routers/capacity.py)."""

from unittest.mock import patch

import pytest


class TestClusterCapacity:

    def test_endpoint_exists(self):
        from api.routers.capacity import cluster_capacity
        assert callable(cluster_capacity)

    def test_returns_sorted_clusters(self):
        from api.routers.capacity import cluster_capacity
        mock_scans = [
            {"cluster": "c1", "avg_cpu_pct": 80, "vms_per_node": 50, "sandbox_active": 10, "sandbox_failing": 0, "health_rate": 90, "status": "healthy", "hot_nodes": 0},
            {"cluster": "c2", "avg_cpu_pct": 20, "vms_per_node": 10, "sandbox_active": 5, "sandbox_failing": 0, "health_rate": 100, "status": "healthy", "hot_nodes": 0},
        ]
        mock_babylon = {"pools": {"all_pools": []}}
        with patch("api.routers.capacity._load_latest_scan", return_value=mock_scans), \
             patch("api.routers.capacity._load_latest_babylon", return_value=mock_babylon):
            result = cluster_capacity()
        assert result["total"] == 2
        assert result["clusters"][0]["cluster"] == "c2"
        assert result["clusters"][0]["score"] > result["clusters"][1]["score"]

    def test_empty_scans(self):
        from api.routers.capacity import cluster_capacity
        with patch("api.routers.capacity._load_latest_scan", return_value=[]), \
             patch("api.routers.capacity._load_latest_babylon", return_value={"pools": {}}):
            result = cluster_capacity()
        assert result["total"] == 0
        assert result["clusters"] == []


class TestClusterScore:

    def test_score_breakdown(self):
        from api.routers.capacity import cluster_score
        mock_scans = [{"cluster": "test", "avg_cpu_pct": 30, "vms_per_node": 20, "sandbox_active": 10, "sandbox_failing": 0, "health_rate": 95, "status": "healthy", "hot_nodes": 0}]
        with patch("api.routers.capacity._load_latest_scan", return_value=mock_scans), \
             patch("api.routers.capacity._load_latest_babylon", return_value={"pools": {"all_pools": []}}):
            result = cluster_score("test")
        assert "breakdown" in result
        assert result["breakdown"]["cpu_score"] == 70
        assert result["breakdown"]["health_score"] == 95
        assert result["score"] > 0

    def test_missing_cluster_404(self):
        from api.routers.capacity import cluster_score
        from fastapi import HTTPException
        with patch("api.routers.capacity._load_latest_scan", return_value=[]), \
             patch("api.routers.capacity._load_latest_babylon", return_value={"pools": {}}):
            with pytest.raises(HTTPException) as exc:
                cluster_score("nonexistent")
            assert exc.value.status_code == 404


class TestPoolAvailability:

    def test_returns_pools(self):
        from api.routers.capacity import pool_availability
        mock_babylon = {"pools": {"all_pools": [
            {"name": "pool-a", "available": 5, "ready": 3, "min": 10},
            {"name": "pool-b", "available": 0, "ready": 0, "min": 5},
        ], "exhausted": [{"name": "pool-b"}], "low": []}}
        with patch("api.routers.capacity._load_latest_babylon", return_value=mock_babylon):
            result = pool_availability()
        assert result["total_pools"] == 2
        assert result["total_available"] == 5
        assert result["total_exhausted"] == 1


class TestHealthSummary:

    def test_returns_cluster_health(self):
        from api.routers.capacity import health_summary
        mock_scans = [
            {"cluster": "healthy-1", "status": "healthy", "avg_cpu_pct": 20, "health_rate": 100, "sandbox_failing": 0},
            {"cluster": "warn-1", "status": "warning", "avg_cpu_pct": 75, "health_rate": 80, "sandbox_failing": 3},
        ]
        with patch("api.routers.capacity._load_latest_scan", return_value=mock_scans):
            result = health_summary()
        assert result["total"] == 2
        assert result["healthy"] == 1
        assert result["degraded"] == 1
        assert result["clusters"]["healthy-1"]["healthy"] is True
        assert result["clusters"]["warn-1"]["healthy"] is False


class TestPlacementScoring:

    def test_perfect_cluster_scores_high(self):
        from api.routers.capacity import _compute_placement_score
        score = _compute_placement_score(avg_cpu=10, vms_per_node=5, health_rate=100, pool_available=10, sandbox_active=5)
        assert score > 80

    def test_overloaded_cluster_scores_low(self):
        from api.routers.capacity import _compute_placement_score
        score = _compute_placement_score(avg_cpu=90, vms_per_node=100, health_rate=50, pool_available=0, sandbox_active=50)
        assert score < 30

    def test_score_range_0_to_100(self):
        from api.routers.capacity import _compute_placement_score
        low = _compute_placement_score(avg_cpu=100, vms_per_node=200, health_rate=0, pool_available=0, sandbox_active=0)
        high = _compute_placement_score(avg_cpu=0, vms_per_node=0, health_rate=100, pool_available=20, sandbox_active=0)
        assert 0 <= low <= 100
        assert 0 <= high <= 100
