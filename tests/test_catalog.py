"""TDD tests — Platform catalog endpoint."""


class TestCatalogEndpoint:
    def test_endpoint_exists(self, client):
        resp = client.get("/dashboard/catalog")
        assert resp.status_code == 200

    def test_response_structure(self, client):
        resp = client.get("/dashboard/catalog")
        data = resp.json()
        assert "total" in data
        assert "active" in data
        assert "disabled" in data
        assert "by_category" in data
        assert "sources" in data
        assert "items" in data
        assert isinstance(data["items"], list)

    def test_items_have_required_fields(self, client):
        resp = client.get("/dashboard/catalog")
        data = resp.json()
        for item in data["items"][:5]:
            assert "name" in item
            assert "source" in item
            assert "disabled" in item
