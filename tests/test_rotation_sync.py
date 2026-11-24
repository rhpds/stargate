"""Rotation sync — provider parsing and aggregation cases (TDD, RED first)."""

import pytest

from collectors import rotation_sync as rs


def _issue(key, summary, status="New", assignee=None):
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "status": {"name": status},
            "assignee": {"displayName": assignee} if assignee else None,
        },
    }


class TestProviderParsing:
    @pytest.mark.parametrize("summary,expected", [
        ("[turkeyvulture] Maintenance — Rotate models_aws_s3_access_key (AWS)", "AWS"),
        ("[turkeyvulture] Maintenance — Rotate stargate-scanner-token (OCP SA Token (infra02))",
         "OpenShift / SA tokens"),
        ("[turkeyvulture] Maintenance — Rotate granite_bearerToken (AI / MaaS / Lightspeed — upstream unverified)",
         "AI / MaaS"),
        ("[turkeyvulture] Maintenance — Rotate x (Microsoft Azure)", "Microsoft Azure"),
        ("[turkeyvulture] Maintenance — Rotate x (IBM Cloud)", "IBM Cloud"),
        ("[turkeyvulture] Maintenance — Rotate x (Registry credentials — issuer unverified)", "Registry"),
        ("[turkeyvulture] Maintenance — Rotate something with no parenthetical", "Unclassified"),
        ("[turkeyvulture] Maintenance — Rotate x (sandbox-api-configs) (AWS / Route 53)", "AWS"),
        ("[turkeyvulture] Maintenance — Rotate x (Token (maas))", "AI / MaaS"),
        ("[turkeyvulture] Maintenance — Rotate x (P1 — Bitwarden Secrets Manager)", "Provider unset"),
        ("[turkeyvulture] Maintenance — Rotate AWS temporary/IAM credentials; IBM API key; "
         "OpenShift service-account credentials (P3 — Per-placement issued credentials)",
         "Provider unset"),
        ("[turkeyvulture] Maintenance — Rotate x (AWS / IBM Cloud)", "Multiple providers"),
        ("RHDP MaaS — Record and verify 881 virtual-key revocations", "AI / MaaS"),
    ])
    def test_parse_provider(self, summary, expected):
        assert rs.parse_provider(summary) == expected


class TestAggregation:
    def test_excludes_parent_epic(self):
        issues = [
            _issue("GPTEINFRA-18544", "Maintenance - 2026 Turkey Vulture"),
            _issue("GPTEINFRA-1", "[turkeyvulture] Maintenance — Rotate a (AWS)"),
        ]
        rows = rs.aggregate_issues(issues)
        assert sum(r["tickets"] for r in rows) == 1

    def test_status_and_unassigned_counts(self):
        issues = [
            _issue("A-1", "[turkeyvulture] Rotate a (AWS)", "Closed", "Ashok"),
            _issue("A-2", "[turkeyvulture] Rotate b (AWS)", "In Progress", "Ashok"),
            _issue("A-3", "[turkeyvulture] Rotate c (AWS)", "New", None),
        ]
        row = rs.aggregate_issues(issues)[0]
        assert (row["tickets"], row["closed"], row["in_progress"], row["new"], row["unassigned"]) == (3, 1, 1, 1, 1)

    def test_providers_sorted_by_tickets(self):
        issues = [
            _issue("A-1", "[turkeyvulture] Rotate a (AWS)"),
            _issue("A-2", "[turkeyvulture] Rotate b (AWS)"),
            _issue("B-1", "[turkeyvulture] Rotate c (IBM Cloud)"),
        ]
        rows = rs.aggregate_issues(issues)
        assert [r["provider"] for r in rows] == ["AWS", "IBM Cloud"]


class TestPagination:
    def test_two_pages_are_merged(self, monkeypatch):
        pages = [
            {"issues": [_issue("A-1", "[turkeyvulture] Rotate a (AWS)")], "isLast": False, "nextPageToken": "t2"},
            {"issues": [_issue("B-1", "[turkeyvulture] Rotate b (IBM Cloud)")], "isLast": True},
        ]
        calls = {"n": 0}

        def fake_get(url, token, next_token=None):
            page = pages[calls["n"]]
            calls["n"] += 1
            return page

        monkeypatch.setattr(rs, "_fetch_page", fake_get)
        issues = rs.fetch_issues("https://jira", "user", "tok")
        assert len(issues) == 2
        assert calls["n"] == 2


