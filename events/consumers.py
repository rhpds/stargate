"""Event consumers — Slack, webhook, log, DeepField integration."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from typing import Optional

from events.bus import EventConsumer
from events.models import Event

logger = logging.getLogger(__name__)


class LogConsumer(EventConsumer):
    """Logs events to stdout. Always active."""
    name = "log"

    def should_receive(self, event: Event) -> bool:
        return not event.filtered

    def deliver(self, event: Event):
        triage = event.metadata.get("triage_level", "info")
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}.get(triage, "⚪")

        parts = [
            f"{icon} [{event.event_type}]",
            event.cluster_name or "",
            event.lab_code or "",
        ]
        if event.failure_class:
            parts.append(f"class={event.failure_class}")
        if event.systemic:
            parts.append("SYSTEMIC")
        if event.blast_radius:
            br = event.blast_radius
            parts.append(f"blast={br['failing_labs']}/{br['total_labs']} labs")
        if event.priority:
            parts.append(f"pri={event.priority}")

        logger.info(" | ".join(p for p in parts if p))


class SlackConsumer(EventConsumer):
    """Posts events to Slack via webhook. Only fires for non-filtered failures."""
    name = "slack"

    def __init__(self, webhook_url: str, min_priority: float = 4.0):
        self.webhook_url = webhook_url
        self.min_priority = min_priority

    def should_receive(self, event: Event) -> bool:
        if event.filtered:
            return False
        if event.event_type not in ("evaluation.failed", "failure.unclassified", "environment.degraded"):
            return False
        return event.priority >= self.min_priority

    def deliver(self, event: Event):
        triage = event.metadata.get("triage_level", "info")
        emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(triage, "⚪")

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{emoji} StarGate: {event.failure_class or event.event_type}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Cluster:* {event.cluster_name or '?'}"},
                    {"type": "mrkdwn", "text": f"*Lab:* {event.lab_code or '?'}"},
                    {"type": "mrkdwn", "text": f"*Priority:* {event.priority:.0f} ({triage})"},
                    {"type": "mrkdwn", "text": f"*Stage:* {event.stage_id or '?'}"},
                ],
            },
        ]

        if event.message:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Message:* {event.message}"},
            })

        if event.systemic:
            correlation = event.metadata.get("correlation", {})
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": (
                    f"⚠️ *Systemic issue detected*\n"
                    f"Pattern: {correlation.get('pattern', '?')}\n"
                    f"Clusters affected: {', '.join(correlation.get('clusters_affected', []))}"
                )},
            })

        if event.blast_radius:
            br = event.blast_radius
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": (
                    f"💥 *Blast radius:* {br['failing_labs']} of {br['total_labs']} labs "
                    f"({br['failure_rate']}%) on {br['cluster']}"
                )},
            })

        payload = {"blocks": blocks}
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.webhook_url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            urllib.request.urlopen(req, timeout=10)
            logger.info(f"Slack notification sent for {event.event_id}")
        except Exception as e:
            logger.error(f"Slack delivery failed: {e}")


class WebhookConsumer(EventConsumer):
    """POSTs events to a registered webhook URL."""
    name = "webhook"

    def __init__(self, url: str, event_types: Optional[list] = None):
        self.url = url
        self.event_types = event_types

    def should_receive(self, event: Event) -> bool:
        if event.filtered:
            return False
        if self.event_types and event.event_type not in self.event_types:
            return False
        return True

    def deliver(self, event: Event):
        data = json.dumps(event.to_dict()).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=data, headers={"Content-Type": "application/json"}
        )
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            logger.error(f"Webhook delivery to {self.url} failed: {e}")


class DeepFieldConsumer(EventConsumer):
    """Forwards evaluation events to DeepField's integration API.

    Only active when STARGATE_DEEPFIELD_URL env var is set. Never crashes
    the event bus — all exceptions are caught and logged.
    """
    name = "deepfield"

    # Event types we forward to DeepField
    _FORWARD_TYPES = {"evaluation.passed", "evaluation.failed", "evaluation.warned"}

    # Map StarGate event types to DeepField event types
    _EVENT_TYPE_MAP = {
        "evaluation.passed": "stargate_stage_passed",
        "evaluation.failed": "stargate_stage_failed",
        "evaluation.warned": "stargate_stage_failed",
    }

    def __init__(self, url: Optional[str] = None):
        self.url = url or os.environ.get("STARGATE_DEEPFIELD_URL", "")

    def should_receive(self, event: Event) -> bool:
        if not self.url:
            return False
        if event.filtered:
            return False
        return event.event_type in self._FORWARD_TYPES

    def deliver(self, event: Event):
        try:
            deepfield_event_type = self._EVENT_TYPE_MAP.get(
                event.event_type, "stargate_stage_failed"
            )

            payload = {
                "source": "stargate",
                "event_type": deepfield_event_type,
                "event_id": event.event_id,
                "timestamp": event.timestamp,
                "payload": {
                    "run_id": event.run_id,
                    "stage_id": event.stage_id,
                    "lab_code": event.lab_code,
                    "cluster": event.cluster_name,
                    "outcome": event.outcome,
                    "failure_class": event.failure_class,
                },
            }

            endpoint = f"{self.url.rstrip('/')}/integration/events"
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            for attempt in range(3):
                try:
                    urllib.request.urlopen(req, timeout=10)
                    logger.info(
                        "DeepField event delivered: %s run=%s stage=%s",
                        deepfield_event_type, event.run_id, event.stage_id,
                    )
                    break
                except Exception:
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                    else:
                        raise
        except Exception as e:
            logger.error("DeepField delivery failed after 3 attempts: %s", e)


class GeoLuxConsumer(EventConsumer):
    """Forwards evaluation events to GeoLux's integration API.

    Mirrors DeepFieldConsumer pattern. Only active when STARGATE_GEOLUX_URL
    env var is set. Triggers GeoLux classification + hypothesis pipeline.
    """
    name = "geolux"

    _FORWARD_TYPES = {"evaluation.passed", "evaluation.failed", "evaluation.warned"}

    _EVENT_TYPE_MAP = {
        "evaluation.passed": "stargate_evaluation_passed",
        "evaluation.failed": "stargate_evaluation_failed",
        "evaluation.warned": "stargate_evaluation_warned",
    }

    def __init__(self, url: Optional[str] = None):
        self.url = url or os.environ.get("STARGATE_GEOLUX_URL", "")

    def should_receive(self, event: Event) -> bool:
        if not self.url:
            return False
        if event.filtered:
            return False
        return event.event_type in self._FORWARD_TYPES

    def deliver(self, event: Event):
        try:
            geolux_event_type = self._EVENT_TYPE_MAP.get(
                event.event_type, "stargate_evaluation_failed"
            )

            payload = {
                "source": "stargate",
                "event_type": geolux_event_type,
                "event_id": event.event_id,
                "timestamp": event.timestamp,
                "payload": {
                    "run_id": event.run_id,
                    "stage_id": event.stage_id,
                    "lab_code": event.lab_code,
                    "cluster": event.cluster_name,
                    "outcome": event.outcome,
                    "failure_class": event.failure_class,
                    "message": getattr(event, 'message', ''),
                    "priority": getattr(event, 'priority', 0.0),
                    "systemic": getattr(event, 'systemic', False),
                },
            }

            endpoint = f"{self.url.rstrip('/')}/integration/events"
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=data,
                headers={"Content-Type": "application/json"},
            )
            for attempt in range(3):
                try:
                    urllib.request.urlopen(req, timeout=10)
                    logger.info(
                        "GeoLux event delivered: %s run=%s stage=%s cluster=%s",
                        geolux_event_type, event.run_id, event.stage_id, event.cluster_name,
                    )
                    break
                except Exception:
                    if attempt < 2:
                        time.sleep(2 ** attempt)
                    else:
                        raise
        except Exception as e:
            logger.warning("GeoLux delivery failed after 3 attempts: %s", e)
