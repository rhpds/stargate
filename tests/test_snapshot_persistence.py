"""Snapshot persistence — no more silent deaths.

The scan_snapshots table sat at ZERO rows in production because the
scheduler and babylon-worker persistence paths wrapped their DB writes
in `except Exception: pass` — and their deployments had no database
URL, so every write failed silently forever (found Nov 12 2026 while
building the capacity forecaster's supply join, which needed that
history). These tests pin the fix: persistence failures LOG, and the
extracted helpers never crash their calling thread.
"""

import logging

import pytest


class TestSchedulerSnapshotPersistence:
    def test_success_persists(self, monkeypatch):
        from cli import scheduler
        saved = {}
        class _FakeDB:
            def close(self):
                saved["closed"] = True
        def fake_get_db():
            yield _FakeDB()
        monkeypatch.setattr("db.database.get_db", fake_get_db)
        monkeypatch.setattr(
            "db.repository.save_scan_snapshot",
            lambda db, kind, data: saved.update(kind=kind, rows=len(data)))
        assert scheduler._persist_scan_snapshot([{"cluster": "x"}]) is True
        assert saved == {"kind": "cluster_scan", "rows": 1, "closed": True}

    def test_failure_logs_and_returns_false(self, monkeypatch, caplog):
        """A dead persistence path must be visible in the logs — the
        silent `except: pass` is what kept scan_snapshots empty for
        months without anyone knowing."""
        from cli import scheduler
        def broken_get_db():
            raise RuntimeError("no database URL configured")
            yield  # pragma: no cover
        monkeypatch.setattr("db.database.get_db", broken_get_db)
        with caplog.at_level(logging.WARNING, logger="stargate.scheduler"):
            ok = scheduler._persist_scan_snapshot([{"cluster": "x"}])
        assert ok is False
        assert any("snapshot" in r.message.lower() for r in caplog.records)

    def test_never_raises(self, monkeypatch):
        from cli import scheduler
        monkeypatch.setattr("db.database.get_db", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        assert scheduler._persist_scan_snapshot([]) is False


class TestBabylonSnapshotPersistence:
    def test_success_persists_all_three(self, monkeypatch):
        from cli import babylon_worker
        saved = []
        class _FakeDB:
            def close(self):
                pass
        def fake_get_db():
            yield _FakeDB()
        monkeypatch.setattr("db.database.get_db", fake_get_db)
        monkeypatch.setattr(
            "db.repository.save_scan_snapshot",
            lambda db, kind, data: saved.append(kind))
        monkeypatch.setattr(
            "db.repository.save_provisioning_snapshot",
            lambda db, data: saved.append("provisioning"))
        results = {"provisioning": {"pools": []}}
        assert babylon_worker._persist_babylon_snapshots(results) is True
        assert "babylon_scan" in saved
        assert "provisioning" in saved

    def test_failure_logs(self, monkeypatch, caplog):
        from cli import babylon_worker
        def broken_get_db():
            raise RuntimeError("no database URL configured")
            yield  # pragma: no cover
        monkeypatch.setattr("db.database.get_db", broken_get_db)
        with caplog.at_level(logging.WARNING, logger="stargate.babylon"):
            ok = babylon_worker._persist_babylon_snapshots({})
        assert ok is False
        assert any("persist" in r.message.lower() for r in caplog.records)
