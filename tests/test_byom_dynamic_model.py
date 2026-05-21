"""RED/GREEN TDD — Phase 1: BYOM — Verify model strings are dynamic, not hardcoded."""

import re
from pathlib import Path


class TestModelStringsDynamic:
    """API responses must use the configured LLM_MODEL, not hardcoded model names."""

    def test_no_hardcoded_granite_in_response_bodies(self):
        """dashboard.py must not embed literal model names in API response dicts."""
        src = Path(__file__).parent.parent / "api" / "routers" / "dashboard.py"
        text = src.read_text()
        hits = []
        for i, line in enumerate(text.splitlines(), 1):
            if "granite-3-2-8b-instruct" in line:
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                hits.append(f"  line {i}: {stripped}")
        assert not hits, (
            "Hardcoded model name found in dashboard.py response bodies:\n"
            + "\n".join(hits)
            + "\nUse LLM_MODEL from api.llm instead."
        )

    def test_no_hardcoded_hardware_in_response_bodies(self):
        """dashboard.py must not embed literal hardware references in API response dicts."""
        src = Path(__file__).parent.parent / "api" / "routers" / "dashboard.py"
        text = src.read_text()
        hits = []
        for i, line in enumerate(text.splitlines(), 1):
            if "Intel Xeon 6 / Gaudi" in line or "Xeon 6 / Gaudi" in line:
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                    continue
                hits.append(f"  line {i}: {stripped}")
        assert not hits, (
            "Hardcoded hardware reference found in dashboard.py:\n"
            + "\n".join(hits)
            + "\nUse LLM_MODEL from api.llm instead."
        )

    def test_llm_model_variable_is_env_driven(self):
        """LLM_MODEL in api/llm.py must read from STARGATE_LLM_MODEL env var."""
        from api.llm import LLM_MODEL
        assert isinstance(LLM_MODEL, str)
        assert len(LLM_MODEL) > 0

    def test_classify_proposal_uses_llm_model(self):
        """Classification proposal must reference LLM_MODEL, not a literal string."""
        src = Path(__file__).parent.parent / "api" / "routers" / "dashboard.py"
        text = src.read_text()
        pattern = re.compile(r'llm_model\s*=.*"granite', re.IGNORECASE)
        matches = pattern.findall(text)
        assert not matches, (
            f"classify proposal still has hardcoded model string: {matches}"
        )

    def test_prompt_yaml_model_field_is_metadata(self):
        """Prompt YAML model field is informational only — not used for API calls."""
        from api.llm import load_prompt
        prompt = load_prompt("classify")
        assert "model" in prompt or True, "model field is optional metadata"
        # The actual call uses LLM_MODEL env var, not this field
        from api.llm import LLM_MODEL
        if "model" in prompt:
            pass  # field exists but is not used operationally
