"""TDD tests — Pool handle velocity tracking and exhaustion prediction."""

from datetime import datetime, timezone, timedelta


class TestPoolVelocity:
    def test_compute_pool_velocity_exists(self):
        from engine.pool_velocity import compute_pool_velocity
        assert callable(compute_pool_velocity)

    def test_depleting_pool(self):
        from engine.pool_velocity import compute_pool_velocity
        now = datetime.now(timezone.utc)
        timeline = [
            {"available": 10, "captured_at": (now - timedelta(hours=2)).isoformat()},
            {"available": 8, "captured_at": (now - timedelta(hours=1)).isoformat()},
            {"available": 6, "captured_at": now.isoformat()},
        ]
        result = compute_pool_velocity(timeline)
        assert result["handles_per_hour"] < 0
        assert result["trend"] == "depleting"

    def test_stable_pool(self):
        from engine.pool_velocity import compute_pool_velocity
        now = datetime.now(timezone.utc)
        timeline = [
            {"available": 5, "captured_at": (now - timedelta(hours=2)).isoformat()},
            {"available": 5, "captured_at": (now - timedelta(hours=1)).isoformat()},
            {"available": 5, "captured_at": now.isoformat()},
        ]
        result = compute_pool_velocity(timeline)
        assert result["trend"] == "stable"

    def test_recovering_pool(self):
        from engine.pool_velocity import compute_pool_velocity
        now = datetime.now(timezone.utc)
        timeline = [
            {"available": 2, "captured_at": (now - timedelta(hours=2)).isoformat()},
            {"available": 4, "captured_at": (now - timedelta(hours=1)).isoformat()},
            {"available": 6, "captured_at": now.isoformat()},
        ]
        result = compute_pool_velocity(timeline)
        assert result["handles_per_hour"] > 0
        assert result["trend"] == "recovering"

    def test_empty_timeline(self):
        from engine.pool_velocity import compute_pool_velocity
        result = compute_pool_velocity([])
        assert result["handles_per_hour"] == 0.0
        assert result["trend"] == "stable"

    def test_single_point(self):
        from engine.pool_velocity import compute_pool_velocity
        result = compute_pool_velocity([
            {"available": 5, "captured_at": datetime.now(timezone.utc).isoformat()},
        ])
        assert result["trend"] == "stable"


class TestEstimateExhaustion:
    def test_depleting_pool_has_eta(self):
        from engine.pool_velocity import estimate_exhaustion
        eta = estimate_exhaustion(current_available=6, velocity=-2.0)
        assert eta is not None
        assert eta == 3.0

    def test_stable_pool_no_eta(self):
        from engine.pool_velocity import estimate_exhaustion
        eta = estimate_exhaustion(current_available=6, velocity=0.0)
        assert eta is None

    def test_recovering_pool_no_eta(self):
        from engine.pool_velocity import estimate_exhaustion
        eta = estimate_exhaustion(current_available=6, velocity=1.0)
        assert eta is None

    def test_already_empty(self):
        from engine.pool_velocity import estimate_exhaustion
        eta = estimate_exhaustion(current_available=0, velocity=-2.0)
        assert eta is None


class TestRecyclingRate:
    def test_handles_returning(self):
        from engine.pool_velocity import compute_recycling_rate
        now = datetime.now(timezone.utc)
        timeline = [
            {"available": 2, "captured_at": (now - timedelta(hours=2)).isoformat()},
            {"available": 4, "captured_at": (now - timedelta(hours=1)).isoformat()},
            {"available": 6, "captured_at": now.isoformat()},
        ]
        rate = compute_recycling_rate(timeline)
        assert rate > 0

    def test_no_recovery(self):
        from engine.pool_velocity import compute_recycling_rate
        now = datetime.now(timezone.utc)
        timeline = [
            {"available": 10, "captured_at": (now - timedelta(hours=2)).isoformat()},
            {"available": 8, "captured_at": (now - timedelta(hours=1)).isoformat()},
            {"available": 6, "captured_at": now.isoformat()},
        ]
        rate = compute_recycling_rate(timeline)
        assert rate == 0.0


class TestPoolSnapshotDB:
    def test_save_pool_snapshot(self, db):
        from db.repository import save_pool_snapshot
        save_pool_snapshot(db, "test-pool", available=5, ready=5, min_required=3, total_handles=10)

    def test_get_pool_timeline(self, db):
        from db.repository import save_pool_snapshot, get_pool_timeline
        save_pool_snapshot(db, "timeline-pool", available=5, ready=5, min_required=3, total_handles=10)
        save_pool_snapshot(db, "timeline-pool", available=4, ready=4, min_required=3, total_handles=10)
        timeline = get_pool_timeline(db, "timeline-pool", hours=1)
        assert len(timeline) == 2
        assert timeline[0]["available"] == 5

    def test_pool_snapshot_model_exists(self):
        from db.models import PoolSnapshot
        assert hasattr(PoolSnapshot, "pool_name")
        assert hasattr(PoolSnapshot, "available")
        assert hasattr(PoolSnapshot, "captured_at")


class TestPoolDepletionRule:
    def test_pool_depletion_predicted_rule_exists(self):
        import yaml
        from pathlib import Path
        rules_path = Path(__file__).parent.parent / "policies" / "rules.yaml"
        data = yaml.safe_load(rules_path.read_text())
        rule_ids = [r["id"] for r in data["rules"]]
        assert "pool_depletion_predicted" in rule_ids

    def test_workload_exceeds_capacity_rule_exists(self):
        import yaml
        from pathlib import Path
        rules_path = Path(__file__).parent.parent / "policies" / "rules.yaml"
        data = yaml.safe_load(rules_path.read_text())
        rule_ids = [r["id"] for r in data["rules"]]
        assert "workload_exceeds_capacity" in rule_ids
