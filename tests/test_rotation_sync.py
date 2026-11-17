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
