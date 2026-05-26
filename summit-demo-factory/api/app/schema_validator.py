"""Validate data dicts against JSON schemas in evidence-schemas/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import jsonschema

SCHEMA_DIR = Path(__file__).parent.parent.parent / "evidence-schemas"

_schema_cache: Dict[str, dict] = {}


class SchemaValidationError(Exception):
    def __init__(self, schema_name: str, errors: list):
        self.schema_name = schema_name
        self.errors = errors
        super().__init__(f"Validation against {schema_name} failed: {errors}")


def _load_schema(name: str) -> dict:
    if name not in _schema_cache:
        path = SCHEMA_DIR / name
        if not path.exists():
            raise SchemaValidationError(name, [f"Schema file not found: {path}"])
        try:
            _schema_cache[name] = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            raise SchemaValidationError(name, [f"Invalid JSON in schema: {e}"])
    return _schema_cache[name]


def validate_against_schema(schema_name: str, data: Dict[str, Any]) -> None:
    schema = _load_schema(schema_name)
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        raise SchemaValidationError(schema_name, [e.message]) from e


def validate_evidence(data: Dict[str, Any]) -> None:
    validate_against_schema("evidence.schema.json", data)


def validate_run(data: Dict[str, Any]) -> None:
    validate_against_schema("run.schema.json", data)
