from __future__ import annotations

import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

from engine.models import Rubric


class RubricLoadError(Exception):
    pass


def load_rubric(path: Path) -> Rubric:
    if not path.exists():
        raise RubricLoadError(f"Rubric file not found: {path}")
    if not path.suffix in (".yaml", ".yml"):
        raise RubricLoadError(f"Rubric file must be YAML: {path}")

    raw = path.read_text()
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise RubricLoadError(f"Invalid YAML in {path}: {e}") from e

    if data is None:
        raise RubricLoadError(f"Rubric file is empty: {path}")
    if not isinstance(data, dict):
        raise RubricLoadError(f"Rubric must be a YAML mapping, got {type(data).__name__}")

    try:
        return Rubric(**data)
    except ValidationError as e:
        raise RubricLoadError(f"Rubric validation failed for {path}: {e}") from e


def load_rubrics_from_directory(directory: Path) -> list[Rubric]:
    if not directory.is_dir():
        raise RubricLoadError(f"Not a directory: {directory}")

    rubrics = []
    for path in sorted(directory.glob("*.yaml")):
        rubrics.append(load_rubric(path))
    for path in sorted(directory.glob("*.yml")):
        rubrics.append(load_rubric(path))
    return rubrics


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m api.app.rubric_loader <path>")
        sys.exit(1)

    target = Path(sys.argv[1])
    if target.is_dir():
        rubrics = load_rubrics_from_directory(target)
        for r in rubrics:
            print(f"  {r.id} ({r.version}) - {len(r.exit_criteria)} exit criteria")
        print(f"Loaded {len(rubrics)} rubrics.")
    else:
        rubric = load_rubric(target)
        print(f"  {rubric.id} ({rubric.version}) - {len(rubric.exit_criteria)} exit criteria")
