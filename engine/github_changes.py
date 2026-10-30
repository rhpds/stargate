"""GitHub PR change correlation — attribute failures to merged changes.

RHDP has no formal change management. The team's own triage workflow
(Confluence 436537517, Failed Item Triage) says:

    "Investigate: Check provision and destroy logs for error details.
    Review recent changes — AgnosticV merges, EE updates, cloud quota
    changes, infrastructure changes."

But "review recent changes" is tribal memory — nothing correlates merges
with observed failures. The documented incident record shows the pattern
repeatedly: agnosticv#28356 (pin fix, merged Sep 30), agnosticv#27528
(operator channel pin), jeffcpullen.agnosticp#6 (CSV wait extension),
agd-v2#227 (SSO/JSON defensive fix) — each a merged PR whose effect on
provisioning health was known only to whoever remembered it.

This module closes that gap:

1. Fetch merged PRs from the platform repos (GitHub REST API).
2. Detect a lab's failure onset from evaluation history (first failure
   after its last pass).
3. Correlate: PRs merged in the lookback window before onset whose
   changed files intersect the lab's AgnosticV path.

Fleet-wide changes (common.yaml, __meta__, cluster-config) are flagged
separately — they affect every lab and are the classic "nothing changed
in the lab, everything broke anyway" cause.

Auth: STARGATE_GITHUB_TOKEN (or GITHUB_TOKEN) env var. Anonymous access
works for public repos but is rate-limited and cannot see private repos.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("stargate.github_changes")

DEFAULT_REPOS = [
    "rhpds/agnosticv",
    "rhpds/agnosticd",
    "redhat-cop/agnosticd",
]

API_BASE = "https://api.github.com"

# Files that affect every lab using a repo, not just one catalog item.
FLEET_WIDE_MARKERS = (
    "common.yaml",
    "__meta__",
    "cluster-config",
    "requirements.yml",
    "ansible.cfg",
)

_pr_cache: Dict[str, Any] = {"prs": {}, "files": {}, "ts": 0.0}
_CACHE_TTL = 300


def _token() -> Optional[str]:
    return (
        os.environ.get("STARGATE_GITHUB_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
        or None
    )


def _api_get(path: str, token: Optional[str] = None) -> Any:
    """GET a GitHub API path. Returns parsed JSON, or None on error."""
    req = urllib.request.Request(API_BASE + path, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "stargate-change-correlation",
    })
    tok = token or _token()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError) as e:
        logger.warning("github api %s failed: %s", path, e)
        return None


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def fetch_merged_prs(
    repos: Optional[List[str]] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    max_per_repo: int = 50,
    token: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Merged PRs across repos, newest first. Cached briefly.

    Uses the search API (is:pr is:merged merged:range) — the pulls-list
    endpoint only returns the most recently updated ~50 closed PRs, which
    misses older windows. For merged PRs, search items' closed_at == merged_at.
    """
    repos = repos or [
        r.strip() for r in os.environ.get("STARGATE_GITHUB_REPOS", "").split(",")
        if r.strip()
    ] or DEFAULT_REPOS
    since = since or datetime.now(timezone.utc) - timedelta(days=7)

    cache_key = f"{','.join(repos)}|{since.isoformat()}|{(until or datetime.now(timezone.utc)).isoformat()}"
    now = time.time()
    if cache_key in _pr_cache["prs"] and now - _pr_cache["ts"] < _CACHE_TTL:
        return _pr_cache["prs"][cache_key]

    out: List[Dict[str, Any]] = []
    for repo in repos:
        until_ts = until or datetime.now(timezone.utc)
        q = (
            f"repo:{repo} is:pr is:merged "
            f"merged:{since.strftime('%Y-%m-%d')}..{until_ts.strftime('%Y-%m-%d')}"
        )
        data = _api_get(
            f"/search/issues?q={urllib.parse.quote(q)}&per_page={min(max_per_repo, 100)}",
            token=token,
        )
        if not isinstance(data, dict) or "items" not in data:
            continue
        for pr in data["items"]:
            merged_at = _parse_ts(pr.get("closed_at"))
            if not merged_at:
                continue
            out.append({
                "repo": repo,
                "number": pr.get("number"),
                "title": pr.get("title", ""),
                "author": (pr.get("user") or {}).get("login", ""),
                "merged_at": merged_at.isoformat(),
                "url": pr.get("html_url", ""),
                "changed_files": None,  # search API omits this; files fetched lazily
                "additions": None,
                "deletions": None,
            })
    out.sort(key=lambda p: p["merged_at"], reverse=True)
    _pr_cache["prs"][cache_key] = out
    _pr_cache["ts"] = now
    return out


def fetch_pr_files(repo: str, number: int, token: Optional[str] = None) -> List[str]:
    """Changed file paths for one PR. Cached."""
    key = f"{repo}#{number}"
    if key in _pr_cache["files"]:
        return _pr_cache["files"][key]
    data = _api_get(f"/repos/{repo}/pulls/{number}/files?per_page=100", token=token)
    files = [f.get("filename", "") for f in data] if isinstance(data, list) else []
    _pr_cache["files"][key] = files
    return files


