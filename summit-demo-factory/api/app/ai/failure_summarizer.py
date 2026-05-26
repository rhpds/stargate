"""Failure summary generator — produces structured analysis of failed runs.

Rule-based initially. Designed so an LLM can be swapped in later
to generate richer summaries while the safety constraints remain enforced
by the AIProposal model.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from api.app.ai.models import FailureSummary
from api.app.rubric_evaluator import EvaluationResult
from api.app.models import StageOutcome


# Maps failure classes to human-readable root cause hypotheses
FAILURE_HYPOTHESES = {
    "namespace_missing": (
        "The target namespace does not exist. It may not have been created, "
        "or it may have been deleted."
    ),
    "deployment_missing": (
        "No deployment found in the namespace. The application manifest "
        "may not have been applied."
    ),
    "pods_not_ready": (
        "The deployment exists but pods are not reaching ready state. "
        "This could be caused by image pull failures, resource limits, "
        "or failing readiness probes."
    ),
    "pods_crashlooping": (
        "Pods are in CrashLoopBackOff. The application is starting and "
        "immediately crashing. Check container logs for the root cause — "
        "common issues include missing config, bad entrypoint, or missing dependencies."
    ),
    "service_has_no_endpoints": (
        "The service exists but has no ready endpoints. This typically means "
        "the service selector does not match any pod labels, or all matching "
        "pods are not ready."
    ),
    "route_missing": (
        "No route found for the service. The route manifest may not have "
        "been applied."
    ),
    "health_check_failed": (
        "The route is reachable but the health endpoint is not returning 200. "
        "The application may be running but not fully initialized."
    ),
    "smoke_test_failed": (
        "The smoke test did not pass. The application may not be functioning "
        "as expected."
    ),
}

FAILURE_ACTIONS = {
    "namespace_missing": [
        "Verify the namespace creation step ran successfully",
        "Check for namespace quota or limit range issues",
    ],
    "deployment_missing": [
        "Verify the deployment manifest was applied (oc apply)",
        "Check GitOps sync status if using Argo CD",
    ],
    "pods_not_ready": [
        "Check pod status: oc get pods -n {namespace}",
        "Check pod events: oc describe pod -n {namespace}",
        "Check resource quotas: oc describe quota -n {namespace}",
    ],
    "pods_crashlooping": [
        "Check container logs: oc logs -n {namespace} {pod} --previous",
        "Check events: oc get events -n {namespace} --sort-by=.lastTimestamp",
        "Verify image and tag are correct",
        "Check environment variables and config maps",
    ],
    "service_has_no_endpoints": [
        "Compare service selector with pod labels",
        "Check pod readiness status",
        "Verify service port matches container port",
    ],
    "route_missing": [
        "Verify route manifest was applied",
        "Check for route admission errors",
    ],
    "health_check_failed": [
        "Check application logs for startup errors",
        "Verify health endpoint path is correct",
        "Check if dependent services are available",
    ],
    "smoke_test_failed": [
        "Review smoke test output for specific assertion failures",
        "Check application logs during the test window",
    ],
}


def summarize_failures(
    run_id: str,
    stage_results: List[EvaluationResult],
    evidence: Optional[Dict[str, Dict]] = None,
) -> FailureSummary:
    """Generate a structured failure summary from evaluation results."""

    failed = [r for r in stage_results if r.outcome == StageOutcome.FAIL]
    warned = [r for r in stage_results if r.outcome == StageOutcome.WARN]

    if not failed and not warned:
        return FailureSummary(
            proposal_id=f"summary-{uuid4().hex[:8]}",
            source_run_id=run_id,
            summary="All stages passed. No failures to summarize.",
            failed_stages=[],
            root_cause_hypothesis="None — all stages passed.",
            confidence="high",
        )

    failed_stage_ids = [r.stage_id for r in failed]
    failure_classes = [r.failure_class for r in failed if r.failure_class]

    summary_parts = []
    all_actions = []
    supporting = []

    for result in failed:
        stage_line = f"Stage '{result.stage_id}' failed"
        if result.failure_class:
            stage_line += f" with class '{result.failure_class}'"
        if result.message:
            stage_line += f": {result.message}"
        summary_parts.append(stage_line)

        if result.failure_class:
            actions = FAILURE_ACTIONS.get(result.failure_class, [])
            all_actions.extend(actions)

        supporting.append({
            "stage_id": result.stage_id,
            "outcome": result.outcome.value,
            "failure_class": result.failure_class,
            "message": result.message,
            "criteria": [
                {"name": c.name, "required": c.required, "passed": c.passed}
                for c in result.criteria_results
            ],
        })

    for result in warned:
        summary_parts.append(
            f"Stage '{result.stage_id}' warned: {result.message}"
        )

    primary_failure = failure_classes[0] if failure_classes else None
    hypothesis = FAILURE_HYPOTHESES.get(
        primary_failure or "",
        "Unable to determine root cause from available evidence.",
    )

    confidence = "medium" if primary_failure else "low"
    if len(failed) == 1 and primary_failure:
        confidence = "medium"

    return FailureSummary(
        proposal_id=f"summary-{uuid4().hex[:8]}",
        source_run_id=run_id,
        failed_stages=failed_stage_ids,
        summary="; ".join(summary_parts),
        root_cause_hypothesis=hypothesis,
        supporting_evidence=supporting,
        recommended_actions=all_actions,
        confidence=confidence,
    )
