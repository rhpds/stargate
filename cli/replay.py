"""Event replay — read from Kafka topics and re-inject events for testing.

Usage:
  python -m cli.replay --topic stargate-evaluations --from-beginning
  python -m cli.replay --topic audit-trail --since 2026-05-28T00:00:00
  python -m cli.replay --record --topic audit-trail --output replay-2026-05-28.json
  python -m cli.replay --playback replay-2026-05-28.json --speed 2x
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger("stargate.replay")

KAFKA_BOOTSTRAP = os.environ.get(
    "KAFKA_BOOTSTRAP_SERVERS",
    "ecosystem-kafka-kafka-bootstrap.ecosystem-kafka.svc:9092",
)

TOPICS = [
    "launchpad-lifecycle",
    "launchpad-provisioning",
    "stargate-evaluations",
    "stargate-remediations",
    "deepfield-signals",
    "deepfield-inferences",
    "cluster-health",
    "audit-trail",
    "ecosystem-commands",
]


def consume_topic(topic: str, limit: int = 100, from_beginning: bool = True) -> List[dict]:
    """Read messages from a Kafka topic."""
    try:
        from kafka import KafkaConsumer
    except ImportError:
        logger.error("kafka-python-ng not installed. Run: pip install kafka-python-ng")
        return []

    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        auto_offset_reset="earliest" if from_beginning else "latest",
        consumer_timeout_ms=10000,
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        group_id=f"replay-{int(time.time())}",
    )

    messages = []
    for msg in consumer:
        messages.append({
            "topic": msg.topic,
            "partition": msg.partition,
            "offset": msg.offset,
            "timestamp": msg.timestamp,
            "key": msg.key.decode("utf-8") if msg.key else None,
            "value": msg.value,
        })
        if len(messages) >= limit:
            break

    consumer.close()
    return messages


def record_to_file(topic: str, output: str, limit: int = 1000):
    """Record messages from a topic to a JSON file for later playback."""
    messages = consume_topic(topic, limit=limit, from_beginning=True)
    with open(output, "w") as f:
        json.dump({
            "topic": topic,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "count": len(messages),
            "messages": messages,
        }, f, indent=2)
    logger.info("Recorded %d messages from %s to %s", len(messages), topic, output)
    return len(messages)


def playback_from_file(filename: str, target_topic: Optional[str] = None, speed: float = 1.0):
    """Replay recorded messages to a topic (or the original topic)."""
    try:
        from kafka import KafkaProducer
    except ImportError:
        logger.error("kafka-python-ng not installed")
        return 0

    with open(filename) as f:
        data = json.load(f)

    messages = data.get("messages", [])
    topic = target_topic or data.get("topic", "audit-trail")

    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None,
    )

    prev_ts = None
    replayed = 0
    for msg in messages:
        if speed > 0 and prev_ts and msg.get("timestamp"):
            delay = (msg["timestamp"] - prev_ts) / 1000 / speed
            if 0 < delay < 30:
                time.sleep(delay)
        prev_ts = msg.get("timestamp")

        producer.send(topic, value=msg["value"], key=msg.get("key"))
        replayed += 1

    producer.flush()
    producer.close()
    logger.info("Replayed %d messages to %s (speed: %sx)", replayed, topic, speed)
    return replayed


def list_topics():
    """List all available Kafka topics."""
    try:
        from kafka import KafkaConsumer
        consumer = KafkaConsumer(bootstrap_servers=KAFKA_BOOTSTRAP)
        topics = sorted(consumer.topics())
        consumer.close()
        return topics
    except Exception as e:
        logger.error("Failed to list topics: %s", e)
        return []


def main():
    parser = argparse.ArgumentParser(description="Kafka event replay tool")
    parser.add_argument("--topic", help="Kafka topic to consume from")
    parser.add_argument("--list-topics", action="store_true", help="List available topics")
    parser.add_argument("--record", action="store_true", help="Record messages to file")
    parser.add_argument("--output", default="replay.json", help="Output file for recording")
    parser.add_argument("--playback", help="Replay messages from file")
    parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier")
    parser.add_argument("--limit", type=int, default=100, help="Max messages to consume")
    parser.add_argument("--from-beginning", action="store_true", help="Start from earliest offset")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if args.list_topics:
        topics = list_topics()
        for t in topics:
            marker = " *" if t in TOPICS else ""
            print(f"  {t}{marker}")
        return

    if args.record:
        if not args.topic:
            parser.error("--record requires --topic")
        count = record_to_file(args.topic, args.output, limit=args.limit)
        print(f"Recorded {count} messages to {args.output}")
        return

    if args.playback:
        count = playback_from_file(args.playback, target_topic=args.topic, speed=args.speed)
        print(f"Replayed {count} messages")
        return

    if args.topic:
        messages = consume_topic(args.topic, limit=args.limit, from_beginning=args.from_beginning)
        for msg in messages:
            print(json.dumps(msg, indent=2))
        print(f"\n{len(messages)} messages consumed from {args.topic}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
