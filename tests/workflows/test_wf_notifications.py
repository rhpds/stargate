"""Workflow tests — Notifications + Audit Ledger."""

from unittest.mock import patch


class TestAuditLedger:

    def test_chain_integrity(self):
        from engine.audit_ledger import AuditLedger
        ledger = AuditLedger()
        ledger.append({"action": "cleanup", "target": "ns-1"})
        ledger.append({"action": "rollout", "target": "ns-2"})
        ledger.append({"action": "scale", "target": "ns-3"})
        assert ledger.verify_chain() is True
        assert len(ledger.entries) == 3

    def test_chain_detects_tampering(self):
        from engine.audit_ledger import AuditLedger
        ledger = AuditLedger()
        ledger.append({"action": "a"})
        ledger.append({"action": "b"})
        ledger.entries[0]["payload"] = {"action": "tampered"}
        assert ledger.verify_chain() is False

    def test_entry_has_sequence_and_hash(self):
        from engine.audit_ledger import AuditLedger
        ledger = AuditLedger()
        ledger.append({"test": True})
        entry = ledger.entries[0]
        assert entry["sequence"] == 0
        assert entry["hash"] is not None
        assert len(entry["hash"]) > 0


class TestNotifications:

    def test_notification_module_importable(self):
        from engine import notifications
        assert hasattr(notifications, "check_and_notify")
