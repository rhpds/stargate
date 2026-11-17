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
        untracked_live=untracked_live, verified_at=datetime.now(timezone.utc),
        synced_at=datetime.now(timezone.utc)))
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
        assert body["source"]["verification_at"] is not None

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
        assert aws.verified_at is not None
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


class TestProviderDetail:
    def _seed_ticket(self, db, key, provider, status, assignee):
        from db.models import RotationTicket
        db.add(RotationTicket(issue_key=key, provider=provider,
                              summary=f"[turkeyvulture] Rotate {key} ({provider})",
                              status=status, assignee=assignee))
        db.commit()

    def test_lists_actionable_tickets_first(self, client, db):
        _seed(db, date(2026, 11, 18), "AWS", 3, 1, 0, 2, 1, 50, 300, 0)
        self._seed_ticket(db, "GPTEINFRA-2", "AWS", "Closed", "Ashok")
        self._seed_ticket(db, "GPTEINFRA-1", "AWS", "New", None)
        self._seed_ticket(db, "GPTEINFRA-3", "AWS", "In Progress", "Guillaume")

        body = client.get("/dashboard/rotation/provider", params={"name": "AWS"}).json()

        assert body["provider"] == "AWS"
        assert body["counts"] == {
            "tickets": 3, "closed": 1, "in_progress": 1, "new": 1, "unassigned": 1,
        }
        assert [t["key"] for t in body["tickets"]] == [
            "GPTEINFRA-3", "GPTEINFRA-1", "GPTEINFRA-2",
        ]
        assert body["tickets"][0]["url"].endswith("/browse/GPTEINFRA-3")
        assert "key%20in%20%28GPTEINFRA-3" in body["jira_url"]
        assert body["audit"] == {"verified_live": 50, "live_locations": 300, "untracked_live": 0}

    def test_unknown_provider_is_404(self, client, db):
        assert client.get("/dashboard/rotation/provider", params={"name": "NewCo"}).status_code == 404

    def test_provider_names_with_a_slash_are_addressable(self, client, db):
        _seed(db, date(2026, 11, 18), "OpenShift / SA tokens", 1, 0, 0, 1, 1, 4, 8, 4)
        body = client.get(
            "/dashboard/rotation/provider", params={"name": "OpenShift / SA tokens"}
        ).json()
        assert body["provider"] == "OpenShift / SA tokens"
        assert body["audit"]["verified_live"] == 4

    def test_audit_only_provider_still_opens(self, client, db):
        _seed(db, date(2026, 11, 18), "NewCo", 0, 0, 0, 0, 0, 2, 3, 2)

        body = client.get("/dashboard/rotation/provider", params={"name": "NewCo"}).json()

        assert body["tickets"] == []
        assert body["audit"]["verified_live"] == 2


class TestCredentialIngest:
    def test_requires_admin_key(self, client):
        r = client.post("/integration/rotation-credentials",
                        json={"date": "2026-11-18", "credentials": []},
                        headers={"X-API-Key": ""})
        assert r.status_code in (401, 403)

    def test_stores_rows_and_canonicalises_provider(self, client, db):
        payload = {"date": "2026-11-18", "credentials": [
            {"id": "abc123", "credential": "storage_thing", "provider": "S3 bucket",
             "live_copies": 12, "coverage": "not-in-tracker"},
            {"id": "def456", "credential": "cluster_scheduler_token",
             "provider": "", "live_copies": 3, "coverage": "in-jira",
             "jira_keys": "GPTEINFRA-1"},
        ]}
        r = client.post("/integration/rotation-credentials", json=payload)
        assert r.status_code == 201
        assert r.json()["credentials"] == 2

        from db.models import RotationCredential
        s3 = db.query(RotationCredential).filter_by(credential_id="abc123").one()
        assert s3.provider == "Datastores / storage"
        token = db.query(RotationCredential).filter_by(credential_id="def456").one()
        assert token.provider == "OpenShift / SA tokens"
        assert token.verified_at is not None

    def test_provider_detail_lists_credentials(self, client, db):
        _seed(db, date(2026, 11, 18), "AWS", 1, 0, 0, 1, 1, 50, 300, 0)
        client.post("/integration/rotation-credentials", json={
            "date": "2026-11-18",
            "credentials": [
                {"id": "aaa", "credential": "aws_one", "provider": "AWS",
                 "live_copies": 9, "coverage": "in-jira", "jira_keys": "GPTEINFRA-9"},
                {"id": "bbb", "credential": "aws_two", "provider": "AWS",
                 "live_copies": 2, "coverage": "not-in-tracker"},
            ],
        })

        body = client.get("/dashboard/rotation/provider", params={"name": "AWS"}).json()

        assert [c["id"] for c in body["credentials"]] == ["aaa", "bbb"]
        assert body["credentials"][0]["jira_keys"] == "GPTEINFRA-9"
        assert body["credential_counts"] == {"total": 2, "ticketed": 1, "untracked": 1}


