"""LLM quality evaluator — assesses prompt response quality across dimensions.

Mirrors engine/rubric_evaluator.py in architecture but handles richer check
types for LLM response quality.  Each check_type is dispatched to a simple
handler function via a lookup dict.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from engine.models import (
    LLMQualityResult,
    QualityCriterion,
    QualityCriterionResult,
    QualityDimension,
    QualityDimensionResult,
    QualityOutcome,
    QualityRubric,
)

logger = logging.getLogger("stargate.llm_quality")

DEFAULT_RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "llm-quality"
SCHEMA_DIR = Path(__file__).parent.parent / "evidence-schemas"


# ---------------------------------------------------------------------------
# Rubric loading
# ---------------------------------------------------------------------------

def load_quality_rubrics(rubric_dir: Path) -> dict[str, QualityRubric]:
    """Load all YAML files from *rubric_dir*, parse as QualityRubric, return keyed by id."""
    rubrics: dict[str, QualityRubric] = {}
    if not rubric_dir.is_dir():
        logger.warning("Rubric directory does not exist: %s", rubric_dir)
        return rubrics

    for yaml_file in sorted(rubric_dir.glob("*.yaml")):
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
            if data is None or not isinstance(data, dict):
                logger.warning("Skipping empty or non-dict YAML: %s", yaml_file)
                continue
            rubric = QualityRubric(**data)
            rubrics[rubric.id] = rubric
        except Exception as e:
            logger.warning("Failed to load quality rubric %s: %s", yaml_file, e)

    for yaml_file in sorted(rubric_dir.glob("*.yml")):
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
            if data is None or not isinstance(data, dict):
                continue
            rubric = QualityRubric(**data)
            if rubric.id not in rubrics:
                rubrics[rubric.id] = rubric
        except Exception as e:
            logger.warning("Failed to load quality rubric %s: %s", yaml_file, e)

    return rubrics


# ---------------------------------------------------------------------------
# JSON parse cache helper
# ---------------------------------------------------------------------------

def _parse_json_cached(response: str, cache: dict) -> Optional[Any]:
    """Parse *response* as JSON, caching the result in *cache*."""
    _sentinel = object()
    cached = cache.get("_parsed_json", _sentinel)
    if cached is not _sentinel:
        return cached
    try:
        parsed = json.loads(response)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    cache["_parsed_json"] = parsed
    return parsed


# ---------------------------------------------------------------------------
# Check-type handlers
#
# Each handler receives (criterion, response, evidence, metadata,
# scenario_expected, json_cache) and returns (passed, message).
# ---------------------------------------------------------------------------

HandlerResult = Tuple[bool, str]


def _check_section_present(
    criterion: QualityCriterion,
    response: str,
    evidence: dict,
    metadata: Optional[dict],
    scenario_expected: Optional[dict],
    json_cache: dict,
) -> HandlerResult:
    pattern = criterion.target
    if re.search(pattern, response, re.IGNORECASE):
        return True, f"Section matched: {pattern}"
    return False, f"Section not found: {pattern}"


def _check_is_json(
    criterion: QualityCriterion,
    response: str,
    evidence: dict,
    metadata: Optional[dict],
    scenario_expected: Optional[dict],
    json_cache: dict,
) -> HandlerResult:
    parsed = _parse_json_cached(response, json_cache)
    if parsed is not None:
        return True, "Response is valid JSON"
    return False, "Response is not valid JSON"


def _check_not_json(
    criterion: QualityCriterion,
    response: str,
    evidence: dict,
    metadata: Optional[dict],
    scenario_expected: Optional[dict],
    json_cache: dict,
) -> HandlerResult:
    parsed = _parse_json_cached(response, json_cache)
    if parsed is None:
        return True, "Response is free text (not JSON)"
    return False, "Response is JSON but free text was expected"


def _check_json_field(
    criterion: QualityCriterion,
    response: str,
    evidence: dict,
    metadata: Optional[dict],
    scenario_expected: Optional[dict],
    json_cache: dict,
) -> HandlerResult:
    parsed = _parse_json_cached(response, json_cache)
    if parsed is None:
        return False, "Cannot check field — response is not valid JSON"
    if not isinstance(parsed, dict):
        return False, "JSON is not an object"
    field = criterion.target
    if field in parsed:
        return True, f"Field '{field}' present"
    return False, f"Field '{field}' missing from JSON response"


def _check_field_type(
    criterion: QualityCriterion,
    response: str,
    evidence: dict,
    metadata: Optional[dict],
    scenario_expected: Optional[dict],
    json_cache: dict,
) -> HandlerResult:
    parsed = _parse_json_cached(response, json_cache)
    if parsed is None:
        return False, "Cannot check field type — response is not valid JSON"
    if not isinstance(parsed, dict):
        return False, "JSON is not an object"

    field = criterion.target
    if field not in parsed:
        return False, f"Field '{field}' missing"

    value = parsed[field]
    expected_type = criterion.params.get("expected_type", "str")

    type_map = {
        "float": (int, float),
        "int": (int,),
        "list": (list,),
        "str": (str,),
        "bool": (bool,),
        "dict": (dict,),
    }
    allowed = type_map.get(expected_type)
    if allowed is None:
        return False, f"Unknown expected_type: {expected_type}"

    if not isinstance(value, allowed):
        return False, f"Field '{field}' is {type(value).__name__}, expected {expected_type}"

    # Range checks for numeric types
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        min_val = criterion.params.get("min_value")
        max_val = criterion.params.get("max_value")
        if min_val is not None and value < min_val:
            return False, f"Field '{field}' value {value} < min {min_val}"
        if max_val is not None and value > max_val:
            return False, f"Field '{field}' value {value} > max {max_val}"

    return True, f"Field '{field}' is {expected_type}"


def _check_regex_match(
    criterion: QualityCriterion,
    response: str,
    evidence: dict,
    metadata: Optional[dict],
    scenario_expected: Optional[dict],
    json_cache: dict,
) -> HandlerResult:
    parsed = _parse_json_cached(response, json_cache)
    if parsed is None:
        return False, "Cannot check regex — response is not valid JSON"
    if not isinstance(parsed, dict):
        return False, "JSON is not an object"

    field = criterion.target
    if field not in parsed:
        return False, f"Field '{field}' missing for regex check"

    value = str(parsed[field])
    pattern = criterion.params.get("pattern", "")
    if re.search(pattern, value):
        return True, f"Field '{field}' matches pattern"
    return False, f"Field '{field}' does not match pattern: {pattern}"


def _check_json_schema(
    criterion: QualityCriterion,
    response: str,
    evidence: dict,
    metadata: Optional[dict],
    scenario_expected: Optional[dict],
    json_cache: dict,
) -> HandlerResult:
    parsed = _parse_json_cached(response, json_cache)
    if parsed is None:
        return False, "Cannot validate schema — response is not valid JSON"

    schema_name = criterion.target.replace("_", "-")
    schema_file = SCHEMA_DIR / f"{schema_name}.schema.json"
    if not schema_file.exists():
        return False, f"Schema file not found: {schema_file.name}"

    try:
        import jsonschema

        schema = json.loads(schema_file.read_text())
        jsonschema.validate(instance=parsed, schema=schema)
        return True, f"Response validates against {schema_file.name}"
    except ImportError:
        return False, "jsonschema package not available"
    except json.JSONDecodeError as e:
        return False, f"Invalid schema JSON: {e}"
    except jsonschema.ValidationError as e:
        return False, f"Schema validation failed: {e.message}"


def _check_evidence_cited(
    criterion: QualityCriterion,
    response: str,
    evidence: dict,
    metadata: Optional[dict],
    scenario_expected: Optional[dict],
    json_cache: dict,
) -> HandlerResult:
    target = criterion.target

    if target in ("lab_code", "failure_class", "cluster_name"):
        expected_value = evidence.get(target, "")
        if expected_value and str(expected_value) in response:
            return True, f"Evidence '{target}' cited in response"
        if not expected_value:
            return True, f"No '{target}' in evidence to check"
        return False, f"Evidence '{target}' ({expected_value}) not found in response"

    if target == "any_numeric":
        for key, val in evidence.items():
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                if str(val) in response:
                    return True, f"Numeric evidence '{key}={val}' cited"
            elif isinstance(val, str):
                nums = re.findall(r"\b\d+\b", val)
                for n in nums:
                    if int(n) > 0 and n in response:
                        return True, f"Numeric value '{n}' from evidence '{key}' cited"
        return False, "No numeric evidence values found in response"

    if target == "conditions_match_evidence":
        parsed = _parse_json_cached(response, json_cache)
        if parsed is None or not isinstance(parsed, dict):
            return False, "Cannot check conditions — response is not valid JSON"
        conditions = parsed.get("conditions", parsed.get("criteria", []))
        if not conditions:
            return False, "No conditions/criteria found in response"
        # Check that at least one condition references evidence content
        conditions_text = json.dumps(conditions) if not isinstance(conditions, str) else conditions
        for key, val in evidence.items():
            if str(val) in conditions_text:
                return True, "Conditions reference evidence content"
        return False, "Conditions do not reference any evidence values"

    if target == "reasoning":
        parsed = _parse_json_cached(response, json_cache)
        if parsed is not None and isinstance(parsed, dict):
            reasoning = str(parsed.get("reasoning", parsed.get("explanation", "")))
        else:
            reasoning = response
        for key, val in evidence.items():
            if str(val) in reasoning:
                return True, f"Reasoning references evidence ({key})"
        return False, "Reasoning does not reference any evidence content"

    return False, f"Unknown evidence_cited target: {target}"


def _check_no_hallucination(
    criterion: QualityCriterion,
    response: str,
    evidence: dict,
    metadata: Optional[dict],
    scenario_expected: Optional[dict],
    json_cache: dict,
) -> HandlerResult:
    pattern = criterion.params.get("pattern", "")
    if not pattern:
        return True, "No pattern specified for hallucination check"

    entity_type = criterion.target
    evidence_text = json.dumps(evidence)
    found = re.findall(pattern, response)

    hallucinated = []
    for entity in found:
        if entity not in evidence_text:
            hallucinated.append(entity)

    if hallucinated:
        return False, (
            f"Hallucinated {entity_type}(s) not in evidence: "
            f"{', '.join(hallucinated[:5])}"
        )
    return True, f"All {entity_type} entities found in evidence"


def _check_negative_match(
    criterion: QualityCriterion,
    response: str,
    evidence: dict,
    metadata: Optional[dict],
    scenario_expected: Optional[dict],
    json_cache: dict,
) -> HandlerResult:
    pattern = criterion.target
    if re.search(pattern, response, re.IGNORECASE):
        return False, f"Negative match found: {pattern}"
    return True, f"No forbidden pattern found: {pattern}"


def _check_value_in_set(
    criterion: QualityCriterion,
    response: str,
    evidence: dict,
    metadata: Optional[dict],
    scenario_expected: Optional[dict],
    json_cache: dict,
) -> HandlerResult:
    parsed = _parse_json_cached(response, json_cache)
    if parsed is None:
        return False, "Cannot check value — response is not valid JSON"
    if not isinstance(parsed, dict):
        return False, "JSON is not an object"

    field = criterion.target
    if field not in parsed:
        return False, f"Field '{field}' missing"

    value = parsed[field]
    known_set_source = criterion.params.get("known_set_source", "")
    allow_novel = criterion.params.get("allow_novel", False)

    known_values: set = set()
    if known_set_source == "failure-classes":
        known_values = _load_failure_class_names()

    if value in known_values:
        return True, f"Value '{value}' is in known set"

    if allow_novel:
        # Novel value — not a hard failure but worth flagging
        return True, f"Value '{value}' is novel (not in known set, allow_novel=true)"

    return False, f"Value '{value}' not in known set ({known_set_source})"


def _load_failure_class_names() -> set:
    """Load known failure class names, preferring the engine loader if available."""
    try:
        from engine.failure_class_loader import get_all_classes

        return {cls["name"] for cls in get_all_classes()}
    except Exception:
        pass

    # Fallback: load directly from YAML files
    fc_dir = Path(__file__).parent.parent / "failure-classes"
    names: set = set()
    if not fc_dir.is_dir():
        return names
    for yaml_file in fc_dir.glob("*.yaml"):
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
            for cls_name in data.get("classes", {}):
                names.add(cls_name)
        except Exception:
            pass
    return names


def _check_scenario_assertion(
    criterion: QualityCriterion,
    response: str,
    evidence: dict,
    metadata: Optional[dict],
    scenario_expected: Optional[dict],
    json_cache: dict,
) -> HandlerResult:
    if scenario_expected is None:
        return True, "No scenario expectations provided — skipped"

    key = criterion.target
    if key not in scenario_expected:
        return True, f"Scenario key '{key}' not in expectations — skipped"

    expected = scenario_expected[key]
    if isinstance(expected, bool):
        if expected:
            return True, f"Scenario assertion '{key}' passed"
        return False, f"Scenario assertion '{key}' failed"

    return True, f"Scenario key '{key}' has non-boolean value — skipped"


def _check_min_length(
    criterion: QualityCriterion,
    response: str,
    evidence: dict,
    metadata: Optional[dict],
    scenario_expected: Optional[dict],
    json_cache: dict,
) -> HandlerResult:
    try:
        min_len = int(criterion.target)
    except (ValueError, TypeError):
        return False, f"Invalid min_length target: {criterion.target}"

    if len(response) >= min_len:
        return True, f"Response length {len(response)} >= {min_len}"
    return False, f"Response length {len(response)} < {min_len}"


def _check_metadata_check(
    criterion: QualityCriterion,
    response: str,
    evidence: dict,
    metadata: Optional[dict],
    scenario_expected: Optional[dict],
    json_cache: dict,
) -> HandlerResult:
    if metadata is None:
        return False, "No metadata provided"

    key = criterion.target
    if key not in metadata:
        return False, f"Metadata key '{key}' not found"

    expected = criterion.params.get("expected")
    actual = metadata[key]

    if str(actual) == str(expected):
        return True, f"Metadata '{key}' = '{actual}'"
    return False, f"Metadata '{key}' = '{actual}', expected '{expected}'"


def _check_format_check(
    criterion: QualityCriterion,
    response: str,
    evidence: dict,
    metadata: Optional[dict],
    scenario_expected: Optional[dict],
    json_cache: dict,
) -> HandlerResult:
    target = criterion.target

    if target == "prose_with_optional_markdown":
        stripped = response.strip()
        # Reject pure JSON
        parsed = _parse_json_cached(response, json_cache)
        if parsed is not None and (isinstance(parsed, (dict, list))):
            return False, "Response is pure JSON, expected prose"
        # Reject pure code blocks (entire response is a fenced code block)
        if re.fullmatch(r"```[\s\S]*```", stripped):
            return False, "Response is a pure code block, expected prose"
        return True, "Response is prose (with optional markdown)"

    return False, f"Unknown format_check target: {target}"


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

CHECK_HANDLERS = {
    "section_present": _check_section_present,
    "is_json": _check_is_json,
    "not_json": _check_not_json,
    "json_field": _check_json_field,
    "field_type": _check_field_type,
    "regex_match": _check_regex_match,
    "json_schema": _check_json_schema,
    "evidence_cited": _check_evidence_cited,
    "no_hallucination": _check_no_hallucination,
    "negative_match": _check_negative_match,
    "value_in_set": _check_value_in_set,
    "scenario_assertion": _check_scenario_assertion,
    "min_length": _check_min_length,
    "metadata_check": _check_metadata_check,
    "format_check": _check_format_check,
}


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def evaluate_quality(
    rubric: QualityRubric,
    response: str,
    evidence: dict,
    metadata: Optional[dict] = None,
    scenario_expected: Optional[dict] = None,
) -> QualityDimensionResult:
    """Evaluate a single dimension rubric against a response.

    Outcome logic:
    - All required pass -> GREEN
    - All required pass, some optional fail -> YELLOW
    - Any required fail -> RED
    """
    criteria_results: List[QualityCriterionResult] = []
    json_cache: dict = {}

    for criterion in rubric.criteria:
        handler = CHECK_HANDLERS.get(criterion.check_type)
        if handler is None:
            logger.warning(
                "Unknown check_type '%s' in rubric '%s' — skipping",
                criterion.check_type,
                rubric.id,
            )
            criteria_results.append(
                QualityCriterionResult(
                    name=criterion.name,
                    dimension=rubric.dimension,
                    required=criterion.required,
                    passed=True,
                    message=f"Unknown check_type '{criterion.check_type}' — skipped",
                )
            )
            continue

        passed, message = handler(
            criterion, response, evidence, metadata, scenario_expected, json_cache
        )
        criteria_results.append(
            QualityCriterionResult(
                name=criterion.name,
                dimension=rubric.dimension,
                required=criterion.required,
                passed=passed,
                message=message,
            )
        )

    required_failures = [c for c in criteria_results if c.required and not c.passed]
    optional_failures = [c for c in criteria_results if not c.required and not c.passed]

    if required_failures:
        failed_names = ", ".join(c.name for c in required_failures)
        return QualityDimensionResult(
            dimension=rubric.dimension,
            outcome=QualityOutcome.RED,
            criteria_results=criteria_results,
            message=f"Required criteria failed: {failed_names}",
        )

    if optional_failures:
        optional_names = ", ".join(c.name for c in optional_failures)
        return QualityDimensionResult(
            dimension=rubric.dimension,
            outcome=QualityOutcome.YELLOW,
            criteria_results=criteria_results,
            message=f"Optional criteria failed: {optional_names}",
        )

    return QualityDimensionResult(
        dimension=rubric.dimension,
        outcome=QualityOutcome.GREEN,
        criteria_results=criteria_results,
        message="All criteria passed",
    )


# ---------------------------------------------------------------------------
# Multi-dimension evaluation
# ---------------------------------------------------------------------------

def evaluate_all_dimensions(
    prompt_type: str,
    response: str,
    evidence: dict,
    metadata: Optional[dict] = None,
    scenario_expected: Optional[dict] = None,
    rubric_dir: Optional[Path] = None,
) -> LLMQualityResult:
    """Load rubrics for *prompt_type*, evaluate each dimension, compute overall outcome."""
    if rubric_dir is None:
        rubric_dir = DEFAULT_RUBRIC_DIR

    all_rubrics = load_quality_rubrics(rubric_dir)

    # Filter rubrics that match the requested prompt_type
    matching = {
        rid: rubric
        for rid, rubric in all_rubrics.items()
        if rubric.prompt_type == prompt_type
    }

    dimensions: Dict[str, QualityDimensionResult] = {}
    for rubric_id, rubric in matching.items():
        dim_result = evaluate_quality(
            rubric, response, evidence, metadata, scenario_expected
        )
        dimensions[rubric.dimension.value] = dim_result

    # Overall outcome: worst across all dimensions
    outcomes = [d.outcome for d in dimensions.values()]
    if QualityOutcome.RED in outcomes:
        overall = QualityOutcome.RED
    elif QualityOutcome.YELLOW in outcomes:
        overall = QualityOutcome.YELLOW
    elif outcomes:
        overall = QualityOutcome.GREEN
    else:
        overall = QualityOutcome.GREEN

    preview = response[:200] if response else ""

    return LLMQualityResult(
        prompt_type=prompt_type,
        scenario=scenario_expected.get("scenario", "") if scenario_expected else "",
        overall_outcome=overall,
        dimensions=dimensions,
        response_preview=preview,
        timestamp=datetime.now(timezone.utc),
    )
