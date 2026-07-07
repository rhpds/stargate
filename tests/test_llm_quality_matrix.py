"""LLM Quality Matrix Test — prompt x scenario x dimension = expected outcome.

RED/GREEN TDD: tests written FIRST, canned fixtures wired to pass.
Each cell validates: canned evidence + canned response -> quality evaluator -> outcome.

32-cell matrix: 2 prompt types x 4 scenarios x 4 dimensions.
"""

import pytest
from pathlib import Path

from engine.llm_quality_evaluator import evaluate_quality, load_quality_rubrics
from tests.llm_quality_fixtures import load_fixture

RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "llm-quality"
_rubrics = load_quality_rubrics(RUBRIC_DIR)

# (prompt_type, scenario, dimension, expected_outcome)
MATRIX = [
    # --- remediation: good response ---
    ("remediation", "good-lab-pods-not-ready", "tdd", "green"),
    ("remediation", "good-lab-pods-not-ready", "edd", "green"),
    ("remediation", "good-lab-pods-not-ready", "cdd", "green"),
    ("remediation", "good-lab-pods-not-ready", "bdd", "green"),

    # --- remediation: bad — hallucinated lab codes ---
    ("remediation", "bad-lab-hallucinated", "tdd", "yellow"),
    ("remediation", "bad-lab-hallucinated", "edd", "red"),
    ("remediation", "bad-lab-hallucinated", "cdd", "green"),
    ("remediation", "bad-lab-hallucinated", "bdd", "green"),

    # --- remediation: bad — empty/short response ---
    ("remediation", "bad-lab-empty", "tdd", "red"),
    ("remediation", "bad-lab-empty", "edd", "red"),
    ("remediation", "bad-lab-empty", "cdd", "green"),
    ("remediation", "bad-lab-empty", "bdd", "green"),

    # --- remediation: edge — no history in evidence ---
    ("remediation", "edge-no-history", "tdd", "green"),
    ("remediation", "edge-no-history", "edd", "red"),
    ("remediation", "edge-no-history", "cdd", "green"),
    ("remediation", "edge-no-history", "bdd", "green"),

    # --- classify: good — known failure ---
    ("classify", "good-known-failure", "tdd", "green"),
    ("classify", "good-known-failure", "edd", "green"),
    ("classify", "good-known-failure", "cdd", "green"),
    ("classify", "good-known-failure", "bdd", "green"),

    # --- classify: bad — invalid JSON ---
    ("classify", "bad-invalid-json", "tdd", "red"),
    ("classify", "bad-invalid-json", "edd", "red"),
    ("classify", "bad-invalid-json", "cdd", "red"),
    ("classify", "bad-invalid-json", "bdd", "green"),

    # --- classify: bad — hallucinated class ---
    ("classify", "bad-hallucinated-class", "tdd", "green"),
    ("classify", "bad-hallucinated-class", "edd", "green"),
    ("classify", "bad-hallucinated-class", "cdd", "green"),
    ("classify", "bad-hallucinated-class", "bdd", "green"),

    # --- classify: edge — novel failure ---
    ("classify", "edge-novel-failure", "tdd", "green"),
    ("classify", "edge-novel-failure", "edd", "green"),
    ("classify", "edge-novel-failure", "cdd", "green"),
    ("classify", "edge-novel-failure", "bdd", "green"),
]


class TestLLMQualityMatrix:
    """32-cell matrix: prompt_type x scenario x dimension -> expected outcome."""

    @pytest.mark.parametrize(
        "prompt_type,scenario,dimension,expected_outcome",
        MATRIX,
        ids=[f"{pt}-{sc}-{dim}" for pt, sc, dim, _ in MATRIX],
    )
    def test_quality_cell(self, prompt_type, scenario, dimension, expected_outcome):
        fixture = load_fixture(prompt_type, scenario)

        rubric_id = f"{prompt_type}-{dimension}"
        if rubric_id not in _rubrics:
            pytest.skip(f"No quality rubric: {rubric_id}")

        rubric = _rubrics[rubric_id]
        result = evaluate_quality(
            rubric=rubric,
            response=fixture["response"],
            evidence=fixture["evidence"],
            metadata=fixture.get("metadata"),
            scenario_expected=fixture.get("expected", {}).get(dimension),
        )

        assert result.outcome.value == expected_outcome, (
            f"\n  Prompt: {prompt_type}\n"
            f"  Scenario: {scenario}\n"
            f"  Dimension: {dimension}\n"
            f"  Expected: {expected_outcome}\n"
            f"  Got: {result.outcome.value}\n"
            f"  Criteria: {[(c.name, c.passed, c.message) for c in result.criteria_results]}"
        )


class TestLLMQualityStructural:
    """Structural checks on the quality framework itself."""

    def test_all_rubrics_load(self):
        assert len(_rubrics) >= 8, f"Expected >= 8 rubrics, got {len(_rubrics)}"

    def test_rubric_coverage(self):
        prompt_types = {r.prompt_type for r in _rubrics.values()}
        assert "remediation" in prompt_types
        assert "classify" in prompt_types

    def test_dimension_coverage(self):
        dims = {r.dimension.value for r in _rubrics.values()}
        assert dims == {"tdd", "edd", "cdd", "bdd"}

    def test_all_fixtures_loadable(self):
        from tests.llm_quality_fixtures import load_all_fixtures
        fixtures = load_all_fixtures()
        assert len(fixtures) >= 8

    def test_fixture_has_required_fields(self):
        from tests.llm_quality_fixtures import load_all_fixtures
        for fixture in load_all_fixtures():
            assert "id" in fixture, f"Missing 'id' in fixture"
            assert "prompt_type" in fixture, f"Missing 'prompt_type' in {fixture.get('id')}"
            assert "evidence" in fixture, f"Missing 'evidence' in {fixture.get('id')}"
            assert "response" in fixture, f"Missing 'response' in {fixture.get('id')}"
