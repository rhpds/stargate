"""Tolerant JSON-object extraction from LLM replies.

The output contract for LLM endpoints is a single JSON object. In practice
replies arrive wrapped in markdown fences, embedded in prose, or — when the
prompt's own JSON example carried doubled braces — mirrored back as
``{{...}}``. This module extracts the first JSON object without inventing
content: a direct parse always wins; fence stripping, brace normalization,
and first-object scanning are fallbacks only. Replies that contain no JSON
object return ``None`` so callers keep their explicit fallback paths.
"""
from __future__ import annotations

import json
import re
from typing import Optional

_FENCE_RE = re.compile(r"```[a-zA-Z0-9_-]*\s*(.*?)\s*```", re.DOTALL)


def _normalize_braces(text: str) -> str:
    """Collapse doubled braces used to escape a JSON example in a prompt."""
    return text.replace("{{", "{").replace("}}", "}")


def _first_object(text: str) -> Optional[str]:
    """Return the first complete top-level ``{...}`` span in ``text``.

    Tracks string state so braces inside JSON string values do not confuse
    the depth counter; returns None when no complete object exists.
    """
    depth = 0
    start = None
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                return text[start:i + 1]
    return None


def _candidates(content: str):
    stripped = content.strip()
    yield stripped
    for match in _FENCE_RE.finditer(content):
        yield match.group(1).strip()
    first = _first_object(content)
    if first:
        yield first
    yield _normalize_braces(stripped)
    for match in _FENCE_RE.finditer(content):
        yield _normalize_braces(match.group(1).strip())
    if first:
        yield _normalize_braces(first)


def parse_llm_json(content: object) -> Optional[dict]:
    """Return the first JSON object found in an LLM reply, or ``None``.

    Candidates are tried cheapest-first: the raw reply, fenced blocks, the
    first brace-delimited object, then the same three with doubled braces
    collapsed. A candidate that parses to a non-object (list, scalar) is
    rejected; valid JSON embedded in string values is never rewritten
    because the direct parse wins before any normalization runs.
    """
    if not isinstance(content, str) or not content.strip():
        return None
    for candidate in _candidates(content):
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None
