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
