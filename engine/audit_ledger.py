"""Tamper-proof audit ledger with hash chaining.

Each entry's SHA-256 hash includes the previous entry's hash,
creating an immutable chain. If any entry is modified after the
fact, the chain breaks and verify_chain() returns False.

Used by the audit-trail Kafka topic and the dashboard's audit
export endpoint to provide cryptographic integrity guarantees.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("stargate.audit_ledger")

GENESIS_HASH = "0" * 64
SIGNING_KEY = os.environ.get("AUDIT_SIGNING_KEY", "stargate-audit-default-key")


class AuditLedger:
    """Append-only ledger with hash-chained entries."""

    def __init__(self, source: str = "stargate"):
        self.source = source
        self.entries: List[Dict] = []
        self._last_hash = GENESIS_HASH

    def append(self, payload: dict) -> Dict:
        """Add an entry to the ledger. Returns the entry with hash metadata."""
        sequence = len(self.entries)
        timestamp = datetime.now(timezone.utc).isoformat()

        entry = {
            "sequence": sequence,
            "timestamp": timestamp,
            "source": self.source,
            "prev_hash": self._last_hash,
            "payload": dict(payload),
        }

        entry_hash = self._compute_hash(entry)
        entry["hash"] = entry_hash
        entry["signature"] = self._sign(entry_hash)

        self.entries.append(entry)
        self._last_hash = entry_hash

        return entry

    def verify_chain(self) -> bool:
        """Verify the entire chain is intact — no entries tampered."""
        if not self.entries:
            return True

        prev_hash = GENESIS_HASH
        for entry in self.entries:
            expected_hash = self._compute_hash({
                "sequence": entry["sequence"],
                "timestamp": entry["timestamp"],
                "source": entry["source"],
                "prev_hash": prev_hash,
                "payload": entry["payload"],
            })
            if entry["hash"] != expected_hash:
                logger.warning(
                    "Chain broken at sequence %d: expected %s, got %s",
                    entry["sequence"], expected_hash[:16], entry["hash"][:16],
                )
                return False
            prev_hash = entry["hash"]

        return True

    def export_chain(self) -> List[Dict]:
        """Export the full chain for external verification."""
        return [dict(e) for e in self.entries]

    @staticmethod
    def verify_exported_chain(chain: List[Dict]) -> bool:
        """Verify an exported chain without needing the ledger instance."""
        if not chain:
            return True

        prev_hash = GENESIS_HASH
        for entry in chain:
            expected = AuditLedger._compute_hash_static({
                "sequence": entry["sequence"],
                "timestamp": entry["timestamp"],
                "source": entry["source"],
                "prev_hash": prev_hash,
                "payload": entry["payload"],
            })
            if entry["hash"] != expected:
                return False
            prev_hash = entry["hash"]

        return True

    @staticmethod
    def _compute_hash(entry: Dict) -> str:
        """SHA-256 hash of the canonical entry representation."""
        canonical = json.dumps({
            "sequence": entry["sequence"],
            "timestamp": entry["timestamp"],
            "source": entry["source"],
            "prev_hash": entry["prev_hash"],
            "payload": entry["payload"],
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    _compute_hash_static = _compute_hash

    @staticmethod
    def _sign(entry_hash: str) -> str:
        """HMAC-SHA256 signature using the signing key."""
        return hmac.new(
            SIGNING_KEY.encode("utf-8"),
            entry_hash.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
