from datetime import datetime, timedelta, timezone

from db.models import ScanSnapshot
from db.repository import cleanup_old_scan_snapshots


def test_scan_snapshot_retention_is_bounded(db):
    now = datetime.now(timezone.utc)
    db.add_all([
        ScanSnapshot(scan_type="babylon_scan", data={"n": 1}, scanned_at=now - timedelta(days=8)),
        ScanSnapshot(scan_type="cluster_scan", data={"n": 2}, scanned_at=now - timedelta(days=9)),
        ScanSnapshot(scan_type="babylon_scan", data={"n": 3}, scanned_at=now - timedelta(days=1)),
    ])
    db.commit()

    assert cleanup_old_scan_snapshots(db, days=7, batch_size=1) == 1
    assert db.query(ScanSnapshot).count() == 2
    assert cleanup_old_scan_snapshots(db, days=7, batch_size=10) == 1
    assert db.query(ScanSnapshot).count() == 1
    assert cleanup_old_scan_snapshots(db, days=7, batch_size=10) == 0
