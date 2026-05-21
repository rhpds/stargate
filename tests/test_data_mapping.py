"""RED/GREEN TDD — Data mapping validation endpoint."""


class TestDataMapping:
    """Validate data source joins across all labs."""

    def test_endpoint_exists(self, client):
        resp = client.get("/dashboard/data-mapping")
        assert resp.status_code == 200

    def test_returns_labs_with_source_status(self, client):
        resp = client.get("/dashboard/data-mapping")
        data = resp.json()
        assert "labs" in data
        if data["labs"]:
            lab = data["labs"][0]
            assert "lab_code" in lab
            assert "sources" in lab
            sources = lab["sources"]
            for src in ["labagator", "babylon", "pools", "demolition", "scanner", "agnosticv", "llm"]:
                assert src in sources, f"Missing source: {src}"
                assert "connected" in sources[src]

    def test_returns_join_keys(self, client):
        resp = client.get("/dashboard/data-mapping")
        data = resp.json()
        assert "join_keys" in data
        assert len(data["join_keys"]) >= 5
        for jk in data["join_keys"]:
            assert "from_source" in jk
            assert "to_source" in jk
            assert "key" in jk
            assert "reliability" in jk
            assert jk["reliability"] in ("high", "medium", "low")

    def test_returns_summary(self, client):
        resp = client.get("/dashboard/data-mapping")
        data = resp.json()
        assert "summary" in data
        summary = data["summary"]
        assert "total_labs" in summary
        assert "fully_connected" in summary
        assert "partially_connected" in summary
        assert "disconnected" in summary

    def test_labagator_always_connected(self, client):
        resp = client.get("/dashboard/data-mapping")
        data = resp.json()
        for lab in data.get("labs", []):
            assert lab["sources"]["labagator"]["connected"] is True

    def test_labs_have_join_health(self, client):
        resp = client.get("/dashboard/data-mapping")
        data = resp.json()
        for lab in data.get("labs", []):
            assert "join_health" in lab
            assert "issues" in lab

    def test_summary_counts_add_up(self, client):
        resp = client.get("/dashboard/data-mapping")
        data = resp.json()
        s = data["summary"]
        assert s["fully_connected"] + s["partially_connected"] + s["disconnected"] == s["total_labs"]
