"""Fixture loader for LLM quality test matrix.

Loads canned evidence bundles and LLM responses from fixtures/llm-quality/.
"""

import yaml
from pathlib import Path
from typing import Dict, List

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "llm-quality"

_fixture_cache: Dict[str, dict] = {}


def load_fixture(prompt_type: str, scenario: str) -> dict:
    key = f"{prompt_type}-{scenario}"
    if key not in _fixture_cache:
        path = FIXTURE_DIR / f"{key}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"Fixture not found: {path}")
        _fixture_cache[key] = yaml.safe_load(path.read_text())
    return _fixture_cache[key]


def load_all_fixtures() -> List[dict]:
    fixtures = []
    for path in sorted(FIXTURE_DIR.glob("*.yaml")):
        fixtures.append(yaml.safe_load(path.read_text()))
    return fixtures
