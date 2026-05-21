"""RED/GREEN TDD — Phase D proof via synthetic emulator + test namespace execution."""


class TestPhaseDProof:
    """Full OBSERVE → EVALUATE → RECOMMEND → EXECUTE → VERIFY → LEARN loop."""

    def test_phase_d_endpoint_exists(self, client):
        """POST /admin/run-phase-d-test must exist and return results."""
        resp = client.post("/admin/run-phase-d-test")
        assert resp.status_code == 200
        data = resp.json()
        assert "phase" in data
        assert data["phase"] == "D"
        assert "steps" in data

    def test_mock_validate_step(self, client):
        """Phase D includes mock validation of all scenarios."""
        resp = client.post("/admin/run-phase-d-test")
        data = resp.json()
        steps = data.get("steps", [])
        mock_step = next((s for s in steps if s.get("step") == "mock_validate"), None)
        assert mock_step is not None, "Phase D must include mock_validate step"

    def test_mock_execute_step(self, client):
        """Phase D includes mock execution with command validation."""
        resp = client.post("/admin/run-phase-d-test")
        data = resp.json()
        steps = data.get("steps", [])
        exec_step = next((s for s in steps if s.get("step") == "mock_execute"), None)
        assert exec_step is not None, "Phase D must include mock_execute step"

    def test_receipt_generated(self, client):
        """Phase D generates a receipt with evidence."""
        resp = client.post("/admin/run-phase-d-test")
        data = resp.json()
        assert "receipt" in data
        receipt = data["receipt"]
        assert receipt.get("phase") == "D"
        assert "evidence" in receipt
