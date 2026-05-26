"""Provisioning event watcher nanoagent tests.

Tests event classification, issue detection, and evidence generation
for provisioning failures caught from Kubernetes events.
"""

import json
from pathlib import Path

import pytest

from collectors.nanoagents.provision_watcher import (
    IssueCategory,
    IssueSeverity,
    classify_event,
    watch_provision_events,
    watcher_result_to_evidence,
)


PROVISION_HEALTHY = Path(__file__).parent.parent / "fixtures" / "oc" / "provision-healthy"
PROVISION_UNHEALTHY = Path(__file__).parent.parent / "fixtures" / "oc" / "provision-unhealthy"


def _load(path):
    return json.loads(path.read_text())


# --- Event classification ---

class TestClassifyEvent:
    def test_image_pull_failure(self):
        event = {
            "reason": "ErrImagePull",
            "message": "Failed to pull image",
            "type": "Warning",
            "involvedObject": {"kind": "Pod", "name": "demo-pod", "namespace": "ns"},
        }
        issue = classify_event(event)
        assert issue is not None
        assert issue.category == IssueCategory.IMAGE_PULL
        assert issue.severity == IssueSeverity.CRITICAL

    def test_scheduling_failure(self):
        event = {
            "reason": "FailedScheduling",
            "message": "0/6 nodes are available: Insufficient cpu",
            "type": "Warning",
            "involvedObject": {"kind": "Pod", "name": "demo-pod", "namespace": "ns"},
        }
        issue = classify_event(event)
        assert issue.category == IssueCategory.SCHEDULING
        assert issue.severity == IssueSeverity.CRITICAL

    def test_quota_exceeded(self):
        event = {
            "reason": "FailedCreate",
            "message": "exceeded quota: compute-resources",
            "type": "Warning",
            "involvedObject": {"kind": "ReplicaSet", "name": "demo-rs", "namespace": "ns"},
        }
        issue = classify_event(event)
        assert issue.category == IssueCategory.QUOTA
        assert issue.severity == IssueSeverity.CRITICAL

    def test_crashloop(self):
        event = {
            "reason": "BackOff",
            "message": "Back-off restarting failed container",
            "type": "Warning",
            "involvedObject": {"kind": "Pod", "name": "demo-pod", "namespace": "ns"},
        }
        issue = classify_event(event)
        assert issue.category == IssueCategory.CRASHLOOP
        assert issue.severity == IssueSeverity.CRITICAL

    def test_provision_failed(self):
        event = {
            "reason": "ActionFailed",
            "message": "AnarchyAction provision failed: playbook execution timed out",
            "type": "Warning",
            "involvedObject": {"kind": "AnarchySubject", "name": "demo-as", "namespace": "ns"},
        }
        issue = classify_event(event)
        assert issue.category == IssueCategory.PROVISION_FAILED
        assert issue.severity == IssueSeverity.CRITICAL

    def test_storage_failure(self):
        event = {
            "reason": "ProvisioningFailed",
            "message": "Failed to provision volume with StorageClass",
            "type": "Warning",
            "involvedObject": {"kind": "PVC", "name": "demo-pvc", "namespace": "ns"},
        }
        issue = classify_event(event)
        assert issue.category == IssueCategory.STORAGE
        assert issue.severity == IssueSeverity.CRITICAL

    def test_normal_event_returns_none(self):
        event = {
            "reason": "Scheduled",
            "message": "Successfully assigned pod",
            "type": "Normal",
            "involvedObject": {"kind": "Pod", "name": "demo-pod", "namespace": "ns"},
        }
        issue = classify_event(event)
        assert issue is None

    def test_unknown_warning_classified(self):
        event = {
            "reason": "SomethingWeird",
            "message": "An unknown problem occurred",
            "type": "Warning",
            "involvedObject": {"kind": "Pod", "name": "demo-pod", "namespace": "ns"},
        }
        issue = classify_event(event)
        assert issue is not None
        assert issue.category == IssueCategory.UNKNOWN
        assert issue.severity == IssueSeverity.WARNING

    def test_message_pattern_match(self):
        event = {
            "reason": "SomeReason",
            "message": "container is in CrashLoopBackOff state",
            "type": "Warning",
            "involvedObject": {"kind": "Pod", "name": "demo-pod", "namespace": "ns"},
        }
        issue = classify_event(event)
        assert issue.category == IssueCategory.CRASHLOOP


