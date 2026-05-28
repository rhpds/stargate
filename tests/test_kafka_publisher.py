"""Kafka event publisher — TDD red/green.

Tests that StarGate evaluation events publish to Kafka topics.
"""

import pytest
from unittest.mock import patch


class TestKafkaPublisherExists:
    def test_kafka_publish_function_exists(self):
        from integrations.kafka_publisher import publish_to_kafka
        assert callable(publish_to_kafka)

    def test_topic_mapping(self):
        from integrations.kafka_publisher import get_topic_for_event
        assert get_topic_for_event("evaluation.passed") == "stargate-evaluations"
        assert get_topic_for_event("remediation.executed") == "stargate-remediations"
        assert get_topic_for_event("cluster.scanned") == "cluster-health"


class TestGracefulDegradation:
    def test_publish_succeeds_when_no_bootstrap(self):
        from integrations.kafka_publisher import publish_to_kafka
        with patch("integrations.kafka_publisher.KAFKA_BOOTSTRAP", ""):
            result = publish_to_kafka("stargate-evaluations", {"test": True})
            assert result is None or result == {}
