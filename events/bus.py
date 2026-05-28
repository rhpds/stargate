"""Event bus — emits events and routes them through the nanoagent pipeline."""

from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from events.models import Event

logger = logging.getLogger(__name__)


class EventBus:
    """Central event bus. Events flow through nanoagents then to consumers."""

    def __init__(self):
        self.nanoagents: List[Nanoagent] = []
        self.consumers: List[EventConsumer] = []
        self.history: List[Event] = []
        self.max_history: int = 1000
        self._db_persist: bool = True

    def register_nanoagent(self, agent: Nanoagent):
        self.nanoagents.append(agent)

    def register_consumer(self, consumer: EventConsumer):
        self.consumers.append(consumer)

    def emit(self, event: Event):
        """Process event through nanoagent pipeline, then deliver to consumers."""
        # Store in memory history
        self.history.append(event)
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

        # Run through nanoagent pipeline
        for agent in self.nanoagents:
            if agent.should_process(event):
                event = agent.process(event, self)
                if event.filtered:
                    self._persist_event(event)
                    return

        # Persist to DB
        self._persist_event(event)

        # Publish to Kafka
        try:
            from integrations.kafka_publisher import publish_event as kafka_publish
            kafka_publish(event.event_type, {
                "event_type": event.event_type,
                "run_id": event.run_id,
                "stage_id": event.stage_id,
                "lab_code": event.lab_code,
                "cluster_name": event.cluster_name,
                "outcome": event.outcome,
                "failure_class": event.failure_class,
                "message": event.message,
            })
        except Exception:
            pass

        # Deliver to consumers
        for consumer in self.consumers:
            if consumer.should_receive(event):
                try:
                    consumer.deliver(event)
                except Exception as e:
                    logger.error(f"Consumer {consumer.name} failed: {e}")

    def _persist_event(self, event: Event):
        """Persist event to SQLite for durability across restarts."""
        if not self._db_persist:
            return
        try:
            from db.database import get_session_factory
            from db.models import EventLog
            factory = get_session_factory()
            db = factory()
            log = EventLog(
                event_id=event.event_id,
                event_type=event.event_type,
                timestamp=datetime.fromisoformat(event.timestamp),
                run_id=event.run_id,
                stage_id=event.stage_id,
                lab_code=event.lab_code,
                cluster_name=event.cluster_name,
                outcome=event.outcome,
                failure_class=event.failure_class,
                message=event.message,
                priority=event.priority,
                systemic=event.systemic,
                filtered=event.filtered,
                blast_radius=event.blast_radius,
                metadata_json=event.metadata,
            )
            db.add(log)
            db.commit()
            db.close()
        except Exception as e:
            logger.debug(f"Event persist failed: {e}")

    def get_recent(self, event_type: Optional[str] = None, limit: int = 50) -> List[Dict]:
        events = self.history
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        return [e.to_dict() for e in events[-limit:]]

    def get_recent_for_cluster(self, cluster: str, limit: int = 20) -> List[Event]:
        return [e for e in self.history if e.cluster_name == cluster][-limit:]

    def get_recent_by_failure_class(self, failure_class: str, window_minutes: int = 15) -> List[Event]:
        cutoff = datetime.now(timezone.utc).timestamp() - (window_minutes * 60)
        return [
            e for e in self.history
            if e.failure_class == failure_class
            and datetime.fromisoformat(e.timestamp).timestamp() > cutoff
        ]


class Nanoagent:
    """Base class for nanoagents in the event processing pipeline."""
    name: str = "base"

    def should_process(self, event: Event) -> bool:
        return True

    def process(self, event: Event, bus: EventBus) -> Event:
        return event


class EventConsumer:
    """Base class for event consumers."""
    name: str = "base"

    def should_receive(self, event: Event) -> bool:
        return not event.filtered

    def deliver(self, event: Event):
        pass
