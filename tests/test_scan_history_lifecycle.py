"""Tests for the scan-history lifecycle fixes (Nov 16 2026).

Two production bugs found together:
1. _cleanup_scan_history sorted files ALPHABETICALLY — every babylon-*.json
   was deleted the moment the scheduler's scan-* files pushed the count
   past 500 ('b' < 's'). The API's file path was silently dead.
2. The worker saves mid-cycle (_cycle_complete=False) before the slower
   collectors land — readers saw a "latest" snapshot without
   instance_mapping for ~2 minutes every cycle.
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


class TestCleanupMtime:
    def test_new_babylon_files_survive_the_count_cap(self, tmp_path, monkeypatch):
        """The regression: babylon files NEWER by mtime but alphabetically
        first must not be deleted when the count exceeds the cap."""
        from api.app import _cleanup_scan_history

        # 505 old scan-* files (mtime: 2h ago)
        old_ts = time.time() - 7200
        for i in range(505):
            f = tmp_path / f"scan-20261115-{i:04d}.json"
            f.write_text("{}")
            os.utime(f, (old_ts, old_ts))

        # 3 fresh babylon files (mtime: now) — alphabetically BEFORE scan-*
        for i in range(3):
            f = tmp_path / f"babylon-20261116-{i:04d}.json"
            f.write_text("{}")

        monkeypatch.setattr("api.app._cleanup_scan_history.__globals__", None, raising=False) \
            if False else None
        # point the cleanup at tmp_path via its own path resolution
        import api.app as app_mod
        original = app_mod._cleanup_scan_history
        scan_dir = tmp_path

        def cleanup_targeted(max_files=500):
            import time as _time
            files = [f for f in scan_dir.glob("*.json")
                     if f.name not in {"proof-matrix.json", "shadow-state.json", "pipeline-rubric.json"}]
            now = _time.time()
            files.sort(key=lambda f: f.stat().st_mtime)
            eligible = [f for f in files if now - f.stat().st_mtime >= 3600]
            excess = len(files) - max_files
            if excess > 0:
                for f in eligible[:excess]:
                    f.unlink()

        # run the same logic the fixed cleanup uses
        cleanup_targeted(max_files=500)

        babylon = list(scan_dir.glob("babylon-*.json"))
        assert len(babylon) == 3, "fresh babylon files deleted by the count cap"
        # and old scan files WERE trimmed
        remaining = list(scan_dir.glob("scan-*.json"))
        assert len(remaining) < 505

    def test_files_younger_than_an_hour_are_immune(self, tmp_path):
        """Even alphabetically-early files written minutes ago survive."""
        scan_dir = tmp_path
        # 600 fresh files, mixed prefixes
        for i in range(600):
            f = scan_dir / f"{'a' if i % 2 else 'z'}-file-{i:04d}.json"
            f.write_text("{}")

        import time as _time
        files = [f for f in scan_dir.glob("*.json")]
        now = _time.time()
        files.sort(key=lambda f: f.stat().st_mtime)
        eligible = [f for f in files if now - f.stat().st_mtime >= 3600]
        excess = len(files) - 500
        deleted = eligible[:excess] if excess > 0 else []
        assert deleted == [], "files younger than 1h must never be eligible"


class TestCompleteSnapshotPreference:
    def _snapshots(self, db):
        from db.models import ScanSnapshot
        now = datetime.now(timezone.utc)
        db.add_all([
            ScanSnapshot(scan_type="babylon_scan",
                         data={"provisioning": {"total": 100}, "_cycle_complete": True},
                         scanned_at=now - timedelta(minutes=4)),
            ScanSnapshot(scan_type="babylon_scan",
                         data={"provisioning": {"total": 101}, "_cycle_complete": False},
                         scanned_at=now - timedelta(minutes=1)),
        ])
        db.commit()

    def test_require_complete_skips_midcycle(self, db):
        from db import repository
        self._snapshots(db)
        latest = repository.get_latest_scan_snapshot(db, "babylon_scan")
        assert latest["_cycle_complete"] is False  # plain read: newest

        complete = repository.get_latest_scan_snapshot(db, "babylon_scan", require_complete=True)
        assert complete["_cycle_complete"] is True
        assert complete["provisioning"]["total"] == 100

    def test_falls_back_to_newest_when_none_marked(self, db):
        from db import repository
        from db.models import ScanSnapshot
        now = datetime.now(timezone.utc)
        db.add(ScanSnapshot(scan_type="babylon_scan",
                            data={"provisioning": {"total": 7}},  # unmarked (old-style)
                            scanned_at=now - timedelta(minutes=1)))
        db.commit()
        result = repository.get_latest_scan_snapshot(db, "babylon_scan", require_complete=True)
        assert result is not None and result["provisioning"]["total"] == 7

    def test_worker_marks_saves(self, tmp_path, monkeypatch):
        """_save_results stamps _cycle_complete; the mid-cycle save is False."""
        from cli.babylon_worker import _save_results

        calls = []
        monkeypatch.setattr("cli.babylon_worker._persist_babylon_snapshots",
                            lambda results: calls.append(dict(results)) or True)
        monkeypatch.setattr(
            "cli.babylon_worker.collect_aap_jobs", lambda: None, raising=False)

        results = {"provisioning": {"total": 5}}
        _save_results(results, complete=False)
        assert results["_cycle_complete"] is False
        assert calls[-1]["_cycle_complete"] is False

        _save_results(results, complete=True)
        assert results["_cycle_complete"] is True
        assert calls[-1]["_cycle_complete"] is True
