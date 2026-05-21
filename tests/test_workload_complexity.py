"""TDD tests — Workload complexity scoring from AgnosticV constraints."""


class TestWorkloadComplexity:
    def test_compute_complexity_score_exists(self):
        from engine.workload_complexity import compute_complexity_score
        assert callable(compute_complexity_score)

    def test_simple_lab_low_score(self):
        from engine.workload_complexity import compute_complexity_score
        result = compute_complexity_score({
            "workload_count": 1,
            "timeout_seconds": 1800,
        })
        assert result["score"] < 0.4
        assert result["estimated_provision_minutes"] > 0

    def test_complex_ai_lab_high_score(self):
        from engine.workload_complexity import compute_complexity_score
        result = compute_complexity_score({
            "workload_count": 8,
            "collections": [{"name": f"c{i}", "version": "1.0"} for i in range(6)],
            "worker_instance_count": 4,
            "ai_workers_cores": 32,
            "timeout_seconds": 7200,
            "components": [{"name": f"comp{i}"} for i in range(4)],
            "cloud_provider": "cnv",
        })
        assert result["score"] > 0.6
        assert result["resource_weight"] > 1.0
        assert result["components"]["cloud_multiplier"] == 1.2

    def test_tenant_namespace_minimal_score(self):
        from engine.workload_complexity import compute_complexity_score
        result = compute_complexity_score({
            "workload_count": 0,
            "config": "tenant",
        })
        assert result["score"] < 0.15
        assert result["components"]["cloud_multiplier"] == 0.5

    def test_missing_fields_default_gracefully(self):
        from engine.workload_complexity import compute_complexity_score
        result = compute_complexity_score({})
        assert "score" in result
        assert "estimated_provision_minutes" in result
        assert "resource_weight" in result
        assert result["score"] >= 0.0

    def test_string_values_handled(self):
        from engine.workload_complexity import compute_complexity_score
        result = compute_complexity_score({
            "workload_count": "3",
            "worker_instance_count": "2",
            "ai_workers_cores": "16",
            "timeout_seconds": "3600",
        })
        assert result["score"] > 0.2
        assert result["components"]["workers"] == 2

    def test_score_capped_at_one(self):
        from engine.workload_complexity import compute_complexity_score
        result = compute_complexity_score({
            "workload_count": 100,
            "collections": [{"name": f"c{i}"} for i in range(50)],
            "worker_instance_count": 20,
            "ai_workers_cores": 256,
            "timeout_seconds": 99999,
            "components": [{"name": f"comp{i}"} for i in range(20)],
            "cloud_provider": "cnv",
        })
        assert result["score"] <= 1.0
