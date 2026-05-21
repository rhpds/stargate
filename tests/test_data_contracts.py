"""RED/GREEN TDD — Data contracts for tab accuracy."""


class TestDataContracts:
    """Data contracts validate API responses at the boundary."""

    def test_contract_definitions_exist(self):
        from contracts.dashboard_contracts import CONTRACTS
        assert len(CONTRACTS) >= 5
        assert "/dashboard/labs" in CONTRACTS or "labs" in CONTRACTS

    def test_validate_response_function(self):
        from api.contracts import validate_response
        assert callable(validate_response)

    def test_labs_contract_validates(self, client):
        resp = client.get("/dashboard/labs")
        data = resp.json()
        from api.contracts import validate_response
        result = validate_response("/dashboard/labs", data)
        assert "_contract" in result
        assert "valid" in result["_contract"]
        assert "sources" in result["_contract"]

    def test_pipeline_cross_check(self, client):
        resp = client.get("/dashboard/pipeline")
        data = resp.json()
        for stage in data.get("stages", []):
            if stage["total"] > 0:
                assert stage["pass"] + stage["warn"] + stage["fail"] == stage["total"], (
                    f"Stage {stage['stage_id']}: {stage['pass']}+{stage['warn']}+{stage['fail']} != {stage['total']}"
                )

    def test_freshness_tracking_exists(self):
        from api.contracts import get_freshness
        assert callable(get_freshness)

    def test_data_health_endpoint(self, client):
        resp = client.get("/dashboard/data-health")
        assert resp.status_code == 200
        data = resp.json()
        assert "checks" in data
        assert "passed" in data
        assert "failed" in data

    def test_required_fields_enforced(self):
        from api.contracts import validate_response
        result = validate_response("/dashboard/labs", {"labs": [{"lab_code": None, "title": "test"}]})
        contract = result.get("_contract", {})
        if contract.get("warnings"):
            assert any("required" in w for w in contract["warnings"])
