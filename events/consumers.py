"""Event consumers — Slack, webhook, log."""

from __future__ import annotations

import json
import logging
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