# --- Watcher on fixtures ---

class TestWatchProvisionEvents:
    def test_healthy_no_issues(self):
        data = _load(PROVISION_HEALTHY / "events.json")
        result = watch_provision_events(data)
        assert result.total_events == 5
        assert result.warning_events == 0
        assert len(result.issues) == 0
        assert result.has_critical_issues is False

    def test_unhealthy_detects_issues(self):
        data = _load(PROVISION_UNHEALTHY / "events.json")
        result = watch_provision_events(data)
        assert result.total_events == 7
        assert result.warning_events == 6
        assert len(result.issues) == 6
        assert result.has_critical_issues is True

    def test_unhealthy_categories(self):
        data = _load(PROVISION_UNHEALTHY / "events.json")
        result = watch_provision_events(data)
        categories = set(result.categories_seen)
        assert "image_pull" in categories
        assert "scheduling" in categories
        assert "quota" in categories
        assert "storage" in categories

    def test_unhealthy_critical_count(self):
        data = _load(PROVISION_UNHEALTHY / "events.json")
        result = watch_provision_events(data)
        critical = [i for i in result.issues if i.severity == IssueSeverity.CRITICAL]
        assert len(critical) >= 4

    def test_empty_event_list(self):
        data = {"kind": "EventList", "items": []}
        result = watch_provision_events(data)
        assert result.total_events == 0
        assert result.has_critical_issues is False


# --- Evidence generation ---

class TestWatcherEvidence:
    def test_healthy_evidence(self):
        data = _load(PROVISION_HEALTHY / "events.json")
        result = watch_provision_events(data)
        evidence = watcher_result_to_evidence(result)
        assert evidence.resource_kind == "ProvisionEventWatch"
        assert evidence.observed["provisioning_issues_found"] == 0
        assert evidence.observed["has_critical_issues"] is False
        assert evidence.observed["no_error_conditions"] is True

    def test_unhealthy_evidence(self):
        data = _load(PROVISION_UNHEALTHY / "events.json")
        result = watch_provision_events(data)
        evidence = watcher_result_to_evidence(result)
        assert evidence.observed["provisioning_issues_found"] >= 5
        assert evidence.observed["has_critical_issues"] is True
        assert evidence.observed["no_error_conditions"] is False
        assert evidence.observed["critical_issue_count"] >= 4
        assert "image_pull" in evidence.observed["critical_categories"]

    def test_evidence_issues_are_serializable(self):
        data = _load(PROVISION_UNHEALTHY / "events.json")
        result = watch_provision_events(data)
        evidence = watcher_result_to_evidence(result)
        for issue in evidence.observed["issues"]:
            assert "category" in issue
            assert "severity" in issue
            assert "reason" in issue
            assert "message" in issue

    def test_evidence_feeds_provision_rubric(self):
        """Evidence from watcher can feed into the provision-complete normalizer."""
        from api.app.rubric_evaluator import evaluate_rubric
        from api.app.rubric_loader import load_rubric
        from collectors.openshift.evidence_normalizer import normalize_evidence

        rubric_dir = Path(__file__).parent.parent / "rubrics" / "platform"
        rubric = load_rubric(rubric_dir / "provision-complete.yaml")

        data = _load(PROVISION_UNHEALTHY / "events.json")
        result = watch_provision_events(data)
        watcher_ev = watcher_result_to_evidence(result)

        normalized = normalize_evidence("provision-complete", [watcher_ev])
        assert normalized["no_error_conditions"] is False