class TestPageRequest:
    def test_next_token_is_sent_to_jira(self, monkeypatch):
        """Found live: the token was never added, so page 1 repeated forever."""
        seen = {}

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"issues": [], "isLast": true}'

        def fake_urlopen(request, timeout=None):
            seen["url"] = request.full_url
            return _Response()

        monkeypatch.setattr(rs.urllib.request, "urlopen", fake_urlopen)
        rs._fetch_page("https://jira/rest/api/3/search/jql?jql=x", "auth", "t2")

        assert "nextPageToken=t2" in seen["url"]


class TestPaginationGuard:
    def test_repeated_token_raises_instead_of_looping(self, monkeypatch):
        page = {
            "issues": [_issue("A-1", "[turkeyvulture] Rotate a (AWS)")],
            "isLast": False,
            "nextPageToken": "same",
        }
        monkeypatch.setattr(rs, "_fetch_page", lambda url, token, next_token=None: page)
        with pytest.raises(RuntimeError, match="did not advance"):
            rs.fetch_issues("https://jira", "user", "tok")


class TestBucketFor:
    @pytest.mark.parametrize("raw,expected", [
        ("AWS", "AWS"),
        ("Microsoft Azure", "Microsoft Azure"),
        ("P1 — AWS; DNS/Route 53 account credentials", "AWS"),
        ("OCP SA Token (infra02)", "OpenShift / SA tokens"),
        ("ReachMail", "ReachMail"),
        ("x" * 120, "x" * 80),
        ("Storage", "Datastores / storage"),
        ("Datastores", "Datastores / storage"),
        ("", "Unclassified"),
    ])
    def test_raw_provider_names_map_to_canonical_buckets(self, raw, expected):
        assert rs.bucket_for(raw) == expected


class TestTicketUpsert:
    def _issue(self, key, summary, status="New", assignee=None):
        return _issue(key, summary, status, assignee)

    def test_stores_and_updates_tickets(self, db):
        rs.upsert_tickets(db, [
            self._issue("A-1", "[turkeyvulture] Rotate a (AWS)", "New", "Ashok"),
        ])
        db.commit()
        rs.upsert_tickets(db, [
            self._issue("A-1", "[turkeyvulture] Rotate a (AWS)", "Closed", "Ashok"),
        ])
        db.commit()

        from db.models import RotationTicket
        row = db.query(RotationTicket).filter_by(issue_key="A-1").one()
        assert (row.provider, row.status, row.assignee) == ("AWS", "Closed", "Ashok")

    def test_removes_tickets_that_left_the_epic(self, db):
        rs.upsert_tickets(db, [
            self._issue("A-1", "[turkeyvulture] Rotate a (AWS)"),
            self._issue("B-1", "[turkeyvulture] Rotate b (IBM Cloud)"),
        ])
        db.commit()
        rs.upsert_tickets(db, [self._issue("A-1", "[turkeyvulture] Rotate a (AWS)")])
        db.commit()

        from db.models import RotationTicket
        assert [t.issue_key for t in db.query(RotationTicket).all()] == ["A-1"]

    def test_ignores_the_parent_epic(self, db):
        rs.upsert_tickets(db, [
            self._issue("GPTEINFRA-18544", "Maintenance - 2026 Turkey Vulture"),
            self._issue("A-1", "[turkeyvulture] Rotate a (AWS)"),
        ])
        db.commit()

        from db.models import RotationTicket
        assert db.query(RotationTicket).count() == 1


