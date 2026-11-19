"""MCP usage must be answerable after the logs rotate."""

from datetime import datetime, timedelta, timezone


def _call(db, key_id, method, tool=None, minutes=5):
    from db.models import MCPCall
    db.add(MCPCall(
        called_at=datetime.now(timezone.utc) - timedelta(minutes=minutes),
        key_id=key_id, method=method, tool=tool, path="/mcp/",
    ))
    db.commit()


class TestMCPUsage:
    def test_counts_by_key_and_tool(self, db, monkeypatch):
        from db.repository import mcp_usage
        monkeypatch.setenv("STARGATE_API_KEY_LABELS", '{"929e6e5f": "wharris"}')

        _call(db, "929e6e5f", "tools/call", "get_lab_session")
        _call(db, "929e6e5f", "tools/call", "get_lab_session")
        _call(db, "629de852", "tools/call", "query_evaluations")
        _call(db, "629de852", "tools/list")

        report = mcp_usage(db, hours=24)

        assert report["total"] == 4
        keys = {row["key_id"]: row for row in report["by_key"]}
        assert keys["929e6e5f"]["label"] == "wharris"
        assert keys["929e6e5f"]["calls"] == 2
        assert keys["629de852"]["label"] == ""
        tools = {row["tool"]: row["calls"] for row in report["tools"]}
        assert tools == {"get_lab_session": 2, "query_evaluations": 1}
        assert report["methods"]["tools/list"] == 1

    def test_ignores_calls_outside_the_window(self, db):
        from db.repository import mcp_usage
        _call(db, "abc", "tools/call", "ask", minutes=60 * 48)
        assert mcp_usage(db, hours=24)["total"] == 0

    def test_mcp_tool_returns_the_report(self, db, monkeypatch):
        from api import mcp_server
        monkeypatch.setattr(mcp_server, "_db", lambda: db)
        _call(db, "abc", "tools/call", "ask")
        assert '"total": 1' in mcp_server.get_mcp_usage(hours=24)
