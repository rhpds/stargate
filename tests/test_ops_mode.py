"""Operations Mode Tests — pivoting from Summit-specific to day-to-day ops.

RED/GREEN TDD: tests written FIRST. Config changes don't exist yet.
"""

import pytest
from tests.conftest import client, db


class TestOperationsMode:
    def test_event_config_exists(self):
        """EVENT_DATE, EVENT_NAME, EVENT_PREFIX config vars exist in shared."""
        from api.routers._shared import EVENT_DATE, EVENT_NAME, EVENT_PREFIX
        # Defaults: no event configured = continuous ops
        assert EVENT_NAME is not None  # has a default

    def test_no_event_date_operational_mode(self, client):
        """Without event date, readiness shows operational status."""
        resp = client.get("/dashboard/readiness")
        assert resp.status_code == 200
        data = resp.json()
        # Should not say "Summit"
        assert "summit" not in str(data).lower() or "days_until_event" in data

    def test_labs_endpoint_exists(self, client):
        """GET /dashboard/labs works (renamed from /dashboard/summit)."""
        resp = client.get("/dashboard/labs")
        assert resp.status_code == 200

    def test_summit_endpoint_backward_compat(self, client):
        """GET /dashboard/summit still works as alias."""
        resp = client.get("/dashboard/summit")
        assert resp.status_code == 200

    def test_labs_and_summit_return_same_data(self, client):
        """Both endpoints return the same structure."""
        labs = client.get("/dashboard/labs").json()
        summit = client.get("/dashboard/summit").json()
        assert "labs" in labs
        assert "labs" in summit


class TestPrompts:
    def test_executive_summary_no_summit(self):
        """Executive summary prompt doesn't hardcode Summit 2026."""
        from api.llm import load_prompt
        prompt = load_prompt("executive-summary")
        system = prompt.get("system", "")
        assert "Summit 2026" not in system

    def test_remediation_no_summit(self):
        """Remediation prompt doesn't hardcode Summit 2026."""
        from api.llm import load_prompt
        prompt = load_prompt("remediation")
        system = prompt.get("system", "")
        assert "Summit 2026" not in system


class TestPolicyUrgency:
    def test_urgency_not_hardcoded_day1(self):
        """Policy engine doesn't hardcode 'Day 1' for urgency."""
        import inspect
        from engine import policy
        source = inspect.getsource(policy.generate_recommendations)
        assert '"Day 1"' not in source


class TestFrontendText:
    def test_dashboard_title_not_summit(self):
        """Dashboard page title is generic, not 'Summit 2026'."""
        from pathlib import Path
        dashboard = Path(__file__).parent.parent / "frontend" / "src" / "pages" / "Dashboard.tsx"
        content = dashboard.read_text()
        assert "Summit 2026" not in content

    def test_readiness_banner_not_summit(self):
        """Readiness banner doesn't say 'days to Summit'."""
        from pathlib import Path
        banner = Path(__file__).parent.parent / "frontend" / "src" / "components" / "ReadinessBanner.tsx"
        content = banner.read_text()
        assert "days to Summit" not in content
