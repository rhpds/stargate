"""Audit ledger with hash chaining — TDD red/green.

Tamper-proof audit trail where each entry's hash includes the
previous entry's hash, creating an immutable chain.
"""

import pytest


class TestAuditLedger:
    def test_ledger_exists(self):
        from engine.audit_ledger import AuditLedger
        assert AuditLedger is not None

    def test_append_returns_entry_with_hash(self):
        from engine.audit_ledger import AuditLedger
        ledger = AuditLedger()
        entry = ledger.append({"event": "test", "source": "stargate"})
        assert "hash" in entry
        assert "prev_hash" in entry
        assert "sequence" in entry
        assert entry["sequence"] == 0

    def test_chain_links_entries(self):
        from engine.audit_ledger import AuditLedger
        ledger = AuditLedger()
        e1 = ledger.append({"event": "first"})
        e2 = ledger.append({"event": "second"})
        assert e2["prev_hash"] == e1["hash"]
        assert e2["sequence"] == 1

    def test_verify_chain_valid(self):
        from engine.audit_ledger import AuditLedger
        ledger = AuditLedger()
        ledger.append({"event": "one"})
        ledger.append({"event": "two"})
        ledger.append({"event": "three"})
        assert ledger.verify_chain() == True

    def test_verify_chain_detects_tamper(self):
        from engine.audit_ledger import AuditLedger
        ledger = AuditLedger()
        ledger.append({"event": "one"})
        ledger.append({"event": "two"})
        ledger.append({"event": "three"})
        # Tamper with entry 1
        ledger.entries[1]["payload"]["event"] = "TAMPERED"
        assert ledger.verify_chain() == False

    def test_genesis_entry_has_zero_prev_hash(self):
        from engine.audit_ledger import AuditLedger
        ledger = AuditLedger()
        e = ledger.append({"event": "genesis"})
        assert e["prev_hash"] == "0" * 64

    def test_entry_includes_timestamp(self):
        from engine.audit_ledger import AuditLedger
        ledger = AuditLedger()
        e = ledger.append({"event": "test"})
        assert "timestamp" in e

    def test_entry_includes_source_signature(self):
        from engine.audit_ledger import AuditLedger
        ledger = AuditLedger(source="stargate")
        e = ledger.append({"event": "test"})
        assert e["source"] == "stargate"
        assert "signature" in e


class TestHashComputation:
    def test_hash_is_sha256(self):
        from engine.audit_ledger import AuditLedger
        ledger = AuditLedger()
        e = ledger.append({"event": "test"})
        assert len(e["hash"]) == 64  # SHA-256 hex

    def test_same_payload_different_hash_due_to_chain(self):
        from engine.audit_ledger import AuditLedger
        ledger = AuditLedger()
        e1 = ledger.append({"event": "same"})
        e2 = ledger.append({"event": "same"})
        assert e1["hash"] != e2["hash"]  # Different because prev_hash differs


class TestExportImport:
    def test_export_chain(self):
        from engine.audit_ledger import AuditLedger
        ledger = AuditLedger()
        ledger.append({"event": "one"})
        ledger.append({"event": "two"})
        exported = ledger.export_chain()
        assert len(exported) == 2
        assert exported[0]["sequence"] == 0

    def test_verify_exported_chain(self):
        from engine.audit_ledger import AuditLedger
        ledger = AuditLedger()
        ledger.append({"event": "one"})
        ledger.append({"event": "two"})
        exported = ledger.export_chain()
        assert AuditLedger.verify_exported_chain(exported) == True
