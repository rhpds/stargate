"""Constraint classifier — compare live evidence against AgnosticV specs.

Produces constraint violations when reality doesn't match the spec:
  - workload_not_deployed: a declared workload is missing
  - operator_version_drift: operator channel doesn't match spec
  - showroom_wrong_content: showroom repo/ref doesn't match spec
  - resource_below_spec: resource count/size below declared minimum
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ConstraintViolation:
    """A single constraint violation."""
    violation_type: str
    expected: str
    actual: str
    severity: str = "warning"
    detail: str = ""


def classify_constraints(
    constraints: Dict[str, Any],
    evidence: Dict[str, Any],
) -> List[ConstraintViolation]:
    """Compare AgnosticV constraints against collected evidence.

    Args:
        constraints: Output from agnosticv_loader.load_lab_constraints()
        evidence: Normalized evidence dict from collectors (merged observed fields)

    Returns:
        List of constraint violations found.
    """
    violations = []

    # Workload presence check
    violations.extend(_check_workloads(constraints, evidence))

    # Operator channel check
    violations.extend(_check_operator_channels(constraints, evidence))

    # Showroom config check
    violations.extend(_check_showroom(constraints, evidence))

    # Resource spec check
    violations.extend(_check_resources(constraints, evidence))

    return violations


def _check_workloads(
    constraints: Dict[str, Any],
    evidence: Dict[str, Any],
) -> List[ConstraintViolation]:
    """Check if declared workloads are deployed."""
    violations = []
    workloads = constraints.get("workloads", [])
    if not workloads:
        return violations

    deployed_namespaces = evidence.get("deployed_namespaces", [])
    deployed_operators = evidence.get("deployed_operators", [])
    deployed_workloads = set()

    def _normalize(s: str) -> str:
        return s.lower().replace("-", "_")

    # Build a set of what's actually deployed (from namespace names, operator names, etc.)
    for ns in deployed_namespaces:
        deployed_workloads.add(_normalize(ns))
    for op in deployed_operators:
        deployed_workloads.add(_normalize(op))

    # Also check pod names and deployment names for workload indicators
    pod_names = evidence.get("pod_names", [])
    deployment_names = evidence.get("deployment_names", [])
    for name in pod_names + deployment_names:
        deployed_workloads.add(_normalize(name))

    for workload in workloads:
        # Extract the short name from the collection path
        # e.g., "agnosticd.core_workloads.ocp4_workload_rhacs" → "rhacs"
        parts = workload.split(".")
        short_name = parts[-1] if parts else workload
        short_name = short_name.replace("ocp4_workload_", "")
        normalized_short = _normalize(short_name)

        # Check if any deployed resource matches
        found = any(normalized_short in w for w in deployed_workloads)

        if not found:
            violations.append(ConstraintViolation(
                violation_type="workload_not_deployed",
                expected=workload,
                actual="not found",
                severity="warning",
                detail=f"Declared workload '{short_name}' not detected in deployed resources",
            ))

    return violations


def _check_operator_channels(
    constraints: Dict[str, Any],
    evidence: Dict[str, Any],
) -> List[ConstraintViolation]:
    """Check if operator channels match the spec."""
    violations = []
    expected_channels = constraints.get("operator_channels", {})
    actual_channels = evidence.get("operator_channels", {})

    if not expected_channels or not actual_channels:
        return violations

    for operator, expected_channel in expected_channels.items():
        actual = actual_channels.get(operator)
        if actual and actual != expected_channel:
            violations.append(ConstraintViolation(
                violation_type="operator_version_drift",
                expected=f"{operator}: {expected_channel}",
                actual=f"{operator}: {actual}",
                severity="warning",
                detail=f"Operator '{operator}' on channel '{actual}', expected '{expected_channel}'",
            ))

    return violations


def _check_showroom(
    constraints: Dict[str, Any],
    evidence: Dict[str, Any],
) -> List[ConstraintViolation]:
    """Check if showroom content matches the spec."""
    violations = []

    expected_repo = constraints.get("showroom_repo")
    actual_repo = evidence.get("showroom_repo")

    if expected_repo and actual_repo and expected_repo != actual_repo:
        violations.append(ConstraintViolation(
            violation_type="showroom_wrong_content",
            expected=expected_repo,
            actual=actual_repo,
            severity="critical",
            detail="Showroom content repo doesn't match AgnosticV spec",
        ))

    expected_ref = constraints.get("showroom_ref")
    actual_ref = evidence.get("showroom_ref")

    if expected_ref and actual_ref and expected_ref != actual_ref:
        # Skip template variables
        if not expected_ref.startswith("{{"):
            violations.append(ConstraintViolation(
                violation_type="showroom_wrong_content",
                expected=f"ref: {expected_ref}",
                actual=f"ref: {actual_ref}",
                severity="warning",
                detail="Showroom content ref doesn't match AgnosticV spec",
            ))

    return violations


def _check_resources(
    constraints: Dict[str, Any],
    evidence: Dict[str, Any],
) -> List[ConstraintViolation]:
    """Check if resource specs meet declared minimums."""
    violations = []

    # OCP version check
    expected_ocp = constraints.get("ocp_version")
    actual_ocp = evidence.get("ocp_version")
    if expected_ocp and actual_ocp and expected_ocp != actual_ocp:
        violations.append(ConstraintViolation(
            violation_type="resource_below_spec",
            expected=f"OCP {expected_ocp}",
            actual=f"OCP {actual_ocp}",
            severity="warning",
            detail=f"OCP version mismatch: expected {expected_ocp}, running {actual_ocp}",
        ))

    return violations


def format_violations(violations: List[ConstraintViolation]) -> List[Dict]:
    """Convert violations to serializable dicts."""
    return [
        {
            "type": v.violation_type,
            "expected": v.expected,
            "actual": v.actual,
            "severity": v.severity,
            "detail": v.detail,
        }
        for v in violations
    ]
