from __future__ import annotations

from dataclasses import dataclass, field

from engine.models import Rubric, StageOutcome
from engine.sub_classifier import sub_classify


@dataclass
class CriterionResult:
    name: str
    required: bool
    passed: bool | None


@dataclass
class EvaluationResult:
    stage_id: str
    outcome: StageOutcome
    failure_class: str | None = None
    sub_class: str | None = None
    message: str | None = None
    criteria_results: list[CriterionResult] = field(default_factory=list)
    timeout_seconds: int | None = None


def _entry_failure_context(name: str, evidence: dict[str, object]) -> str:
    """Diagnostics for the failure message.

    Found Nov 18: 'Entry criterion not met: showroom_route_reachable' with no
    URL, status or endpoint count is not reproducible — the reader cannot tell
    a 503 from a 502 from a slow page.
    """
    if name != "showroom_route_reachable":
        return ""
    parts = []
    url = evidence.get("route_url")
    if url:
        parts.append(str(url))
    status = evidence.get("http_status")
    if status:
        parts.append(f"HTTP {status}")
    ready = evidence.get("ready_endpoint_count")
    if ready is not None:
        parts.append(f"{ready} ready endpoint{'s' if ready != 1 else ''}")
    catalog = evidence.get("catalog_item")
    if catalog:
        parts.append(f"catalog {catalog}")
    return f" — {', '.join(parts)}" if parts else ""


def evaluate_rubric(rubric: Rubric, evidence: dict[str, object]) -> EvaluationResult:
    criteria_results: list[CriterionResult] = []
    timeout = rubric.timeout_seconds

    for criterion in rubric.entry_criteria:
        value = evidence.get(criterion.name)
        passed = None if criterion.name in evidence and value is None else _is_truthy(value)
        criteria_results.append(CriterionResult(
            name=criterion.name,
            required=criterion.required,
            passed=passed,
        ))
        # Unknown entries must not hide a later observed required failure.
        # Resolve unknowns only after examining the remaining criteria.
        if criterion.required and passed is False:
            # An entry gate that failed did not pass, so exit-criteria rules
            # (e.g. pods_not_ready needs deployment_exists) do not apply — they
            # were mislabelling teardown namespaces as pods_not_ready.
            failure_class = _classify_entry_failure(criterion.name)
            if failure_class not in ENTRY_FAILURE_MAP.values():
                failure_class = _classify_failure(rubric, evidence) or failure_class
            sub = sub_classify(failure_class, f"Entry criterion not met: {criterion.name}")
            return EvaluationResult(
                stage_id=rubric.stage,
                outcome=StageOutcome.FAIL,
                failure_class=failure_class,
                sub_class=sub.get("sub_class"),
                message=(
                    f"Entry criterion not met: {criterion.name}"
                    f"{_entry_failure_context(criterion.name, evidence)}"
                ),
                criteria_results=criteria_results,
                timeout_seconds=timeout,
            )

    for criterion in rubric.exit_criteria:
        value = evidence.get(criterion.name)
        passed = None if criterion.name in evidence and value is None else _is_truthy(value)
        criteria_results.append(CriterionResult(
            name=criterion.name,
            required=criterion.required,
            passed=passed,
        ))

    required_failures = [c for c in criteria_results if c.required and c.passed is False]
    optional_failures = [c for c in criteria_results if not c.required and c.passed is False]

    if required_failures:
        failure_class = _classify_failure(rubric, evidence)
        failed_names = ", ".join(c.name for c in required_failures)
        sub = sub_classify(failure_class, f"Required criteria failed: {failed_names}") if failure_class else {}
        return EvaluationResult(
            stage_id=rubric.stage,
            outcome=StageOutcome.FAIL,
            failure_class=failure_class,
            sub_class=sub.get("sub_class"),
            message=f"Required criteria failed: {failed_names}",
            criteria_results=criteria_results,
            timeout_seconds=timeout,
        )

    unobserved = [c.name for c in criteria_results if c.passed is None]
    if unobserved:
        return EvaluationResult(
            stage_id=rubric.stage,
            outcome=StageOutcome.INDETERMINATE,
            message=f"Criteria unobserved: {', '.join(unobserved)}",
            criteria_results=criteria_results,
            timeout_seconds=timeout,
        )

    if optional_failures:
        optional_names = ", ".join(c.name for c in optional_failures)
        detail = _failed_observation_context([c.name for c in optional_failures], evidence)
        # Classify warns too: an optional-criteria failure with a matching
        # class (e.g. ceph_headroom_ok == false → ceph_near_full) carries
        # the class so downstream consumers (events, dashboards, MTTR by
        # class) see WHY it warned, not just that it did.
        failure_class = _classify_failure(rubric, evidence)
        return EvaluationResult(
            stage_id=rubric.stage,
            outcome=StageOutcome.WARN,
            failure_class=failure_class,
            message=f"Optional criteria failed: {optional_names}{detail}",
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


def _failed_observation_context(failed_names: list[str], evidence: dict[str, object]) -> str:
    """Name the observation behind a failed health criterion.

    "Optional criteria failed: health_endpoint_returns_200" leaves the reader
    unable to tell a 503 from a 403 from an unprobed route. The status line is
    the finding, so it belongs in the message — same reason
    ``_entry_failure_context`` carries the URL for showroom routes.
    """
    if "health_endpoint_returns_200" not in failed_names:
        return ""
    url = evidence.get("probed_url")
    where = f" at {url}" if url else ""
    # Several routes serve one lab, so a bare status understates the finding:
    # "none of the 9 routes answered" is the actual observation.
    probed = evidence.get("routes_probed")
    scope = f"no route answered, {probed} probed: " if isinstance(probed, int) and probed > 1 else ""
    status = evidence.get("http_status")
    if status:
        return f" ({scope}HTTP {status}{where})"
    reason = evidence.get("probe_error")
    if reason:
        return f" ({scope}{reason}{where})"
    return ""


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


ENTRY_FAILURE_MAP = {
    "showroom_route_reachable": "showroom_not_reachable",
    "showroom_pod_running": "showroom_pod_down",
    "service_exists": "service_missing",
    "namespace_exists": "namespace_missing",
    "datavolume_succeeded": "datavolume_not_ready",
    "datavolume_exists": "datavolume_missing",
    "deployment_exists": "deployment_missing",
    "route_exists": "route_missing",
    "vm_exists": "vm_missing",
    "vmi_running": "vmi_not_running",
    "cluster_reachable": "cluster_unreachable",
}


def _classify_entry_failure(criterion_name: str) -> str:
    return ENTRY_FAILURE_MAP.get(criterion_name, f"{criterion_name}_failed")


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
        if key in evidence and evidence[key] is None:
            return False
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
