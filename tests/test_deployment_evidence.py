"""deployment-ready: a scaled-to-zero Deployment is complete, and warm-up is
unobserved.

From production evidence (19 Nov): 56% of pods_not_ready was a Deployment with
desired=0 and Available=True; 41% was a showroom pod still Pending minutes
after creation.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from collectors.openshift.collect_resource_state import collect_from_data
from collectors.openshift.evidence_normalizer import normalize_evidence
from engine.models import StageOutcome
from engine.rubric_evaluator import evaluate_rubric
from engine.rubric_loader import load_rubric

RUBRIC = load_rubric(Path(__file__).parent.parent / "rubrics" / "platform" / "deployment-ready.yaml")


def _ts(minutes_ago):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")


def _deployment(desired, ready, available=True, age=60, name="showroom"):
    return {
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": "sandbox-x",
                     "creationTimestamp": _ts(age)},
        "spec": {"replicas": desired},
        "status": {
            "readyReplicas": ready,
            "availableReplicas": ready,
            "unavailableReplicas": 0,
            "conditions": [{"type": "Available", "status": "True" if available else "False"}],
        },
    }


def _pods(total, ready, age=60, waiting=""):
    items = []
    for index in range(total):
        is_ready = index < ready
        items.append({
            "metadata": {"name": f"pod-{index}", "namespace": "sandbox-x",
                         "creationTimestamp": _ts(age)},
            "status": {
                "phase": "Running" if is_ready else "Pending",
                "containerStatuses": [{
                    "ready": is_ready,
                    "restartCount": 0,
                    "state": {"waiting": {"reason": waiting}} if waiting and not is_ready else {},
                }],
            },
        })
    return {"kind": "PodList", "items": items}


def _namespace():
    return {"kind": "Namespace", "metadata": {"name": "sandbox-x"},
            "status": {"phase": "Active"}}


class TestScaledToZero:
    def test_zero_replicas_with_available_condition_is_ready(self):
        ev = collect_from_data(_deployment(desired=0, ready=0, available=True))
        assert ev.observed["desired_replicas_ready"] is True

    def test_zero_replicas_without_available_condition_is_not_ready(self):
        ev = collect_from_data(_deployment(desired=0, ready=0, available=False))
        assert ev.observed["desired_replicas_ready"] is False


class TestWarmUp:
    def test_young_unready_pods_are_unobserved_not_failed(self):
        evidence = [collect_from_data(x) for x in (
            _namespace(),
            _deployment(desired=1, ready=0, age=3),
            _pods(total=2, ready=1, age=3),
        )]
        normalized = normalize_evidence("deployment-ready", evidence)
        result = evaluate_rubric(RUBRIC, normalized)

        assert normalized["desired_replicas_ready"] is None
        assert result.outcome == StageOutcome.INDETERMINATE

    def test_old_unready_pods_still_fail(self):
        evidence = [collect_from_data(x) for x in (
            _namespace(),
            _deployment(desired=1, ready=0, age=60),
            _pods(total=2, ready=1, age=60),
        )]
        normalized = normalize_evidence("deployment-ready", evidence)
        result = evaluate_rubric(RUBRIC, normalized)

        assert normalized["desired_replicas_ready"] is False
        assert result.failure_class == "pods_not_ready"

    def test_pod_waiting_reason_is_captured(self):
        ev = collect_from_data(_pods(total=2, ready=1, age=90, waiting="ImagePullBackOff"))
        assert ev.observed["pod_details"][1]["waiting_reason"] == "ImagePullBackOff"

    def test_all_deployments_must_be_ready(self):
        evidence = [collect_from_data(x) for x in (
            _namespace(),
            _deployment(desired=1, ready=1),
            _deployment(desired=1, ready=0, age=90, name="other"),
        )]
        normalized = normalize_evidence("deployment-ready", evidence)
        assert normalized["desired_replicas_ready"] is False


class TestEntryClassification:
    def test_missing_namespace_is_not_reported_as_pods_not_ready(self):
        evidence = [collect_from_data(x) for x in (
            {"kind": "Namespace", "metadata": {"name": "sandbox-x"},
             "status": {"phase": "Terminating"}},
            _deployment(desired=1, ready=0, age=90),
        )]
        normalized = normalize_evidence("deployment-ready", evidence)
        result = evaluate_rubric(RUBRIC, normalized)

        assert result.outcome == StageOutcome.FAIL
        assert result.failure_class == "namespace_missing"
