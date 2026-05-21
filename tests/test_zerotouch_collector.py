"""TDD tests — ZeroTouch collector: catalog items, workshops, dashboard endpoint."""


class TestZeroTouchCatalog:
    def test_collect_catalog_items_function_exists(self):
        from collectors.zerotouch.collect_zerotouch import collect_catalog_items
        assert callable(collect_catalog_items)

    def test_collect_catalog_items_no_url_returns_empty(self):
        from collectors.zerotouch.collect_zerotouch import collect_catalog_items
        result = collect_catalog_items("")
        assert result == []


class TestZeroTouchWorkshop:
    def test_collect_workshop_availability_function_exists(self):
        from collectors.zerotouch.collect_zerotouch import collect_workshop_availability
        assert callable(collect_workshop_availability)

    def test_collect_workshop_no_url_returns_empty(self):
        from collectors.zerotouch.collect_zerotouch import collect_workshop_availability
        result = collect_workshop_availability("", ["ws1", "ws2"])
        assert result == {}

    def test_collect_workshop_no_ids_returns_empty(self):
        from collectors.zerotouch.collect_zerotouch import collect_workshop_availability
        result = collect_workshop_availability("http://example.com", None)
        assert result == {}


class TestSummarizeZeroTouch:
    def test_summarize_returns_required_fields(self):
        from collectors.zerotouch.collect_zerotouch import summarize_zerotouch, _cache
        _cache["data"] = None
        _cache["ts"] = 0
        result = summarize_zerotouch("")
        assert "available" in result
        assert "catalog_total" in result
        assert "catalog_active" in result
        assert "workshops" in result
        assert "timestamp" in result

    def test_summarize_not_available_without_url(self):
        from collectors.zerotouch.collect_zerotouch import summarize_zerotouch, _cache
        _cache["data"] = None
        _cache["ts"] = 0
        result = summarize_zerotouch("")
        assert result["available"] is False


class TestZeroTouchDashboard:
    def test_endpoint_exists(self, client):
        resp = client.get("/dashboard/zerotouch")
        assert resp.status_code == 200
        data = resp.json()
        assert "catalog_total" in data
        assert "workshops" in data

    def test_freshness_includes_zerotouch(self):
        from api.contracts import get_freshness
        freshness = get_freshness()
        assert "zerotouch" in freshness
