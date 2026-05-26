from __future__ import annotations

from dataclasses import dataclass, field

from api.app.models import Rubric, StageOutcome


@dataclass
class CriterionResult:
    name: str
    required: bool
    passed: bool


@dataclass
class EvaluationResult:
    stage_id: str
    outcome: StageOutcome
    failure_class: str | None = None
    message: str | None = None
    criteria_results: list[CriterionResult] = field(default_factory=list)
    timeout_seconds: int | None = None


def evaluate_rubric(rubric: Rubric, evidence: dict[str, object]) -> EvaluationResult:
    criteria_results: list[CriterionResult] = []
    timeout = rubric.timeout_seconds

    for criterion in rubric.entry_criteria:
        value = evidence.get(criterion.name)
        passed = _is_truthy(value)
        criteria_results.append(CriterionResult(
            name=criterion.name,
            required=criterion.required,
            passed=passed,
        ))
        if criterion.required and not passed:
            return EvaluationResult(
                stage_id=rubric.stage,
                outcome=StageOutcome.FAIL,
                message=f"Entry criterion not met: {criterion.name}",
                criteria_results=criteria_results,
                timeout_seconds=timeout,
            )

    for criterion in rubric.exit_criteria:
        value = evidence.get(criterion.name)
        passed = _is_truthy(value)
        criteria_results.append(CriterionResult(
            name=criterion.name,
            required=criterion.required,
            passed=passed,
        ))

    required_failures = [c for c in criteria_results if c.required and not c.passed]
    optional_failures = [c for c in criteria_results if not c.required and not c.passed]

    if required_failures:
        failure_class = _classify_failure(rubric, evidence)
        failed_names = ", ".join(c.name for c in required_failures)
        return EvaluationResult(
            stage_id=rubric.stage,
            outcome=StageOutcome.FAIL,
            failure_class=failure_class,
            message=f"Required criteria failed: {failed_names}",
            criteria_results=criteria_results,
            timeout_seconds=timeout,
        )

    if optional_failures:
        optional_names = ", ".join(c.name for c in optional_failures)
        return EvaluationResult(
            stage_id=rubric.stage,
            outcome=StageOutcome.WARN,
            message=f"Optional criteria failed: {optional_names}",
            criteria_results=criteria_results,
            timeout_seconds=timeout,
        )

    return EvaluationResult(
        stage_id=rubric.stage,
        outcome=StageOutcome.PASS,
        message="All criteria passed",
        criteria_results=criteria_results,
        timeout_seconds=timeout,
    )


def _is_truthy(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.lower() in ("true", "yes", "1", "pass", "ok", "ready")
    return bool(value)


def _classify_failure(rubric: Rubric, evidence: dict[str, object]) -> str | None:
    for class_name, condition in rubric.failure_classes.items():
        if _matches_conditions(condition.when, evidence):
            return class_name
    return None


def _matches_conditions(conditions: list[str], evidence: dict[str, object]) -> bool:
    if not conditions:
        return False
    for condition in conditions:
        if "==" not in condition:
            return False
        parts = condition.split("==", 1)
        if len(parts) != 2:
            return False
        key = parts[0].strip()
        expected_raw = parts[1].strip()
        actual = evidence.get(key)
        if not _values_match(actual, expected_raw):
            return False
    return True


def _values_match(actual: object, expected_raw: str) -> bool:
    if expected_raw.lower() == "true":
        return _is_truthy(actual)
    if expected_raw.lower() == "false":
        return not _is_truthy(actual)
    if isinstance(actual, (int, float)):
        try:
            return actual == type(actual)(expected_raw)
        except (ValueError, TypeError):
            return False
    return str(actual) == expected_raw
