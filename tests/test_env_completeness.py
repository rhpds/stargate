"""EDD tests — Every env var referenced in code exists in .env.example."""

import os
import re
from pathlib import Path

import pytest


PROJECT_DIR = Path(__file__).parent.parent
SOURCE_DIRS = ("api", "cli", "collectors", "constraints", "contracts", "db", "engine",
               "events", "integrations", "proposals", "qualify", "scripts", "tasks", "alembic")


def _find_env_vars_in_code(root=PROJECT_DIR) -> set:
    """Check runtime sources, not test fixtures, vendored code or environments."""
    pattern = re.compile(r'os\.(?:environ\.get|getenv)\(\s*["\'](STARGATE_[A-Z0-9_]+)["\']')
    found = set()
    sources = list(root.glob("*.py"))
    for directory in SOURCE_DIRS:
        sources.extend((root / directory).rglob("*.py"))
    for py in sources:
        if "__pycache__" in str(py) or "node_modules" in str(py):
            continue
        try:
            text = py.read_text()
            found.update(pattern.findall(text))
        except Exception:
            pass
    return found


def _read_env_example(env_file=None) -> set:
    """Read all var names from .env.example."""
    env_file = env_file or PROJECT_DIR / ".env.example"
    if not env_file.exists():
        return set()
    names = set()
    for line in env_file.read_text().splitlines():
        line = line.strip()
        # Commented optional assignments document a setting without enabling it.
        line = line.removeprefix("#").strip()
        match = re.match(r'^(STARGATE_[A-Z0-9_]+)\s*=', line)
        if match:
            names.add(match.group(1))
    return names


class TestEnvCompleteness:

    def test_scanner_handles_multiline_and_digit_names_without_test_fixtures(self, tmp_path):
        (tmp_path / "api").mkdir()
        (tmp_path / "api" / "example.py").write_text(
            'os.environ.get(\n "STARGATE_API_V2", "")\nos.getenv("STARGATE_OPTION", "")\n'
        )
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "example.py").write_text('os.environ.get("STARGATE_TEST_ONLY")')
        assert _find_env_vars_in_code(tmp_path) == {"STARGATE_API_V2", "STARGATE_OPTION"}

    def test_commented_optional_settings_are_documented(self, tmp_path):
        example = tmp_path / ".env.example"
        example.write_text('# Optional settings\n# STARGATE_OPTION=\nSTARGATE_ACTIVE=true\n')
        assert _read_env_example(example) == {"STARGATE_OPTION", "STARGATE_ACTIVE"}

    def test_env_example_exists(self):
        assert (PROJECT_DIR / ".env.example").exists()

    def test_all_code_vars_documented(self):
        code_vars = _find_env_vars_in_code()
        documented = _read_env_example()
        missing = code_vars - documented
        assert not missing, f"Env vars used in code but not in .env.example: {missing}"

    def test_no_empty_env_example(self):
        documented = _read_env_example()
        assert len(documented) > 5, f"Only {len(documented)} vars in .env.example"

    def test_critical_vars_present(self):
        documented = _read_env_example()
        critical = {"STARGATE_DATABASE_URL", "STARGATE_ADMIN_API_KEY", "STARGATE_LITELLM_URL"}
        missing = critical - documented
        assert not missing, f"Critical vars missing from .env.example: {missing}"
