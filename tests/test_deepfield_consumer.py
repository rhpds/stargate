"""Tests for the DeepField event consumer + auto-evaluation namespace matching."""

import pytest

from events.consumers import DeepFieldConsumer
from events.models import Event
from engine.namespace_matcher import match_namespace_to_lab


class TestDeepFieldConsumer:
    def test_filters_correct_events(self):
        consumer = DeepFieldConsumer(url="http://test:8099")
        assert consumer.should_receive(Event(event_type="evaluation.passed"))
        assert consumer.should_receive(Event(event_type="evaluation.failed"))
        assert consumer.should_receive(Event(event_type="evaluation.warned"))
        assert not consumer.should_receive(Event(event_type="remediation.proposed"))
        assert not consumer.should_receive(Event(event_type="failure.unclassified"))

    def test_filtered_events_skipped(self):
        consumer = DeepFieldConsumer(url="http://test:8099")
        assert not consumer.should_receive(Event(event_type="evaluation.failed", filtered=True))

    def test_inactive_without_url(self):
        consumer = DeepFieldConsumer(url="")
        assert not consumer.should_receive(Event(event_type="evaluation.failed"))

    def test_delivery_failure_doesnt_crash(self):
        consumer = DeepFieldConsumer(url="http://unreachable:9999")
        event = Event(
            event_type="evaluation.failed",
            run_id="run-456",
            lab_code="test",
        )
        consumer.deliver(event)


class TestNamespaceMatcher:
    def test_matches_lab(self):
        mappings = [
            {"lab_code": "rag-demo", "namespace_pattern": "sandbox-*-rag-demo"},
            {"lab_code": "cnv-lab", "namespace_pattern": "sandbox-*-openshift-cnv"},
        ]
        assert match_namespace_to_lab("sandbox-abc123-rag-demo", mappings) == "rag-demo"
        assert match_namespace_to_lab("sandbox-xyz-openshift-cnv", mappings) == "cnv-lab"

    def test_no_match_returns_none(self):
        mappings = [{"lab_code": "rag", "namespace_pattern": "sandbox-*-rag"}]
        assert match_namespace_to_lab("kube-system", mappings) is None

    def test_empty_mappings(self):
        assert match_namespace_to_lab("anything", []) is None

    def test_empty_pattern_skipped(self):
        mappings = [{"lab_code": "test", "namespace_pattern": ""}]
        assert match_namespace_to_lab("anything", mappings) is None

    def test_first_match_wins(self):
        mappings = [
            {"lab_code": "first", "namespace_pattern": "sandbox-*"},
            {"lab_code": "second", "namespace_pattern": "sandbox-abc-*"},
        ]
        assert match_namespace_to_lab("sandbox-abc-test", mappings) == "first"
