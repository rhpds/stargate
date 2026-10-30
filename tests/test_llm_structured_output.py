"""Transport contracts: schema enforcement and explicit reasoning accounting."""
import json
import pytest


@pytest.mark.parametrize("reported_reasoning", [60, None])
def test_schema_on_wire_and_reasoning_usage_without_reasoning_text(monkeypatch, reported_reasoning):
    from api import llm
    monkeypatch.setattr(llm, "LLM_URL", "https://model.invalid/v1/chat/completions")
    monkeypatch.setattr(llm._circuit, "check", lambda: True)
    monkeypatch.setattr(llm._circuit, "record_success", lambda: None)
    seen = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return json.dumps({"choices": [{"finish_reason": "stop", "message": {
                "content": '{"ok":true}', "reasoning_content": "private internal reasoning"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 80, "total_tokens": 180,
                          "completion_tokens_details": {"reasoning_tokens": reported_reasoning}}}).encode()

    def urlopen(req, **kwargs):
        seen.append(json.loads(req.data))
        return Response()

    monkeypatch.setattr(llm.urllib_req, "urlopen", urlopen)
    fmt = {"type": "json_schema", "json_schema": {"name": "test", "strict": True,
           "schema": {"type": "object", "properties": {"ok": {"type": "boolean"}},
                      "required": ["ok"], "additionalProperties": False}}}
    result = llm.call_llm("adjudication-test", [{"role": "user", "content": "JSON"}],
                          model="deepseek-r1-distill-qwen-14b", response_format=fmt,
                          thinking_token_budget=128)
    assert seen[0]["response_format"] == fmt
    assert seen[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "extra_body" not in seen[0]
    assert seen[0]["num_retries"] == 0 and seen[0]["fallbacks"] == []
    assert seen[0]["max_retries"] == 0
    assert seen[0]["thinking_token_budget"] == 128
    assert result["usage"]["completion_tokens"] == 80
    assert result["usage"]["reasoning_tokens"] == reported_reasoning
    assert result["usage"]["total_tokens"] == 180  # Do not double-count reasoning.
    assert result["reasoning_present"] is True
    assert "private internal reasoning" not in json.dumps(result)


def test_adjudication_schema_requires_all_claims_and_typed_judge_slots():
    from engine.adjudication import _response_format
    schema = _response_format(["initial", "tool-1"], judge=True)["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    props = schema["properties"]
    assert props["claims"]["minItems"] == props["claims"]["maxItems"] == 3
    assert props["reviewer_verdicts"]["minItems"] == props["reviewer_verdicts"]["maxItems"] == 2
    assert props["verdict_agreement"]["type"] == "boolean"
    assert props["evidence_ids"]["items"]["enum"] == ["initial", "tool-1"]


def test_judge_schema_locks_exact_validated_verdict_pair():
    from engine.adjudication import _response_format
    schema = _response_format(["initial"], judge=True,
                              reviewer_verdicts=["INVALID", "UNKNOWN"])["json_schema"]["schema"]
    assert schema["properties"]["reviewer_verdicts"]["enum"] == [["INVALID", "UNKNOWN"]]