def fetch_prs_in_review(
    repos: Optional[List[str]] = None,
    updated_since: Optional[datetime] = None,
    max_per_repo: int = 25,
    token: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Open PRs with their review state — changes in flight.

    An approved-but-unmerged PR touching a failing lab's files means a fix
    is inbound (or a regression is coming). Review states: approved,
    changes_requested, unreviewed. Cached briefly.
    """
    repos = repos or [
        r.strip() for r in os.environ.get("STARGATE_GITHUB_REPOS", "").split(",")
        if r.strip()
    ] or DEFAULT_REPOS
    updated_since = updated_since or datetime.now(timezone.utc) - timedelta(days=14)

    cache_key = f"reviews|{','.join(repos)}|{updated_since.isoformat()}"
    now = time.time()
    if cache_key in _pr_cache["prs"] and now - _pr_cache["ts"] < _CACHE_TTL:
        return _pr_cache["prs"][cache_key]

    out: List[Dict[str, Any]] = []
    for repo in repos:
        for state in ("approved", "changes_requested", "none"):
            q = (
                f"repo:{repo} is:pr is:open review:{state} "
                f"updated:>={updated_since.strftime('%Y-%m-%d')}"
            )
            data = _api_get(
                f"/search/issues?q={urllib.parse.quote(q)}&per_page={max_per_repo}",
                token=token,
            )
            if not isinstance(data, dict) or "items" not in data:
                continue
            for pr in data["items"]:
                out.append({
                    "repo": repo,
                    "number": pr.get("number"),
                    "title": pr.get("title", ""),
                    "author": (pr.get("user") or {}).get("login", ""),
                    "url": pr.get("html_url", ""),
                    "review_state": "approved" if state == "approved"
                    else ("changes_requested" if state == "changes_requested" else "unreviewed"),
                    "updated_at": pr.get("updated_at", ""),
                })
    # dedupe (a PR can match multiple states if reviews conflict)
    seen: Dict[int, Dict[str, Any]] = {}
    for pr in out:
        n = pr["number"]
        if n not in seen or pr["review_state"] == "approved":
            seen[n] = pr
    result = sorted(seen.values(), key=lambda p: p.get("updated_at") or "", reverse=True)
    _pr_cache["prs"][cache_key] = result
    _pr_cache["ts"] = now
    return result


def _normalize(s: str) -> str:
    """AgnosticV names mix - and _ (agd-v2 vs agd_v2), and lab codes join
    item segments with dots while repo paths use slashes. Normalize all
    separators (- _ . /) to one so 'agd-v2.item' matches 'agd_v2/item'."""
    return re.sub(r"[-_./]", "/", s.lower())


def _lab_path_candidates(lab_code: str, agnosticv_path: Optional[str]) -> List[str]:
    """Path fragments that identify a lab's files in a repo."""
    candidates = []
    if agnosticv_path:
        candidates.append(agnosticv_path.strip("/"))
    # lab_code forms: "RHPDS agd-v2.ocp-cluster-cnv-pools", "LB1758", sandbox ids.
    # Dotted item names carry the AgnosticV directory: agd-v2.<item>.<tier>
    for part in lab_code.replace("/", ".").split("."):
        part = part.strip()
        if len(part) >= 5 and not part.isdigit():
            # skip noise: RHPDS, LB1758, sandbox-ids, prod/event tiers
            if part.lower() in ("rhpds", "sandbox", "zt", "prod", "event"):
                continue
            if re.fullmatch(r"[A-Za-z]{0,3}\d+", part):
                continue  # ticket-style codes: LB1758, agd2, ocp4
            candidates.append(part)
    return [c for c in candidates if c]


def _pr_matches_lab(pr_files: List[str], candidates: List[str]) -> Tuple[bool, bool]:
    """Returns (matches_lab, is_fleet_wide)."""
    fleet_wide = any(m in f for f in pr_files for m in FLEET_WIDE_MARKERS)
    if not candidates:
        return False, fleet_wide
    norm_candidates = [_normalize(c) for c in candidates]
    for f in pr_files:
        norm_file = _normalize(f)
        if any(c and c in norm_file for c in norm_candidates):
            return True, fleet_wide
    return False, fleet_wide


def failure_onset(db, lab_code: str, hours: int = 168, now: Optional[datetime] = None) -> Optional[datetime]:
    """First failure after the lab's last pass in the window.

    The triage question is "when did this lab break?" — onset is the
    first fail evaluated after the most recent pass. If the lab has only
    failed in the window, onset is its first failure.
    """
    from db.models import EvaluationRecord

    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    rows = (
        db.query(EvaluationRecord)
        .filter(
            EvaluationRecord.lab_code == lab_code,
            EvaluationRecord.evaluated_at >= since,
        )
        .order_by(EvaluationRecord.evaluated_at.asc())
        .all()
    )
    last_pass: Optional[datetime] = None
    first_fail: Optional[datetime] = None
    for r in rows:
        at = r.evaluated_at if r.evaluated_at.tzinfo else r.evaluated_at.replace(tzinfo=timezone.utc)
        if r.outcome == "pass" and at >= since:
            last_pass = at
            first_fail = None  # reset: failures must come after the last pass
        elif r.outcome == "fail" and first_fail is None:
            first_fail = at
    return first_fail


def correlate_changes_for_lab(
    db,
    lab_code: str,
    lookback_hours: int = 72,
    onset: Optional[datetime] = None,
    repos: Optional[List[str]] = None,
    token: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """PRs merged before a lab's failure onset, ranked by path overlap.

    This automates step 4 of the team's Failed Item Triage workflow:
    'Review recent changes — AgnosticV merges, EE updates...'
    """
    from db.models import LabMapping

    mapping = db.query(LabMapping).filter(LabMapping.lab_code == lab_code).first()
    agnosticv_path = mapping.agnosticv_path if mapping else None

    if onset is None:
        onset = failure_onset(db, lab_code, now=now)
    if onset is None:
        return {
            "lab_code": lab_code,
            "agnosticv_path": agnosticv_path,
            "onset": None,
            "lookback_hours": lookback_hours,
            "prs_merged_in_window": 0,
            "changes": [],
            "in_flight": [],
            "lab_specific_changes": 0,
            "fleet_wide_changes": 0,
            "repos_scanned": repos or DEFAULT_REPOS,
            "note": "no failure onset found in evaluation history (window: "
                    "first failure after last pass, last 168h)",
        }

    since = onset - timedelta(hours=lookback_hours)
    prs = fetch_merged_prs(repos=repos, since=since, until=onset, token=token)

    candidates = _lab_path_candidates(lab_code, agnosticv_path)

    lab_changes: List[Dict[str, Any]] = []
    fleet_changes: List[Dict[str, Any]] = []
    for pr in prs:
        files = fetch_pr_files(pr["repo"], pr["number"], token=token)
        if not files and pr.get("changed_files"):
            # files fetch failed (rate limit / private) — keep the PR as context
            fleet_changes.append({**pr, "correlation": "unknown-files-unavailable"})
            continue
        matches_lab, fleet_wide = _pr_matches_lab(files, candidates)
        entry = {**pr, "correlation": "lab-path-match" if matches_lab else None}
        if matches_lab:
            entry["matching_files"] = [f for f in files if any(
                _normalize(c) in _normalize(f) for c in candidates
            )][:10]
            lab_changes.append(entry)
        elif fleet_wide:
            entry["correlation"] = "fleet-wide"
            fleet_changes.append(entry)

    # Changes in flight: open PRs with review state touching this lab's files.
    in_flight: List[Dict[str, Any]] = []
    try:
        open_prs = fetch_prs_in_review(repos=repos, token=token)
        for pr in open_prs:
            files = fetch_pr_files(pr["repo"], pr["number"], token=token)
            matches_lab, _ = _pr_matches_lab(files, candidates)
            if matches_lab:
                in_flight.append({
                    **pr,
                    "correlation": "fix-inbound" if pr["review_state"] == "approved" else "in-review",
                })
    except Exception:  # noqa: BLE001 — in-flight is enrichment, never fatal
        logger.debug("in-flight PR enrichment failed", exc_info=True)

    return {
        "lab_code": lab_code,
        "agnosticv_path": agnosticv_path,
        "onset": onset.isoformat(),
        "lookback_hours": lookback_hours,
        "prs_merged_in_window": len(prs),
        "changes": lab_changes + fleet_changes,
        "in_flight": in_flight,
        "lab_specific_changes": len(lab_changes),
        "fleet_wide_changes": len(fleet_changes),
        "repos_scanned": repos or DEFAULT_REPOS,
        "note": (
            "Lab-path matches are the strongest signal. Fleet-wide changes "
            "(common.yaml, __meta__, cluster-config) affect every lab — check "
            "whether other labs started failing at the same time. In-flight "
            "PRs: 'fix-inbound' = approved and touching this lab's files."
        ) if (lab_changes or fleet_changes) else
        "No merged PRs in the lookback window — the change is likely outside "
        "the scanned repos (cloud quota, EE image, cluster state).",
    }


def list_recent_changes(
    hours: int = 72,
    repos: Optional[List[str]] = None,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    """Recently merged PRs + PRs in review, across platform repos.

    Answers 'what changed recently?' for investigations and for the
    'review recent changes' triage step when no specific lab is implicated.
    In-review PRs carry review state (approved / changes_requested /
    unreviewed) — approved-but-unmerged is a change about to land.
    """
    prs = fetch_merged_prs(
        repos=repos,
        since=datetime.now(timezone.utc) - timedelta(hours=hours),
        token=token,
    )
    in_review: List[Dict[str, Any]] = []
    try:
        in_review = fetch_prs_in_review(repos=repos, token=token)
    except Exception:  # noqa: BLE001 — enrichment, never fatal
        pass
    return {
        "window_hours": hours,
        "repos": repos or DEFAULT_REPOS,
        "merged_prs": prs,
        "count": len(prs),
        "in_review": in_review,
        "in_review_count": len(in_review),
    }
