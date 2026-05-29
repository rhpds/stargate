"""Event schema — TDD."""
import pytest


class TestEcosystemEvent:
    def test_event_has_required_fields(self):
        from contracts.event_schema import create_event
        e = create_event("stargate", "evaluation.passed", {"run_id": "test"})
        assert "source" in e
        assert "event_type" in e
        assert "event_id" in e
        assert "timestamp" in e
        assert "trace_id" in e

    def test_event_generates_uuid(self):
        from contracts.event_schema import create_event
        e1 = create_event("stargate", "test")
        e2 = create_event("stargate", "test")
        assert e1["event_id"] != e2["event_id"]

    def test_trace_id_propagates(self):
        from contracts.event_schema import create_event
        e = create_event("stargate", "test", trace_id="my-trace-123")
        assert e["trace_id"] == "my-trace-123"

    def test_validate_rejects_missing_source(self):
        from contracts.event_schema import validate_event
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            validate_event({"event_type": "test"})

    def test_create_event_factory(self):
        from contracts.event_schema import create_event
        e = create_event("deepfield", "signal.escalated", {"signal_type": "pod_crashloop"})
        assert e["source"] == "deepfield"
        assert e["event_type"] == "signal.escalated"
        assert e["payload"]["signal_type"] == "pod_crashloop"