class TestPruneStaleProviders:
    def _row(self, db, provider, tickets, verified=0):
        from db.models import RotationSnapshot
        from datetime import date, datetime, timezone
        db.add(RotationSnapshot(
            snapshot_date=date(2026, 11, 17), provider=provider, tickets=tickets,
            closed=0, in_progress=0, new=tickets, unassigned=0,
            verified_live=verified, live_locations=0, untracked_live=0,
            synced_at=datetime.now(timezone.utc)))
        db.commit()

    def test_removes_stale_ticket_rows(self, db):
        from datetime import date
        from db.models import RotationSnapshot
        self._row(db, "aka gpe) (AWS", 1)   # old taxonomy artefact

        removed = rs.prune_stale_providers(db, date(2026, 11, 17), ["AWS"])
        db.commit()

        assert removed == 1
        assert db.query(RotationSnapshot).count() == 0

    def test_keeps_audit_only_rows(self, db):
        from datetime import date
        from db.models import RotationSnapshot
        self._row(db, "NewCo", 0, verified=2)

        rs.prune_stale_providers(db, date(2026, 11, 17), ["AWS"])
        db.commit()

        row = db.query(RotationSnapshot).filter_by(provider="NewCo").one()
        assert row.verified_live == 2

    def test_zeroes_ticket_counters_but_keeps_audit(self, db):
        from datetime import date
        from db.models import RotationSnapshot
        self._row(db, "OldName", 5, verified=4)

        rs.prune_stale_providers(db, date(2026, 11, 17), ["AWS"])
        db.commit()

        row = db.query(RotationSnapshot).filter_by(provider="OldName").one()
        assert (row.tickets, row.verified_live) == (0, 4)


class TestSnapshotCompleteness:
    """An incomplete fetch must never be read as "the epic is empty".

    `upsert_tickets` deletes every ticket absent from the snapshot, so the
    snapshot has to be known-complete before it is allowed to speak for the
    whole epic. These are the two ways it could stop being complete without
    anyone noticing: a page that does not say it is the last one, and a
    result set that is genuinely empty because the query changed.
    """

    def test_empty_snapshot_keeps_stored_tickets(self, db):
        from db.models import RotationTicket

        rs.upsert_tickets(db, [_issue("A-1", "[turkeyvulture] Rotate a (AWS)")])
        db.commit()

        assert rs.upsert_tickets(db, []) == 0
        assert [t.issue_key for t in db.query(RotationTicket).all()] == ["A-1"]

    def test_page_without_is_last_raises(self, monkeypatch):
        monkeypatch.setattr(
            rs, "_fetch_page",
            lambda url, auth, next_token=None: {
                "issues": [_issue("A-1", "[turkeyvulture] Rotate a (AWS)")],
            },
        )

        with pytest.raises(RuntimeError, match="without isLast"):
            rs.fetch_issues("https://example.invalid", "e@example.com", "t")

    def test_page_without_is_last_still_follows_the_token(self, monkeypatch):
        """Missing `isLast` is not the same as "stop": a token means more."""
        pages = [
            {"issues": [_issue("A-1", "[turkeyvulture] Rotate a (AWS)")],
             "nextPageToken": "p2"},
            {"issues": [_issue("B-1", "[turkeyvulture] Rotate b (AWS)")],
             "isLast": True},
        ]
        monkeypatch.setattr(
            rs, "_fetch_page",
            lambda url, auth, next_token=None: pages[0] if next_token is None else pages[1],
        )

        keys = [i["key"] for i in rs.fetch_issues(
            "https://example.invalid", "e@example.com", "t")]
        assert keys == ["A-1", "B-1"]

    def test_sync_with_no_issues_keeps_today_s_rows(self, db, monkeypatch):
        from datetime import datetime, timezone

        from db.models import RotationSnapshot, RotationTicket

        today = datetime.now(timezone.utc).date()
        rs.upsert_tickets(db, [_issue("A-1", "[turkeyvulture] Rotate a (AWS)")])
        db.add(RotationSnapshot(
            snapshot_date=today, provider="AWS", tickets=1, closed=0,
            in_progress=0, new=1, unassigned=0, verified_live=0,
            live_locations=0, untracked_live=0,
            synced_at=datetime.now(timezone.utc)))
        db.commit()

        monkeypatch.setenv("STARGATE_JIRA_URL", "https://example.invalid")
        monkeypatch.setenv("STARGATE_JIRA_EMAIL", "e@example.com")
        monkeypatch.setenv("STARGATE_JIRA_TOKEN", "t")
        monkeypatch.setattr(rs, "fetch_issues", lambda *a, **k: [])

        result = rs.sync(db)

        assert result["status"] == "empty"
        assert db.query(RotationTicket).count() == 1
        assert db.query(RotationSnapshot).count() == 1
