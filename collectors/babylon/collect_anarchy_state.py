"""AnarchySubject state collector — parse oc get anarchysubject JSON into evidence.

Read-only. No mutation. No write verbs.
"""

from __future__ import annotations

from typing import Dict

from collectors.openshift.collect_resource_state import CollectedEvidence


def collect_anarchysubject(data: Dict) -> CollectedEvidence:
    """Parse AnarchySubject CRD JSON into normalized evidence."""
    metadata = data.get("metadata", {})
    status = data.get("status", {})
    spec = data.get("spec", {})
    spec_vars = spec.get("vars", {})

    # State lives in different places across Anarchy versions
    state = (
        status.get("state")
        or spec_vars.get("current_state")
        or "unknown"
    )

    tower_jobs = status.get("towerJobs", {})
    provision_succeeded = _check_provision_succeeded(tower_jobs)

    run_status = status.get("runStatus", "")

    has_error = any(
        c.get("status") == "True" and "error" in c.get("type", "").lower()
        for c in status.get("conditions", [])
    )
    if not status.get("conditions") and run_status == "failed":
        has_error = True

    return CollectedEvidence(
        resource_kind="AnarchySubject",
        resource_name=metadata.get("name", "unknown"),
        namespace=metadata.get("namespace", "unknown"),
        observed={
            "anarchysubject_exists": True,
            "provision_job_succeeded": provision_succeeded,
            "state_is_started": state == "started",
            "current_state": state,
            "no_error_conditions": not has_error,
        },
    )


def summarize_subjects(subjects: list) -> Dict:
    """Summarize all AnarchySubjects into aggregate provisioning data."""
    total = len(subjects)
    by_state: Dict[str, int] = {}
    failed = 0
    started = 0

    for s in subjects:
        ev = collect_anarchysubject(s)
        state = ev.observed.get("current_state", "unknown")
        by_state[state] = by_state.get(state, 0) + 1
        if "failed" in state:
            failed += 1
        if state == "started":
            started += 1

    return {
        "total_subjects": total,
        "started": started,
        "failed": failed,
        "by_state": by_state,
        "failure_rate": round(failed / max(total, 1) * 100, 1),
    }


def _check_provision_succeeded(tower_jobs: Dict) -> bool | None:
    """Respect explicit outcomes; termination alone cannot establish success.

    Mixed list histories have no guaranteed ordering, so remain unverified
    rather than picking an arbitrary successful attempt.
    """
    jobs = tower_jobs.get("provision", tower_jobs.get("start", {}))

    if not jobs:
        return False
    attempts = jobs if isinstance(jobs, list) else [jobs]
    outcomes = []
    for job in attempts:
        if not isinstance(job, dict):
            return None
        status = str(job.get("status", "")).strip().lower()
        if status == "successful":
            outcomes.append(True)
        elif status in {"failed", "error", "canceled", "cancelled"}:
            outcomes.append(False)
        else:
            return None
    if all(outcome is True for outcome in outcomes):
        return True
    if all(outcome is False for outcome in outcomes):
        return False
    return None
