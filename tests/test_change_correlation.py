"""Tests for change correlation — GitHub PRs and Jira issues (engine/github_changes.py, engine/jira_changes.py).

Network is mocked throughout. Validation against real documented incidents
(agnosticv#28356, RHDPOPS-24544/24554, GPTEINFRA-18139) was done live;
these tests pin the correlation logic.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import text

from db.database import Base
from engine.github_changes import (
    _pr_matches_lab,
    _lab_path_candidates,
    correlate_changes_for_lab,
    failure_onset,
    fetch_merged_prs,
    fetch_prs_in_review,
    list_recent_changes,
)
from engine.jira_changes import _search_terms, correlate_issues_for_lab

from tests.conftest import TestSession, test_engine

NOW = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)


# --- GitHub: pure matching logic -----------------------------------------

def test_pr_matches_lab_path():
    files = ["agd_v2/ocp-cluster-cnv-pools/event.yaml", "README.md"]
    matches, fleet = _pr_matches_lab(files, ["agd_v2/ocp-cluster-cnv-pools"])
    assert matches and not fleet


def test_pr_matches_lab_normalizes_dashes_and_underscores():
    # lab code says agd-v2, repo path says agd_v2
    files = ["agd_v2/ocp-cluster-cnv-pools/event.yaml"]
    matches, _ = _pr_matches_lab(files, ["agd-v2.ocp-cluster-cnv-pools"])
    assert matches


def test_pr_no_match_for_unrelated_files():
    files = ["summit-2026/lb1237-hol-rhel10-cnv/event.yaml"]
    matches, fleet = _pr_matches_lab(files, ["ocp-cluster-cnv-pools"])
    assert not matches and not fleet


def test_fleet_wide_detection():
    files = ["common.yaml", "docs/x.md"]
    matches, fleet = _pr_matches_lab(files, ["some-lab"])
    assert not matches and fleet


def test_lab_path_candidates_from_lab_code():
    # dotted item names carry the AgnosticV directory
    cands = _lab_path_candidates("RHPDS agd-v2.ocp-cluster-cnv-pools", None)
    assert "ocp-cluster-cnv-pools" in cands
    # short/noise tokens are skipped
    cands2 = _lab_path_candidates("LB1758", None)
    assert cands2 == []


# --- GitHub: fetchers with mocked API ------------------------------------

def _mock_pr(number, repo="rhpds/agnosticv", closed_at="2026-10-19T10:00:00Z"):
    return {"number": number, "title": f"PR {number}", "user": {"login": "dev"},
            "html_url": f"https://github.com/{repo}/pull/{number}",
            "closed_at": closed_at}


def test_fetch_merged_prs_uses_search_api(monkeypatch):
    calls = []

    def fake_get(path, token=None):
        calls.append(path)
        if "/search/issues" in path:
            return {"items": [_mock_pr(1), _mock_pr(2)]}
        return None

    monkeypatch.setattr("engine.github_changes._api_get", fake_get)
    prs = fetch_merged_prs(repos=["rhpds/agnosticv"], since=NOW - timedelta(days=3))
    assert len(prs) == 2
    assert all("search/issues" in c for c in calls)
    assert prs[0]["repo"] == "rhpds/agnosticv"
    assert prs[0]["merged_at"].startswith("2026-10-19")


def test_fetch_prs_in_review_dedupes(monkeypatch):
    import urllib.parse as _up

    def fake_get(path, token=None):
        p = _up.unquote(path)
        if "review:approved" in p:
            return {"items": [_mock_pr(10)]}
        if "review:changes_requested" in p:
            return {"items": []}
        if "review:none" in p:
            return {"items": [_mock_pr(10), _mock_pr(11)]}  # 10 matches two states
        return None

    monkeypatch.setattr("engine.github_changes._api_get", fake_get)
    prs = fetch_prs_in_review(repos=["rhpds/agnosticv"])
    nums = [p["number"] for p in prs]
    assert nums.count(10) == 1  # deduped, approved wins
    by_num = {p["number"]: p for p in prs}
    assert by_num[10]["review_state"] == "approved"
    assert by_num[11]["review_state"] == "unreviewed"


def test_list_recent_changes_includes_in_review(monkeypatch):
    monkeypatch.setattr("engine.github_changes.fetch_merged_prs", lambda **kw: [_mock_pr(1)])
    monkeypatch.setattr("engine.github_changes.fetch_prs_in_review", lambda **kw: [])
    out = list_recent_changes(hours=24)
    assert out["count"] == 1
    assert "in_review" in out


# --- GitHub: failure onset + correlation ----------------------------------

@pytest.fixture()
def ch_db():
    Base.metadata.create_all(bind=test_engine)
    db = TestSession()
    # lab-x healthy Oct 18, fails starting Oct 19 08:00
    for h in range(6):
        db.execute(text(
            "INSERT INTO evaluations (run_id, stage_id, outcome, evaluated_at, lab_code, cluster_name) "
            "VALUES (:r, 'showroom-healthy', 'pass', :at, 'lab-x', 'ocpvA')"
        ), {"r": f"p{h}", "at": datetime(2026, 10, 18, h, 0, tzinfo=timezone.utc)})
    for h in range(3):
        db.execute(text(
            "INSERT INTO evaluations (run_id, stage_id, outcome, evaluated_at, lab_code, cluster_name) "
            "VALUES (:r, 'showroom-healthy', 'fail', :at, 'lab-x', 'ocpvA')"
        ), {"r": f"f{h}", "at": datetime(2026, 10, 19, 8 + h, 0, tzinfo=timezone.utc)})
    db.commit()
    yield db
    db.rollback()
    db.close()
    Base.metadata.drop_all(bind=test_engine)


def test_failure_onset_after_last_pass(ch_db):
    onset = failure_onset(ch_db, "lab-x", hours=72, now=NOW)
    assert onset == datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)


def test_correlate_changes_lab_path_match(ch_db, monkeypatch):
    # PR merged 6h before onset, touching the lab's files
    monkeypatch.setattr("engine.github_changes.fetch_merged_prs",
                        lambda **kw: [{"repo": "rhpds/agnosticv", "number": 100,
                                       "title": "pin fix", "author": "dev",
                                       "merged_at": "2026-10-19T02:00:00+00:00",
                                       "url": "u", "changed_files": 2,
                                       "additions": 1, "deletions": 1}])
    monkeypatch.setattr("engine.github_changes.fetch_pr_files",
                        lambda repo, number, token=None: ["agd_v2/lab-x/event.yaml"])
    monkeypatch.setattr("engine.github_changes.fetch_prs_in_review", lambda **kw: [])
    monkeypatch.setattr("engine.github_changes._lab_path_candidates", lambda lc, ap: ["lab-x"])

    out = correlate_changes_for_lab(ch_db, "lab-x", now=NOW)
    assert out["onset"].startswith("2026-10-19T08:00")
    assert out["lab_specific_changes"] == 1
    assert out["changes"][0]["correlation"] == "lab-path-match"
    assert "matching_files" in out["changes"][0]


def test_correlate_changes_fix_inbound(ch_db, monkeypatch):
    monkeypatch.setattr("engine.github_changes.fetch_merged_prs", lambda **kw: [])
    monkeypatch.setattr("engine.github_changes.fetch_pr_files",
                        lambda repo, number, token=None: ["agd_v2/lab-x/event.yaml"])
    monkeypatch.setattr("engine.github_changes.fetch_prs_in_review", lambda **kw: [
        {"repo": "rhpds/agnosticv", "number": 200, "title": "fix lab-x",
         "author": "dev", "url": "u", "review_state": "approved",
         "updated_at": "2026-10-20T10:00:00Z"},
    ])
    monkeypatch.setattr("engine.github_changes._lab_path_candidates", lambda lc, ap: ["lab-x"])

    out = correlate_changes_for_lab(ch_db, "lab-x", now=NOW)
    assert out["in_flight"], "approved PR touching lab files should be fix-inbound"
    assert out["in_flight"][0]["correlation"] == "fix-inbound"


# --- Jira ------------------------------------------------------------------

def test_search_terms_prefers_ci_name():
    terms = _search_terms("LB1758", "OCP Virt Migration Factory Demo")
    assert terms[0] == "OCP Virt Migration Factory Demo"


def test_search_terms_from_lab_code_tokens():
    terms = _search_terms("RHPDS agd-v2.ocp-cluster-cnv-pools", None)
    assert "ocp-cluster-cnv-pools" in terms
    assert all(t.lower() != "rhpds" for t in terms)


def test_correlate_issues_annotates_alignment(ch_db, monkeypatch):
    def fake_search(jql, max_results=25):
        return [{
            "key": "RHDPOPS-999", "summary": "lab-x broken",
            "status": "Closed", "issue_type": "Bug", "priority": "Major",
            "labels": [], "assignee": "", "created": "2026-10-19T09:00:00.000+0000",
            "updated": "2026-10-19T12:00:00.000+0000",
            "resolved": "2026-10-19T15:00:00.000+0000", "url": "u",
        }]

    monkeypatch.setattr("engine.jira_changes._search", fake_search)
    monkeypatch.setattr("engine.jira_changes._search_terms", lambda lc, cn: ["lab-x"])
    out = correlate_issues_for_lab(ch_db, "lab-x", now=NOW)
    assert out["onset"].startswith("2026-10-19T08:00")
    issue = out["issues"][0]
    # created 1h after onset → "created near failure onset"
    assert any("noticed by a human" in a for a in issue["alignment"])
    # resolved same day → "resolved in window"
    assert any("the fix" in a for a in issue["alignment"])


def test_correlate_issues_no_onset(ch_db, monkeypatch):
    out = correlate_issues_for_lab(ch_db, "lab-never-failed")
    assert out["onset"] is None
    assert out["issues"] == []


def test_failure_episode_onset_for_flapping_lab(ch_db):
    """Flapping labs (fails + passes interleaved) get episode onset:
    failures happening continuously since the episode start."""
    from engine.github_changes import failure_episode_onset
    # flapping: fails at 2h intervals across the last 24h, passes interleaved
    for h in range(12):
        at = NOW - timedelta(hours=24 - h * 2)
        ch_db.execute(text(
            "INSERT INTO evaluations (run_id, stage_id, outcome, evaluated_at, lab_code, cluster_name) "
            "VALUES (:r, 'showroom-healthy', :o, :at, 'lab-flap', 'ocpvA')"
        ), {"r": f"flap{h}", "o": "fail" if h % 2 == 0 else "pass", "at": at})
    ch_db.commit()

    clean = failure_onset(ch_db, "lab-flap", hours=48, now=NOW)
    assert clean is None, "flapping lab has no clean-break onset"
    episode = failure_episode_onset(ch_db, "lab-flap", hours=48, now=NOW)
    assert episode is not None, "episode onset must be defined for flapping labs"
    assert episode <= NOW - timedelta(hours=22), "episode covers the continuous failure run"


def test_correlate_uses_episode_onset_fallback(ch_db, monkeypatch):
    """Correlation falls back to episode onset for flapping labs."""
    monkeypatch.setattr("engine.github_changes.fetch_merged_prs", lambda **kw: [])
    monkeypatch.setattr("engine.github_changes.fetch_prs_in_review", lambda **kw: [])
    monkeypatch.setattr("engine.github_changes._lab_path_candidates", lambda lc, ap: ["lab-flap"])
    for h in range(8):
        at = NOW - timedelta(hours=16 - h * 2)
        ch_db.execute(text(
            "INSERT INTO evaluations (run_id, stage_id, outcome, evaluated_at, lab_code, cluster_name) "
            "VALUES (:r, 'showroom-healthy', :o, :at, 'lab-flap', 'ocpvA')"
        ), {"r": f"fb{h}", "o": "fail" if h % 2 == 0 else "pass", "at": at})
    ch_db.commit()

    out = correlate_changes_for_lab(ch_db, "lab-flap", now=NOW)
    assert out["onset"] is not None
    assert out["onset_mode"] == "continuous-episode"


def test_jira_episode_onset_fallback(ch_db, monkeypatch):
    """Jira correlation falls back to episode onset for flapping labs."""
    # seed flapping lab: fails every 2h across the last 24h, passes interleaved
    for h in range(12):
        ch_db.execute(text(
            "INSERT INTO evaluations (run_id, stage_id, outcome, evaluated_at, lab_code, cluster_name) "
            "VALUES (:r, 'showroom-healthy', :o, :at, 'lab-flap', 'ocpvA')"
        ), {"r": f"jf{h}", "o": "fail" if h % 2 == 0 else "pass",
            "at": NOW - timedelta(hours=24 - h * 2)})
    ch_db.commit()

    def fake_search(jql, max_results=25):
        return [{"key": "RHDPOPS-777", "summary": "flap lab degraded", "status": "Open",
                 "issue_type": "Bug", "priority": "Major", "labels": [], "assignee": "",
                 "created": "2026-10-19T09:00:00.000+0000", "updated": "2026-10-19T10:00:00.000+0000",
                 "resolved": None, "url": "u"}]

    monkeypatch.setattr("engine.jira_changes._search", fake_search)
    monkeypatch.setattr("engine.jira_changes._search_terms", lambda lc, cn: ["lab-flap"])
    out = correlate_issues_for_lab(ch_db, "lab-flap", now=NOW)
    assert out["onset"] is not None, "episode fallback must define onset for flapping labs"
    assert out["onset_mode"] == "continuous-episode"
    assert out["issues"], "search must run once onset exists"
