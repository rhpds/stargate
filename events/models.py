"""Event models for the StarGate event bus."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


@dataclass
class Event:
    """A single event emitted by the evaluation pipeline."""
    event_id: str = field(default_factory=lambda: f"evt-{uuid4().hex[:12]}")
    event_type: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    run_id: str = ""
    stage_id: Optional[str] = None
    lab_code: Optional[str] = None
    cluster_name: Optional[str] = None
    outcome: Optional[str] = None
    failure_class: Optional[str] = None
    message: Optional[str] = None
    priority: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Nanoagent annotations
    filtered: bool = False
    correlated: bool = False
    systemic: bool = False
    deduplicated: bool = False
    blast_radius: Optional[Dict] = None

    def to_dict(self) -> Dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "stage_id": self.stage_id,
            "lab_code": self.lab_code,
            "cluster_name": self.cluster_name,
            "outcome": self.outcome,
            "failure_class": self.failure_class,
            "message": self.message,
            "priority": self.priority,
            "metadata": self.metadata,
            "filtered": self.filtered,
            "correlated": self.correlated,
            "systemic": self.systemic,
            "deduplicated": self.deduplicated,
            "blast_radius": self.blast_radius,
        }
