"""Kafka event publisher for StarGate evaluation and remediation events."""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("stargate.kafka")

KAFKA_BOOTSTRAP = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS",
    "ecosystem-kafka-kafka-bootstrap.ecosystem-kafka.svc:9092",
)

TOPIC_MAP = {
    "evaluation.passed": "stargate-evaluations",
    "evaluation.failed": "stargate-evaluations",
    "evaluation.warned": "stargate-evaluations",
    "failure.classified": "stargate-evaluations",
    "failure.unclassified": "stargate-evaluations",
    "remediation.proposed": "stargate-remediations",
    "remediation.approved": "stargate-remediations",
    "remediation.executed": "stargate-remediations",
    "remediation.failed": "stargate-remediations",
    "cluster.scanned": "cluster-health",
    "cluster.healthy": "cluster-health",
    "cluster.degraded": "cluster-health",
}

AUDIT_TOPIC = "audit-trail"

_producer = None


def _get_producer():
    global _producer
    if _producer is not None:
        return _producer
    if not KAFKA_BOOTSTRAP:
        return None
    try:
        from kafka import KafkaProducer
        _producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            acks=1, retries=2, request_timeout_ms=5000, max_block_ms=3000,
        )
        logger.info("Kafka producer connected to %s", KAFKA_BOOTSTRAP)
        return _producer
    except ImportError:
        logger.debug("kafka-python not installed — Kafka publishing disabled")
        return None
    except Exception as e:
        logger.debug("Kafka producer init failed: %s", e)
        return None


def get_topic_for_event(event_type: str) -> str:
    return TOPIC_MAP.get(event_type, "stargate-evaluations")


def get_audit_topic() -> str:
    return AUDIT_TOPIC


def publish_to_kafka(topic: str, payload: dict, key: str = None) -> Optional[dict]:
    if not KAFKA_BOOTSTRAP:
        return {}
    producer = _get_producer()
    if not producer:
        return {}
    try:
        producer.send(topic, value=payload, key=key)
        producer.flush(timeout=3)
        return {"published": True, "topic": topic}
    except Exception as e:
        logger.debug("Kafka publish to %s failed: %s", topic, e)
        return {}


_audit_ledger = None


def _get_ledger():
    global _audit_ledger
    if _audit_ledger is None:
        from engine.audit_ledger import AuditLedger
        _audit_ledger = AuditLedger(source="stargate")
    return _audit_ledger


def publish_event(event_type: str, payload: dict) -> None:
    payload["_kafka_topic"] = get_topic_for_event(event_type)
    payload["_published_at"] = datetime.now(timezone.utc).isoformat()
    publish_to_kafka(payload["_kafka_topic"], payload, key=payload.get("run_id"))
    # Hash-chain the audit entry for tamper detection
    ledger = _get_ledger()
    audit_entry = ledger.append({"event_type": event_type, **payload})
    publish_to_kafka(AUDIT_TOPIC, audit_entry, key=payload.get("run_id"))
