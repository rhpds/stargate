"""EDD tests — Every env var referenced in code exists in .env.example."""

import os
import re
from pathlib import Path

import pytest


PROJECT_DIR = Path(__file__).parent.parent


def _find_env_vars_in_code() -> set:
    """Find all STARGATE_* env var references in Python source."""
    pattern = re.compile(r'os\.environ\.get\(["\']?(STARGATE_[A-Z_]+)')
    found = set()
    for py in PROJECT_DIR.rglob("*.py"):
        if "__pycache__" in str(py) or "node_modules" in str(py):
            continue
        try:
            text = py.read_text()
            found.update(pattern.findall(text))
        except Exception:
            pass
    return found


def _read_env_example() -> set:
    """Read all var names from .env.example."""
    env_file = PROJECT_DIR / ".env.example"
    if not env_file.exists():
        return set()
    names = set()
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key = line.split("=")[0].strip()
        if key:
            names.add(key)
    return names


class TestEnvCompleteness:

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
