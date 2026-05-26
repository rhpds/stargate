"""Provisioning event watcher nanoagent.

Watches Kubernetes events during the provisioning window and classifies
provisioning issues as they happen — rather than waiting for timeout to
discover the AnarchySubject never reached 'started'.

Two modes:
  1. Live: streams 'oc get events --watch' via subprocess (Trust Level 1+)
  2. Fixture: parses a pre-collected event list (Trust Level 0)

The watcher produces ProvisioningIssue evidence items that feed into
the provision-complete rubric evaluator. Issues are classified by
severity and type so the gate can fail fast on critical problems
instead of waiting for the full timeout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from collectors.openshift.collect_resource_state import CollectedEvidence


class IssueSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class IssueCategory(str, Enum):
    IMAGE_PULL = "image_pull"
    SCHEDULING = "scheduling"
    QUOTA = "quota"
    CRASHLOOP = "crashloop"
    PROVISION_FAILED = "provision_failed"
    ANARCHY_ERROR = "anarchy_error"
    STORAGE = "storage"
    NETWORK = "network"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


EVENT_CLASSIFIERS = [
    {
        "reasons": ["Failed", "ErrImagePull", "ImagePullBackOff", "ErrImageNeverPull"],
        "message_patterns": ["pull", "image", "ImagePullBackOff"],
        "category": IssueCategory.IMAGE_PULL,
        "severity": IssueSeverity.CRITICAL,
    },
    {
        "reasons": ["FailedScheduling"],
        "message_patterns": ["Insufficient", "node(s)", "unschedulable", "taint"],
        "category": IssueCategory.SCHEDULING,
        "severity": IssueSeverity.CRITICAL,
    },
    {
        "reasons": ["FailedCreate"],
        "message_patterns": ["quota", "exceeded", "forbidden"],
        "category": IssueCategory.QUOTA,
        "severity": IssueSeverity.CRITICAL,
    },
    {
        "reasons": ["BackOff", "CrashLoopBackOff"],
        "message_patterns": ["back-off", "CrashLoopBackOff", "restarting"],
        "category": IssueCategory.CRASHLOOP,
        "severity": IssueSeverity.CRITICAL,
    },
    {
        "reasons": ["FailedMount", "FailedAttachVolume", "ProvisioningFailed"],
        "message_patterns": ["volume", "mount", "pvc", "storageclass", "disk"],
        "category": IssueCategory.STORAGE,
        "severity": IssueSeverity.CRITICAL,
    },
    {
        "reasons": ["ProvisionFailed", "ActionFailed", "RunnerFailed"],
        "message_patterns": ["playbook", "ansible", "provision failed", "provision timed out"],
        "category": IssueCategory.PROVISION_FAILED,
        "severity": IssueSeverity.CRITICAL,
    },
    {
        "reasons": ["AnarchyError", "ActionError"],
        "message_patterns": ["anarchy", "anarchyaction", "governor"],
        "category": IssueCategory.ANARCHY_ERROR,
        "severity": IssueSeverity.WARNING,
    },
    {
        "reasons": ["NetworkNotReady"],
        "message_patterns": ["network", "cni", "multus"],
        "category": IssueCategory.NETWORK,
        "severity": IssueSeverity.WARNING,
    },
]


@dataclass
class ProvisioningIssue:
    category: IssueCategory
    severity: IssueSeverity
    reason: str
    message: str
    involved_object: str
    namespace: str
    count: int = 1
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None


@dataclass
class WatcherResult:
    namespace: str
    issues: List[ProvisioningIssue] = field(default_factory=list)
    total_events: int = 0
    warning_events: int = 0
    has_critical_issues: bool = False
    categories_seen: List[str] = field(default_factory=list)


def classify_event(event: Dict) -> Optional[ProvisioningIssue]:
    reason = event.get("reason", "")
    message = event.get("message", "")
    event_type = event.get("type", "Normal")

    if event_type != "Warning":
        return None

    message_lower = message.lower()
    reason_lower = reason.lower()

    for classifier in EVENT_CLASSIFIERS:
        reason_match = any(r.lower() == reason_lower for r in classifier["reasons"])
        message_match = any(p.lower() in message_lower for p in classifier["message_patterns"])

        if reason_match or message_match:
            involved = event.get("involvedObject", {})
            return ProvisioningIssue(
                category=classifier["category"],
                severity=classifier["severity"],
                reason=reason,
                message=message,
                involved_object=f"{involved.get('kind', 'Unknown')}/{involved.get('name', 'unknown')}",
                namespace=involved.get("namespace", event.get("metadata", {}).get("namespace", "unknown")),
                count=event.get("count", 1),
                first_seen=event.get("firstTimestamp"),
                last_seen=event.get("lastTimestamp"),
            )

    return ProvisioningIssue(
        category=IssueCategory.UNKNOWN,
        severity=IssueSeverity.WARNING,
        reason=reason,
        message=message,
        involved_object=event.get("involvedObject", {}).get("name", "unknown"),
        namespace=event.get("metadata", {}).get("namespace", "unknown"),
        count=event.get("count", 1),
        first_seen=event.get("firstTimestamp"),
        last_seen=event.get("lastTimestamp"),
    )


def watch_provision_events(event_list_data: Dict) -> WatcherResult:
    """Analyze a collected event list for provisioning issues.

    Takes the output of 'oc get events -n <namespace> -o json' and
    classifies each Warning event into a provisioning issue category.
    """
    items = event_list_data.get("items", [])
    namespace = "unknown"
    if items:
        namespace = items[0].get("metadata", {}).get("namespace", "unknown")

    issues: List[ProvisioningIssue] = []
    warning_count = 0

    for event in items:
        if event.get("type") == "Warning":
            warning_count += 1
            issue = classify_event(event)
            if issue:
                issues.append(issue)

    categories = list(set(i.category.value for i in issues))
    has_critical = any(i.severity == IssueSeverity.CRITICAL for i in issues)

    return WatcherResult(
        namespace=namespace,
        issues=issues,
        total_events=len(items),
        warning_events=warning_count,
        has_critical_issues=has_critical,
        categories_seen=sorted(categories),
    )


def watcher_result_to_evidence(result: WatcherResult) -> CollectedEvidence:
    """Convert WatcherResult into normalized evidence for the rubric evaluator."""
    issue_details = [
        {
            "category": i.category.value,
            "severity": i.severity.value,
            "reason": i.reason,
            "message": i.message,
            "involved_object": i.involved_object,
            "count": i.count,
        }
        for i in result.issues
    ]

    critical_issues = [i for i in result.issues if i.severity == IssueSeverity.CRITICAL]
    critical_categories = list(set(i.category.value for i in critical_issues))

    return CollectedEvidence(
        resource_kind="ProvisionEventWatch",
        resource_name="provision-events",
        namespace=result.namespace,
        observed={
            "total_events": result.total_events,
            "warning_events": result.warning_events,
            "provisioning_issues_found": len(result.issues),
            "has_critical_issues": result.has_critical_issues,
            "critical_issue_count": len(critical_issues),
            "categories_seen": result.categories_seen,
            "critical_categories": critical_categories,
            "no_error_conditions": not result.has_critical_issues,
            "issues": issue_details,
        },
    )
