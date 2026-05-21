"""RED/GREEN TDD — Visual storytelling backend data."""


class TestActionStrip:
    """Action strip shows top 3 actionable items."""

    def test_action_strip_endpoint(self, client):
        resp = client.get("/dashboard/action-strip")
        assert resp.status_code == 200
        data = resp.json()
        assert "actions" in data
        assert "source_freshness" in data

    def test_actions_have_required_fields(self, client):
        resp = client.get("/dashboard/action-strip")
        data = resp.json()
        for action in data.get("actions", []):
            assert "message" in action
            assert "urgency" in action
            assert "count" in action
            assert "link_tab" in action


class TestAISummary:
    """AI summary card provides top issues with evidence."""

    def test_ai_summary_endpoint(self, client):
        resp = client.get("/dashboard/ai-summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "top_issues" in data
        assert "recommendation" in data

    def test_top_issues_have_evidence(self, client):
        resp = client.get("/dashboard/ai-summary")
        data = resp.json()
        for issue in data.get("top_issues", []):
            assert "message" in issue
            assert "urgency" in issue
            assert "source" in issue


class TestRecommendationEvidence:
    """Recommendations include evidence summary."""

    def test_recommendations_have_evidence_summary(self, client):
        resp = client.get("/dashboard/provisioning-recommendations")
        data = resp.json()
        for rec in data.get("recommendations", [])[:5]:
            assert "evidence" in rec or "evidence_summary" in rec