class TestCredentialProviderJoin:
    def test_ticketed_credential_inherits_the_ticket_provider(self, client, db):
        from db.models import RotationTicket
        db.add(RotationTicket(issue_key="GPTEINFRA-9", provider="AWS",
                              summary="[turkeyvulture] x (AWS)", status="New"))
        db.commit()

        client.post("/integration/rotation-credentials", json={
            "date": "2026-11-18",
            "credentials": [{"id": "zzz", "credential": "opaque_name",
                             "jira_keys": "GPTEINFRA-9", "live_copies": 1}],
        })

        from db.models import RotationCredential
        row = db.query(RotationCredential).filter_by(credential_id="zzz").one()
        assert row.provider == "AWS"


class TestCredentialAggregates:
    def test_provider_totals_are_derived_from_credentials(self, client, db):
        client.post("/integration/rotation-credentials", json={
            "date": "2026-11-18",
            "credentials": [
                {"id": "a1", "credential": "aws_one", "provider": "AWS", "live_copies": 10,
                 "coverage": "in-jira"},
                {"id": "a2", "credential": "aws_two", "provider": "AWS", "live_copies": 5,
                 "coverage": "not-in-tracker"},
                {"id": "g1", "credential": "gcp_thing", "provider": "Google Cloud",
                 "live_copies": 2, "coverage": "not-in-tracker"},
            ],
        })

        from db.models import RotationSnapshot
        aws = db.query(RotationSnapshot).filter_by(provider="AWS").one()
        assert (aws.verified_live, aws.live_locations, aws.untracked_live) == (2, 15, 1)
        gcp = db.query(RotationSnapshot).filter_by(provider="Google Cloud").one()
        assert (gcp.verified_live, gcp.live_locations, gcp.untracked_live) == (1, 2, 1)

    def test_provider_without_credentials_is_zeroed(self, client, db):
        _seed(db, date(2026, 11, 18), "Ghost", 3, 0, 0, 3, 0, 9, 9, 9)
        client.post("/integration/rotation-credentials", json={
            "date": "2026-11-18",
            "credentials": [{"id": "a1", "credential": "aws_one", "provider": "AWS",
                             "live_copies": 1, "coverage": "in-jira"}],
        })

        from db.models import RotationSnapshot
        ghost = db.query(RotationSnapshot).filter_by(provider="Ghost").one()
        assert (ghost.tickets, ghost.verified_live) == (3, 0)


class TestUnresolvedBucket:
    def test_unknown_credential_names_do_not_become_providers(self, client, db):
        client.post("/integration/rotation-credentials", json={
            "date": "2026-11-18",
            "credentials": [
                {"id": "u1", "credential": "fvmw-password", "live_copies": 9},
                {"id": "u2", "credential": "some_random_thing", "live_copies": 2},
                {"id": "a1", "credential": "aws_key", "provider": "AWS", "live_copies": 1},
            ],
        })

        from db.models import RotationSnapshot
        providers = {p.provider for p in db.query(RotationSnapshot).all()}
        assert providers == {"Unresolved / other", "AWS"}
        unresolved = db.query(RotationSnapshot).filter_by(provider="Unresolved / other").one()
        assert (unresolved.verified_live, unresolved.live_locations) == (2, 11)


class TestEmptyProviderRemoval:
    def test_row_with_no_tickets_and_no_credentials_is_deleted(self, client, db):
        _seed(db, date(2026, 11, 18), "Ghost", 0, 0, 0, 0, 0, 9, 9, 9)
        client.post("/integration/rotation-credentials", json={
            "date": "2026-11-18",
            "credentials": [{"id": "a1", "credential": "aws_key", "provider": "AWS",
                             "live_copies": 1, "coverage": "in-jira"}],
        })

        from db.models import RotationSnapshot
        assert db.query(RotationSnapshot).filter_by(provider="Ghost").count() == 0
