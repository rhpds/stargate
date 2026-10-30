"""Jira change correlation — attribute failures to tracked tickets.

Companion to engine/github_changes.py. RHDP has no formal change
management, but it DOES have tickets: RHDPOPS (ops), GPTEINFRA
(infrastructure + post-mortem actions), RHDPSPPT (JSM service desk).
The team's triage workflows are built around them:

- Destroy Failure Triage: "Create an RHDPOPS ticket ... use the
  destroy-failure label" (project = RHDPOPS AND labels = destroy_failure)
- Failed Item Triage: "Update the Jira ticket with root cause and
  resolution"
- Post-Mortem Actions Tracker: GPTEINFRA issues per incident

The documented incident record is full of ticket-linked causality:
RHDPOPS-24554 (account bloat, fixed Oct 14), RHDPOPS-24544 (ocpv06/08
saturation), GPTEINFRA-18139/18140/18141 (the three failing Summit
tenant labs), GPTEINFRA-18383/18384 (content-owner escalations).

Correlation semantics (mirroring the GitHub module):

1. failure onset — first fail after the lab's last pass
2. issues MENTIONING the lab (ci_name / catalog tokens) in the window
3. temporal alignment:
   - issue CREATED near onset → someone noticed the same breakage
   - issue RESOLVED near failure-stop → the fix (strongest signal)
   - issue UPDATED in window → related churn

Auth: Atlassian API token (same credential as Confluence):
STARGATE_JIRA_EMAIL + STARGATE_JIRA_TOKEN, instance STARGATE_JIRA_URL
(default https://redhat.atlassian.net). Basic auth.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from engine.github_changes import failure_onset

logger = logging.getLogger("stargate.jira_changes")

DEFAULT_JIRA_URL = "https://redhat.atlassian.net"
DEFAULT_PROJECTS = ["RHDPOPS", "GPTEINFRA", "RHDPSPPT"]

_issue_cache: Dict[str, Any] = {"queries": {}, "ts": 0.0}
_CACHE_TTL = 300


def _auth_header() -> Optional[str]:
    email = os.environ.get("STARGATE_JIRA_EMAIL", "")
    token = os.environ.get("STARGATE_JIRA_TOKEN", "")
    if not email or not token:
        return None
    raw = f"{email}:{token}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _jira_url() -> str:
    return os.environ.get("STARGATE_JIRA_URL", DEFAULT_JIRA_URL).rstrip("/")


def _search(jql: str, max_results: int = 25) -> Optional[List[Dict[str, Any]]]:
    """Run a JQL search. Returns issue dicts or None on failure.

    Uses the current Jira Cloud search API (POST /rest/api/3/search/jql);
    the legacy GET /rest/api/2/search returns 410 Gone since late 2025.
    """
    auth = _auth_header()
    if not auth:
        logger.warning("jira search skipped: STARGATE_JIRA_EMAIL/TOKEN not set")
        return None
    now = time.time()
    key = jql
    if key in _issue_cache["queries"] and now - _issue_cache["ts"] < _CACHE_TTL:
        return _issue_cache["queries"][key]

    body = json.dumps({
        "jql": jql,
        "maxResults": max_results,
        "fields": ["summary", "status", "created", "updated", "resolutiondate",
                   "issuetype", "labels", "priority", "assignee"],
    }).encode()
    req = urllib.request.Request(
        f"{_jira_url()}/rest/api/3/search/jql",
        data=body,
        method="POST",
        headers={
            "Authorization": auth,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "stargate-change-correlation",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
        issues = [_to_issue(i) for i in data.get("issues", [])]
        _issue_cache["queries"][key] = issues
        _issue_cache["ts"] = now
        return issues
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, OSError) as e:
        logger.warning("jira search failed: %s", e)
        return None


def _to_issue(raw: Dict[str, Any]) -> Dict[str, Any]:
    f = raw.get("fields", {})
    return {
        "key": raw.get("key", ""),
        "summary": f.get("summary", ""),
        "status": (f.get("status") or {}).get("name", ""),
        "issue_type": (f.get("issuetype") or {}).get("name", ""),
        "priority": ((f.get("priority") or {}).get("name", "")),
        "labels": f.get("labels", []),
        "assignee": ((f.get("assignee") or {}).get("displayName", "")),
        "created": f.get("created"),
        "updated": f.get("updated"),
        "resolved": f.get("resolutiondate"),
        "url": f"{_jira_url()}/browse/{raw.get('key', '')}",
    }


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _search_terms(lab_code: str, ci_name: Optional[str]) -> List[str]:
    """Text terms that identify this lab in ticket prose.

    Tickets use catalog item NAMES ('OCP Virt Migration Factory Demo'),
    not lab codes. Prefer ci_name from LabMapping; fall back to the
    longest distinctive tokens of the lab code.
    """
    terms: List[str] = []
    if ci_name and len(ci_name) >= 8:
        terms.append(ci_name)
    for part in re.split(r"[./\s]+", lab_code):
        part = part.strip()
        if len(part) >= 6 and part.lower() not in (
            "sandbox", "rhpds", "prod", "event",
        ):
            terms.append(part)
    return terms[:4]


def correlate_issues_for_lab(
    db,
    lab_code: str,
    lookback_hours: int = 168,
    onset: Optional[datetime] = None,
    projects: Optional[List[str]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Jira issues mentioning a lab, aligned to its failure onset."""
    from db.models import LabMapping

    projects = projects or DEFAULT_PROJECTS
    if onset is None:
        onset = failure_onset(db, lab_code, now=now)
    if onset is None:
        return {"lab_code": lab_code, "onset": None, "issues": [],
                "note": "no failure onset found in evaluation history"}

    mapping = db.query(LabMapping).filter(LabMapping.lab_code == lab_code).first()
    ci_name = mapping.ci_name if mapping else None
    terms = _search_terms(lab_code, ci_name)

    issues: List[Dict[str, Any]] = []
    for term in terms:
        phrase = f'"{term}"' if " " in term else term
        jql = (
            f'project IN ({", ".join(projects)}) AND text ~ {json.dumps(phrase)} '
            f'AND updated >= "{(onset - timedelta(hours=lookback_hours)).strftime("%Y-%m-%d %H:%M")}" '
            f'ORDER BY updated DESC'
        )
        found = _search(jql) or []
        seen = {i["key"] for i in issues}
        for i in found:
            if i["key"] not in seen:
                i["matched_term"] = term
                issues.append(i)

    # temporal alignment annotation
    for i in issues:
        created = _parse_ts(i.get("created"))
        resolved = _parse_ts(i.get("resolved"))
        notes = []
        if created and abs((created - onset).total_seconds()) < 24 * 3600:
            notes.append("created near failure onset — same breakage noticed by a human")
        if resolved and resolved >= onset - timedelta(hours=lookback_hours):
            notes.append("resolved in window — likely the fix; verify failures stopped after")
        i["alignment"] = notes

    issues.sort(key=lambda i: i.get("updated") or "", reverse=True)
    return {
        "lab_code": lab_code,
        "ci_name": ci_name,
        "onset": onset.isoformat(),
        "lookback_hours": lookback_hours,
        "search_terms": terms,
        "projects": projects,
        "issues": issues,
        "note": (
            "'Resolved in window' is the strongest signal — cross-check that the "
            "lab's failures stopped after the resolution timestamp."
        ) if issues else
        "No tickets mention this lab — the breakage may be unreported.",
    }


def list_recent_incidents(
    hours: int = 168,
    projects: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Recently updated ops tickets — the 'what's the team dealing with' view.

    Mirrors list_recent_changes in the GitHub module.
    """
    projects = projects or ["RHDPOPS", "GPTEINFRA"]
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
    jql = (
        f'project IN ({", ".join(projects)}) AND updated >= "{since}" '
        f'ORDER BY updated DESC'
    )
    issues = _search(jql, max_results=50) or []
    return {
        "window_hours": hours,
        "projects": projects,
        "issues": issues,
        "count": len(issues),
    }
