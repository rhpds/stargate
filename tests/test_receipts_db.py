"""Receipt DB persistence tests — RED/GREEN TDD."""

import pytest
from tests.conftest import client, db


class TestReceiptsDB:
    def test_save_receipt(self, db):
        """Saving a receipt persists to DB."""
        from db.repository import save_receipt
        save_receipt(db, "test-summary", None, {"total": 100, "passed": 100}, True)
        from db.models import Receipt
        count = db.query(Receipt).count()
        assert count > 0

    def test_get_receipts(self, db):
        """Query receipts by type."""
        from db.repository import save_receipt, get_receipts
        save_receipt(db, "phase-a-shadow", "A", {"passed": 43}, True)
        save_receipt(db, "phase-b-mock", "B", {"passed": 18}, True)
        results = get_receipts(db)
        assert len(results) >= 2

    def test_get_receipts_by_type(self, db):
        """Filter receipts by type."""
        from db.repository import save_receipt, get_receipts
        save_receipt(db, "phase-a-shadow", "A", {"passed": 43}, True)
        save_receipt(db, "phase-b-mock", "B", {"passed": 18}, True)
        results = get_receipts(db, receipt_type="phase-a-shadow")
        assert len(results) == 1
        assert results[0]["receipt_type"] == "phase-a-shadow"

    def test_get_latest_receipt(self, db):
        """Get most recent receipt of a type."""
        from db.repository import save_receipt, get_latest_receipt
        save_receipt(db, "test-summary", None, {"run": 1}, True)
        save_receipt(db, "test-summary", None, {"run": 2}, True)
        latest = get_latest_receipt(db, "test-summary")
        assert latest is not None
        assert latest["data"]["run"] == 2

    def test_receipts_endpoint(self, client):
        """GET /admin/receipts returns receipts."""
        resp = client.get("/admin/receipts")
        assert resp.status_code == 200
        data = resp.json()
        assert "receipts" in data

    def test_feedback_loop_writes_receipt(self, db):
        """Feedback loop run persists a receipt."""
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "stargate-synthetic-client-emulator"))
        from engine.feedback_loop import run_feedback_loop
        from db.models import Receipt

        before = db.query(Receipt).filter(Receipt.receipt_type == "feedback-loop").count()
        run_feedback_loop("healthy-baseline", db)
        after = db.query(Receipt).filter(Receipt.receipt_type == "feedback-loop").count()
        assert after > before
