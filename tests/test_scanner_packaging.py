"""Regression: the scanner image must carry every local package its
entrypoints import at module load.

A missing COPY in Containerfile.scanner does not fail any unit test (the
repo checkout has every package) — it surfaces only at runtime as
ModuleNotFoundError CrashLoopBackOff in the deployed babylon-worker. This
test fails at commit time instead.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _scanner_copy_dirs() -> set:
    copied = set()
    for line in (ROOT / "Containerfile.scanner").read_text().splitlines():
        line = line.strip()
        if line.startswith("COPY "):
            parts = line.split()
            for part in parts[1:-1]:  # skip the COPY keyword and the destination
                if part.endswith("/"):
                    copied.add(part.rstrip("/"))
    return copied


def _module_level_local_imports(path: Path) -> set:
    """Local packages imported at module load time (crash the process if missing)."""
    tree = ast.parse(path.read_text())
    packages = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                packages.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            packages.add(node.module.split(".")[0])
    return {
        name for name in packages
        if (ROOT / name).is_dir() and (ROOT / name / "__init__.py").exists()
    }


def test_scanner_image_copies_every_module_level_import_of_its_entrypoints():
    copied = _scanner_copy_dirs()
    assert copied, "failed to parse COPY directives from Containerfile.scanner"
    for entrypoint in sorted((ROOT / "cli").glob("*.py")):
        missing = _module_level_local_imports(entrypoint) - copied
        assert not missing, (
            f"{entrypoint.name} imports {sorted(missing)} at module load but "
            f"Containerfile.scanner does not COPY them — the deployed worker "
            f"would CrashLoop on ModuleNotFoundError"
        )


def test_scanner_image_copies_the_contracts_layer():
    """Direct regression for the 2026-10-29 babylon-worker CrashLoop: the
    outcome contracts are a module-level dependency of the worker."""
    assert "contracts" in _scanner_copy_dirs()
