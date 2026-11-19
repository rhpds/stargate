"""Documentation must not drift from the code.

Each case here is a drift that actually happened: tool counts went stale, and
the API image shipped without docs/, so `ask` retrieved taxonomy only.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tool_count() -> int:
    return (ROOT / "api" / "mcp_server.py").read_text().count("@mcp.tool()")


class TestToolCounts:
    def test_readme_states_the_real_number(self):
        readme = (ROOT / "README.md").read_text()
        count = _tool_count()
        assert f"{count} tools (" in readme
        assert f"({count} tools at /mcp)" in readme

    def test_agent_guide_lists_every_tool(self):
        guide = (ROOT / "docs" / "stargate-mcp-agent-guide.md").read_text()
        rows = [line for line in guide.splitlines() if line.startswith("| **")]
        assert len(rows) == _tool_count()

    def test_guide_heading_matches(self):
        guide = (ROOT / "docs" / "stargate-mcp-agent-guide.md").read_text()
        assert f"## The tools ({_tool_count()} total" in guide


class TestCorpus:
    def test_containerfile_ships_the_docs(self):
        containerfile = (ROOT / "Containerfile").read_text()
        assert "COPY docs/ docs/" in containerfile, (
            "ask retrieves from docs/; without this COPY the corpus is taxonomy only"
        )

    def test_listed_docs_exist(self):
        from engine.stargate_qa import _DOC_FILES

        missing = [
            name for name in _DOC_FILES
            if not name.startswith("confluence/")
            and not (ROOT / "docs" / name).exists()
        ]
        assert missing == [], f"listed in the corpus but missing: {missing}"
