"""Ecosystem event schema — standardized Kafka message format with trace IDs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class EcosystemEvent(BaseModel):
    source: str
    event_type: str
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    trace_id: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: dict = Field(default_factory=dict)


def validate_event(data: dict) -> EcosystemEvent:
    return EcosystemEvent(**data)


def create_event(source: str, event_type: str, payload: dict = None, trace_id: str = None) -> dict:
    event = EcosystemEvent(
        source=source,
        event_type=event_type,
        payload=payload or {},
        trace_id=trace_id or str(uuid4()),
    )
    return event.model_dump()
