"""Tests for tolerant LLM JSON extraction (engine.llm_json).

The production classifier once scored 0/36 on the qualification flywheel
because prompts carried brace-doubled JSON examples rendered via
.replace() (not str.format), so models mirrored ``{{...}}`` back and every
reply failed json.loads. These tests pin both the tolerant parser and the
prompt-rendering rule that prevents the bug from returning.
"""

import json
from pathlib import Path

import yaml

from engine.llm_json import parse_llm_json

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


class TestParseLLMJson:
    def test_direct_json(self):
        assert parse_llm_json('{"proposed_class": "oom_killed"}') == {"proposed_class": "oom_killed"}

    def test_prose_wrapped(self):
        assert parse_llm_json('Prefix text {"a": 1} trailing suffix') == {"a": 1}

    def test_first_object_wins(self):
        assert parse_llm_json('{"a": 1} then {"b": 2}') == {"a": 1}

    def test_nested_objects_stay_intact(self):
        reply = '{"outer": {"inner": 2}, "note": "brace } inside string"}'
        assert parse_llm_json(reply) == json.loads(reply)

    def test_markdown_fenced(self):
        assert parse_llm_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_bare_fence(self):
        assert parse_llm_json('```\n{"a": 1}\n```') == {"a": 1}

    def test_doubled_braces(self):
        """Models mirror the brace-doubled example from a mis-rendered prompt."""
        reply = '{{"proposed_class": "oom_killed", "confidence": 0.9}}'
        assert parse_llm_json(reply) == {"proposed_class": "oom_killed", "confidence": 0.9}

    def test_fenced_doubled_braces(self):
        assert parse_llm_json('```json\n{{"a": 1}}\n```') == {"a": 1}

    def test_doubled_braces_inside_values_survive_direct_parse(self):
        raw = '{"reasoning": "matched {{pattern}} in evidence"}'
        assert parse_llm_json(raw) == json.loads(raw)

    def test_non_dict_json_rejected(self):
        assert parse_llm_json('[1, 2, 3]') is None
        assert parse_llm_json('"scalar"') is None
        assert parse_llm_json('42') is None

    def test_garbage_returns_none(self):
        assert parse_llm_json("not json at all") is None
        assert parse_llm_json("{unterminated") is None

    def test_empty_and_wrong_types_return_none(self):
        assert parse_llm_json("") is None
        assert parse_llm_json("   ") is None
        assert parse_llm_json(None) is None
        assert parse_llm_json({"already": "parsed"}) is None


class TestPromptRenderSafety:
    def test_no_doubled_braces_in_prompt_templates(self):
        """user_template is rendered via .replace(), not str.format().

        Doubled braces in a YAML prompt's JSON example leak verbatim to the
        model, which mirrors them back unparseable. This regression test
        fails if any prompt reintroduces ``{{`` in user_template.
        """
        offenders = []
        for path in sorted(PROMPTS_DIR.glob("*.yaml")):
            data = yaml.safe_load(path.read_text())
            template = data.get("user_template") if isinstance(data, dict) else None
            if template and "{{" in template:
                offenders.append(path.name)
        assert not offenders, f"prompts with doubled braces in user_template: {offenders}"
