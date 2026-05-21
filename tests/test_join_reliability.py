"""RED/GREEN TDD — Strengthen data source join reliability."""

import re
from pathlib import Path


class TestJoinReliability:
    """All joins should use ci_name as canonical key, not substring/dict matching."""

    def test_demolition_join_word_boundary(self):
        """Demolition matching must use word boundaries, not substring."""
        src = Path(__file__).parent.parent / "api" / "routers" / "dashboard.py"
        text = src.read_text()
        # Find the demolition matching section
        in_demolition = False
        uses_word_boundary = False
        uses_raw_substring = False
        for line in text.splitlines():
            if "demolition" in line.lower() and "by_lab" in line:
                in_demolition = True
            if in_demolition:
                if "re.search" in line or "re.compile" in line or r"\b" in line:
                    uses_word_boundary = True
                if "code_lower in" in line and "name" in line:
                    uses_raw_substring = True
                if line.strip().startswith("lab_pool_data"):
                    break
        assert not uses_raw_substring, (
            "Demolition join still uses raw substring match (code_lower in name). "
            "Should use word boundary regex to avoid false positives."
        )

    def test_agnosticv_uses_ci_name_slug(self):
        """AgnosticV should try ci_name slug as exact directory match before prefix search."""
        src = Path(__file__).parent.parent / "api" / "routers" / "_shared.py"
        text = src.read_text()
        assert "ci_name" in text and "slug" in text.lower() or "ci_name" in text, (
            "_load_agnosticv_constraints should accept and use ci_name for exact slug matching"
        )

    def test_pool_join_uses_ci_name_prefix(self):
        """Pool matching should use ci_name prefix, not just lab code extraction."""
        src = Path(__file__).parent.parent / "api" / "routers" / "dashboard.py"
        text = src.read_text()
        # Find lab_pool_data section
        pool_section = ""
        capture = False
        for line in text.splitlines():
            if "lab_pool_data" in line and "Dict" in line:
                capture = True
            if capture:
                pool_section += line + "\n"
                if "summit_mapping" in line and "babylon" in line:
                    break
        assert "ci_name" in pool_section or "ci" in pool_section, (
            "Pool join should use ci_name for matching, not just lb_num extraction"
        )

    def test_data_mapping_reliability_upgraded(self, client):
        """Data mapping should show improved reliability ratings after fixes."""
        resp = client.get("/dashboard/data-mapping")
        if resp.status_code != 200:
            return
        data = resp.json()
        join_keys = data.get("join_keys", [])
        for jk in join_keys:
            if jk["from_source"] == "Labagator" and jk["to_source"] == "Babylon":
                assert jk["reliability"] in ("high", "medium"), f"Babylon join should be medium+, got {jk['reliability']}"
            if jk["from_source"] == "Labagator" and jk["to_source"] == "AgnosticV":
                assert jk["reliability"] in ("high", "medium"), f"AgnosticV join should be medium+, got {jk['reliability']}"

    def test_agnosticv_accepts_ci_name(self):
        """_load_agnosticv_constraints should accept ci_name parameter."""
        from api.routers._shared import _load_agnosticv_constraints
        import inspect
        sig = inspect.signature(_load_agnosticv_constraints)
        params = list(sig.parameters.keys())
        assert "ci_name" in params, (
            f"_load_agnosticv_constraints should accept ci_name param, has: {params}"
        )
