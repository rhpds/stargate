"""Nanoagent pipeline — deterministic event processing before LLM escalation.

Filter → Correlate → Triage → Impact → [LLM if needed]

Each nanoagent is a pure function. No side effects. No external calls
(except Impact which caches lookups). Cost: ~0 per event.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from events.bus import EventBus, Nanoagent
from events.models import Event


class FilterAgent(Nanoagent):
    """Drops routine passes, deduplicates within window, suppresses known-flaky."""

    name = "filter"

    def __init__(self, suppress_rules: Optional[List[Dict]] = None):
        self.suppress_rules = suppress_rules or []
        self._seen: Dict[str, float] = {}
        self.dedup_window_seconds = 900  # 15 minutes

    def should_process(self, event: Event) -> bool:
        return True

    def process(self, event: Event, bus: EventBus) -> Event:
        # Drop routine passes (no state change)
        if event.event_type == "evaluation.passed":
            prev = self._get_previous_outcome(event, bus)
            if prev == "pass":
                event.filtered = True
                return event

        # Deduplicate same failure class on same lab within window
        if event.event_type == "evaluation.failed" and event.failure_class:
            dedup_key = f"{event.lab_code}:{event.failure_class}:{event.cluster_name}"
            now = datetime.now(timezone.utc).timestamp()
            last_seen = self._seen.get(dedup_key, 0)
            if now - last_seen < self.dedup_window_seconds:
                event.filtered = True
                event.deduplicated = True
                return event
            self._seen[dedup_key] = now

        # Apply custom suppress rules
        for rule in self.suppress_rules:
            if self._matches_rule(event, rule):
                event.filtered = True
                return event

        return event

    def _get_previous_outcome(self, event: Event, bus: EventBus) -> Optional[str]:
        for prev in reversed(bus.history[:-1]):
            if prev.lab_code == event.lab_code and prev.stage_id == event.stage_id:
                return prev.outcome
        return None

    def _matches_rule(self, event: Event, rule: Dict) -> bool:
        if "event_type" in rule and event.event_type != rule["event_type"]:
            return False
        if "stage_id" in rule and event.stage_id != rule["stage_id"]:
            return False
        if "failure_class" in rule and event.failure_class != rule["failure_class"]:
            return False
        return True


class CorrelateAgent(Nanoagent):
    """Groups failures by lab+cluster and detects systemic patterns."""

    name = "correlate"
    SYSTEMIC_THRESHOLD = 0.20  # >20% same class = systemic

    def should_process(self, event: Event) -> bool:
        return event.event_type in ("evaluation.failed", "evaluation.warned")

    def process(self, event: Event, bus: EventBus) -> Event:
        if not event.cluster_name or not event.failure_class:
            return event

        # Count failures with same class on same cluster in recent history
        cluster_events = bus.get_recent_for_cluster(event.cluster_name, limit=100)
        total = len(cluster_events)
        same_class = sum(1 for e in cluster_events if e.failure_class == event.failure_class)

        if total > 5 and same_class / total > self.SYSTEMIC_THRESHOLD:
            event.systemic = True
            event.correlated = True
            event.metadata["correlation"] = {
                "same_class_count": same_class,
                "total_events": total,
                "rate": round(same_class / total, 2),
                "pattern": "systemic_cluster",
            }

        # Check if same failure class across multiple clusters
        all_with_class = bus.get_recent_by_failure_class(event.failure_class, window_minutes=60)
        clusters_affected = set(e.cluster_name for e in all_with_class if e.cluster_name)
        if len(clusters_affected) > 1:
            event.correlated = True
            event.metadata.setdefault("correlation", {})
            event.metadata["correlation"]["cross_cluster"] = True
            event.metadata["correlation"]["clusters_affected"] = list(clusters_affected)
            if len(clusters_affected) >= 3:
                event.systemic = True
                event.metadata["correlation"]["pattern"] = "platform_issue"

        return event


class TriageAgent(Nanoagent):
    """Calculates priority and routes by severity."""

    name = "triage"

    SEVERITY_SCORES = {
        "cluster_overloaded": 10,
        "cluster_unreachable": 10,
        "cluster_critical_alerts": 9,
        "pods_crashlooping": 8,
        "provision_failed": 8,
        "namespace_missing": 7,
        "deployment_missing": 6,
        "pods_not_ready": 6,
        "service_has_no_endpoints": 5,
        "route_missing": 4,
        "health_check_failed": 3,
        "showroom_not_ready": 5,
        "showroom_content_missing": 4,
        "guest_agent_not_connected": 2,
        "operator_version_drift": 3,
    }

    def should_process(self, event: Event) -> bool:
        return event.event_type in ("evaluation.failed", "failure.unclassified")

    def process(self, event: Event, bus: EventBus) -> Event:
        severity = self.SEVERITY_SCORES.get(event.failure_class or "", 5)

        # Boost priority for systemic issues
        if event.systemic:
            severity *= 1.5

        # Boost priority if lab has session starting within 60 minutes
        session_boost = self._check_session_urgency(event.lab_code)
        if session_boost > 0:
            severity *= session_boost
            event.metadata["session_urgent"] = True
            event.metadata["session_boost"] = session_boost

        event.priority = round(min(severity, 10.0), 1)
        event.metadata["severity_score"] = severity
        event.metadata["triage_level"] = (
            "critical" if severity >= 8
            else "high" if severity >= 6
            else "medium" if severity >= 4
            else "low"
        )

        return event

    @staticmethod
    def _check_session_urgency(lab_code: str | None) -> float:
        """Check if a lab has a session starting within 60 minutes. Returns boost multiplier."""
        if not lab_code:
            return 0
        try:
            from pathlib import Path
            import json as _json
            scan_dir = Path(__file__).parent.parent / "scan-history"
            babylon_files = sorted(scan_dir.glob("babylon-*.json"), reverse=True)
            if not babylon_files:
                return 0
            with open(babylon_files[0]) as f:
                data = _json.load(f)
            labs_by_code = data.get("labagator", {}).get("labs_by_code", {})
            lab = labs_by_code.get(lab_code, {})
            sessions = lab.get("sessions", [])
            if not sessions:
                return 0

            from datetime import datetime as _dt, timezone as _tz
            now = _dt.now(_tz.utc)
            for s in sessions if isinstance(sessions, list) else []:
                session_date = s.get("session_date", "")
                start_time = s.get("start_time", "")
                if session_date and start_time:
                    try:
                        session_start = _dt.fromisoformat(f"{session_date}T{start_time}").replace(tzinfo=_tz.utc)
                        minutes_until = (session_start - now).total_seconds() / 60
                        if 0 < minutes_until <= 60:
                            return 2.0
                        if 0 < minutes_until <= 120:
                            return 1.5
                    except (ValueError, TypeError):
                        continue
        except Exception:
            pass
        return 0


class ImpactAgent(Nanoagent):
    """Annotates events with blast radius estimation."""

    name = "impact"

    def should_process(self, event: Event) -> bool:
        return event.event_type in ("evaluation.failed", "failure.unclassified") and event.priority >= 5

    def process(self, event: Event, bus: EventBus) -> Event:
        if not event.cluster_name:
            return event

        # Count affected labs on same cluster
        cluster_events = bus.get_recent_for_cluster(event.cluster_name, limit=200)
        failing_labs = set(
            e.lab_code for e in cluster_events
            if e.outcome == "fail" and e.lab_code
        )
        total_labs = set(
            e.lab_code for e in cluster_events
            if e.lab_code
        )

        event.blast_radius = {
            "failing_labs": len(failing_labs),
            "total_labs": len(total_labs),
            "failure_rate": round(len(failing_labs) / max(len(total_labs), 1) * 100, 1),
            "cluster": event.cluster_name,
        }

        # Escalate if blast radius is high
        if len(failing_labs) > 10 or (total_labs and len(failing_labs) / len(total_labs) > 0.3):
            event.metadata["escalate"] = True
            event.metadata["escalation_reason"] = f"{len(failing_labs)} labs failing on {event.cluster_name}"

        return event


def create_default_pipeline() -> List[Nanoagent]:
    """Create the default nanoagent pipeline."""
    return [
        FilterAgent(),
        CorrelateAgent(),
        TriageAgent(),
        ImpactAgent(),
    ]
