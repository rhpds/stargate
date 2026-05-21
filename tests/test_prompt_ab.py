"""RED/GREEN TDD — Item 3: LLM prompt A/B testing."""

import os
from pathlib import Path
from unittest.mock import patch

import yaml


class TestPromptVersionSplitting:
    """load_prompt must support weighted variant selection."""

    def test_load_prompt_supports_variants(self, tmp_path):
        """When STARGATE_PROMPT_VARIANTS_CLASSIFY is set, load_prompt picks a variant."""
        from api.llm import load_prompt_with_variants
        assert callable(load_prompt_with_variants)

    def test_variant_selection_returns_valid_prompt(self, tmp_path):
        """Variant selection returns a prompt dict with version field."""
        v1 = tmp_path / "test-prompt.yaml"
        v1.write_text(yaml.dump({"version": "1.0", "system": "You are v1"}))
        v2 = tmp_path / "test-prompt-v1.1.yaml"
        v2.write_text(yaml.dump({"version": "1.1", "system": "You are v1.1"}))

        from api.llm import load_prompt_with_variants
        with patch.dict(os.environ, {"STARGATE_PROMPT_VARIANTS_TEST_PROMPT": "1.0:50,1.1:50"}):
            prompt = load_prompt_with_variants("test-prompt", prompts_dir=str(tmp_path))
        assert "version" in prompt
        assert prompt["version"] in ("1.0", "1.1")

    def test_no_variants_env_returns_default(self, tmp_path):
        """Without variant env var, returns the default prompt."""
        default = tmp_path / "classify.yaml"
        default.write_text(yaml.dump({"version": "1.0", "system": "default"}))

        from api.llm import load_prompt_with_variants
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STARGATE_PROMPT_VARIANTS_CLASSIFY", None)
            prompt = load_prompt_with_variants("classify", prompts_dir=str(tmp_path))
        assert prompt["version"] == "1.0"

    def test_variant_weights_respected(self, tmp_path):
        """100:0 weight should always select the first version."""
        v1 = tmp_path / "test.yaml"
        v1.write_text(yaml.dump({"version": "1.0", "system": "v1"}))
        v2 = tmp_path / "test-v2.0.yaml"
        v2.write_text(yaml.dump({"version": "2.0", "system": "v2"}))

        from api.llm import load_prompt_with_variants
        with patch.dict(os.environ, {"STARGATE_PROMPT_VARIANTS_TEST": "1.0:100,2.0:0"}):
            results = set()
            for _ in range(20):
                p = load_prompt_with_variants("test", prompts_dir=str(tmp_path))
                results.add(p["version"])
        assert results == {"1.0"}, f"Expected only 1.0, got {results}"


class TestPromptVariantFile:
    """A classify v1.1 variant must exist for A/B testing."""

    def test_classify_v11_exists(self):
        prompts_dir = Path(__file__).parent.parent / "prompts"
        v11 = prompts_dir / "classify-v1.1.yaml"
        assert v11.exists(), f"Missing {v11}"

    def test_classify_v11_has_version(self):
        prompts_dir = Path(__file__).parent.parent / "prompts"
        v11 = prompts_dir / "classify-v1.1.yaml"
        data = yaml.safe_load(v11.read_text())
        assert data.get("version") == "1.1"
