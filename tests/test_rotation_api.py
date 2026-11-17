"""Rotation endpoints — contract cases (TDD, RED first)."""

from datetime import date, datetime, timezone

import pytest


def _seed(db, day, provider, tickets, closed, in_progress, new, unassigned,
          verified_live=0, live_locations=0, untracked_live=0):
    from db.models import RotationSnapshot
    db.add(RotationSnapshot(
        snapshot_date=day, provider=provider, tickets=tickets, closed=closed,
        in_progress=in_progress, new=new, unassigned=unassigned,
        verified_live=verified_live, live_locations=live_locations,
        untracked_live=untracked_live, synced_at=datetime.now(timezone.utc)))
    db.commit()


class TestRotationEndpoint:
    def test_empty_state_is_explicit(self, client):
        body = client.get("/dashboard/rotation").json()
        assert body["summary"]["providers"] == 0
        assert body["providers"] == []
        assert body["trend"] == []
        assert body["source"]["verification"] == "none"

    def test_latest_day_only_and_totals(self, client, db):
        _seed(db, date(2026, 11, 16), "AWS", 10, 2, 1, 7, 4, 20, 100, 3)
        _seed(db, date(2026, 11, 17), "AWS", 12, 5, 1, 6, 3, 30, 150, 4)
        _seed(db, date(2026, 11, 17), "IBM Cloud", 3, 1, 0, 2, 1, 4, 12, 1)

        body = client.get("/dashboard/rotation").json()

        assert [p["provider"] for p in body["providers"]] == ["AWS", "IBM Cloud"]
        assert body["summary"]["tickets"] == 15
        assert body["summary"]["closed"] == 6
        assert body["summary"]["closed_pct"] == 40
        assert body["summary"]["verified_live"] == 34
        assert body["source"]["verification"] == "snapshot"

    def test_trend_is_ascending_and_per_day(self, client, db):
        _seed(db, date(2026, 11, 16), "AWS", 10, 2, 1, 7, 4)
        _seed(db, date(2026, 11, 17), "AWS", 12, 5, 1, 6, 3)

        trend = client.get("/dashboard/rotation").json()["trend"]

        assert [t["date"] for t in trend] == ["2026-11-16", "2026-11-17"]
        assert [t["closed"] for t in trend] == [2, 5]


class TestSnapshotIngest:
    def test_requires_admin_key(self, client):
        payload = {"date": "2026-11-17", "providers": [
            {"provider": "AWS", "verified_live": 1, "live_locations": 1, "untracked_live": 0}]}
        r = client.post("/integration/rotation-snapshot", json=payload,
                        headers={"X-API-Key": ""})
        assert r.status_code in (401, 403)

    def test_ingest_writes_verified_fields(self, client, db):
        payload = {"date": "2026-11-17", "providers": [
            {"provider": "AWS", "verified_live": 50, "live_locations": 300, "untracked_live": 21},
            {"provider": "NewCo", "verified_live": 2, "live_locations": 3, "untracked_live": 2}]}
        r = client.post("/integration/rotation-snapshot", json=payload)
        assert r.status_code == 201
        assert r.json()["providers"] == 2

        from db.models import RotationSnapshot
        aws = db.query(RotationSnapshot).filter_by(provider="AWS").one()
        assert (aws.verified_live, aws.live_locations, aws.untracked_live) == (50, 300, 21)
        newco = db.query(RotationSnapshot).filter_by(provider="NewCo").one()
        assert newco.tickets == 0  # created empty, filled by the next sync

    def test_ingest_is_idempotent(self, client, db):
        for live in (10, 12):
            client.post("/integration/rotation-snapshot",
                        json={"date": "2026-11-17", "providers": [
                            {"provider": "AWS", "verified_live": live,
                             "live_locations": 1, "untracked_live": 0}]})

        from db.models import RotationSnapshot
        rows = db.query(RotationSnapshot).filter_by(provider="AWS").all()
        assert len(rows) == 1
        assert rows[0].verified_live == 12


class TestSourceLinks:
    def test_links_come_from_configuration(self, client, monkeypatch):
        import json
        monkeypatch.setenv("STARGATE_ROTATION_LINKS", json.dumps([
            {"label": "Progress spreadsheet", "url": "https://docs.google.com/spreadsheets/d/x"}
        ]))
        body = client.get("/dashboard/rotation").json()
        assert body["links"] == [
            {"label": "Progress spreadsheet", "url": "https://docs.google.com/spreadsheets/d/x"}
        ]

    def test_links_default_to_empty(self, client, monkeypatch):
        monkeypatch.delenv("STARGATE_ROTATION_LINKS", raising=False)
        assert client.get("/dashboard/rotation").json()["links"] == []

    def test_malformed_links_are_ignored(self, client, monkeypatch):
        monkeypatch.setenv("STARGATE_ROTATION_LINKS", "{not json")
        assert client.get("/dashboard/rotation").json()["links"] == []
