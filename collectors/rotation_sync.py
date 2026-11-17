"""Turkey Vulture rotation sync — Jira is the source of truth.

Pulls every issue labelled `turkeyvulture` (the children of epic
GPTEINFRA-18544), buckets them by provider, and writes one row per provider
per day into `rotation_snapshots`. The rotation page reads those rows; the
audit ingest (`POST /integration/rotation-snapshot`) fills in the verified-live
columns that StarGate cannot observe itself.

Why this is a collector and not a dashboard query: the epic has >200 issues and
Jira is rate-limited. A page load must never fan out to Atlassian, and the trend
needs a row per day whether or not anyone opened the page.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("stargate.rotation_sync")

PARENT_KEY = "GPTEINFRA-18544"
DEFAULT_URL = "https://redhat.atlassian.net"
DEFAULT_JQL = "labels = turkeyvulture ORDER BY key ASC"
FIELDS = "summary,status,assignee"
PAGE_SIZE = 100
TIMEOUT_SECONDS = 30

# Provider buckets — the order matters: first match wins, so put the specific
# names before the patterns that could swallow them.
_RULES = [
    ("AWS", r"\baws\b|amazon|assumerole"),
    ("Microsoft Azure", r"azure"),
    ("Google Cloud", r"google|\bgcp\b|vertex"),
    ("IBM Cloud", r"\bibm\b"),
    ("OpenShift / SA tokens", r"ocp sa|openshift|kubernetes|sa token|cluster.*token"),
    ("Registry", r"registry|quay"),
    ("GitHub", r"github"),
    ("AI / MaaS", r"\bmaas\b|\bmas\b|litellm|lightspeed|\bai\s*/"),
    ("OAuth / SSO", r"oauth|\bsso\b"),
    ("Red Hat hosted APIs", r"offline|rosa|rhsm|red hat (hosted|external)"),
    ("AAP / automation", r"\baap\b|automation|ansible"),
    ("Splunk", r"splunk"),
    ("Salesforce", r"salesforce"),
    ("Slack", r"slack"),
    ("SendGrid", r"sendgrid"),
    ("Atlassian / Jira", r"jira|atlassian"),
    ("Hugging Face", r"hugging"),
    ("Datastores / storage", r"database|datastore|postgres|redis|kafka|storage|\bs3\b"),
    ("TLS / certificates", r"cert|\btls\b|acme|zerossl"),
    ("RHDP internal", r"sandbox|rhdp internal|internal api"),
]


_PRIORITY_TAG = re.compile(r"^p\d+[a-z]?\b|priority")

# Buckets the rules actually produce. Anything else is a raw fallback — fine
# for a ticket title, useless as a credential's provider.
KNOWN_BUCKETS = frozenset(name for name, _ in _RULES) | {
    "Unclassified",
    "Provider unset",
    "Multiple providers",
    "Unresolved / other",
}


def bucket_for(raw: str) -> str:
    """Canonical provider bucket for a raw provider/type string.

    Shared with the audit publisher so a name that arrived through a ticket and
    the same name that arrived through a snapshot land in one row.

    Some tickets put a priority where a provider belongs ("P1 — Bitwarden
    Secrets Manager") and some span several providers. Guessing one of them
    would be a quiet lie, so those get their own explicit bucket.
    """
    cleaned = (raw or "").strip()
    lowered = cleaned.lower()
    if not lowered:
        return "Unclassified"

    matches = []
    for name, pattern in _RULES:
        if re.search(pattern, lowered) and name not in matches:
            matches.append(name)
    if len(matches) > 1:
        return "Multiple providers"
    if matches:
        return matches[0]
    if _PRIORITY_TAG.search(lowered):
        return "Provider unset"
    return cleaned[:80]  # column width; long raw names are a fallback, not a taxonomy


def _trailing_group(text: str) -> str:
    """The last balanced `(...)` at the end of the title.

    Titles can carry a second parenthetical before the provider —
    `Rotate x (sandbox-api-configs) (AWS / Route 53)` — and a greedy regex
    swallows both. Scan backwards so nesting such as
    `(OCP SA Token (infra02))` still returns the whole group.
    """
    stripped = (text or "").rstrip()
    if not stripped.endswith(")"):
        return ""
    depth = 0
    for index in range(len(stripped) - 1, -1, -1):
        char = stripped[index]
        if char == ")":
            depth += 1
        elif char == "(":
            depth -= 1
            if depth == 0:
                return stripped[index + 1 : -1]
    return ""


def parse_provider(summary: str) -> str:
    """Provider bucket from the ticket's trailing parenthetical.

    Titles follow the epic convention
    `[turkeyvulture] Maintenance — Rotate <variable> (<Provider / type>)`.
    The parenthetical may itself be nested — `(OCP SA Token (infra02))` — so
    match the outermost trailing group rather than the last short token.
    """
    group = _trailing_group(summary or "")
    if group:
        return bucket_for(group)
    # A few programme tickets have no provider parenthetical. Only MaaS is
    # unambiguous enough to infer from the title; everything else stays
    # Unclassified rather than guessing.
    if re.search(r"\bmaas\b", (summary or "").lower()):
        return "AI / MaaS"
    return "Unclassified"


def _is_child(issue: Dict[str, Any]) -> bool:
    """The epic itself is labelled turkeyvulture; its children carry the prefix."""
    if issue.get("key") == PARENT_KEY:
        return False
    summary = (issue.get("fields") or {}).get("summary") or ""
    return "[turkeyvulture]" in summary


def aggregate_issues(issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Per-provider ticket counts, sorted by ticket volume then name."""
    buckets: Dict[str, Dict[str, Any]] = {}
    for issue in issues:
        if not _is_child(issue):
            continue
        fields = issue.get("fields") or {}
        provider = parse_provider(fields.get("summary") or "")
        row = buckets.setdefault(
            provider,
            {
                "provider": provider,
                "tickets": 0,
                "closed": 0,
                "in_progress": 0,
                "new": 0,
                "unassigned": 0,
            },
        )
        row["tickets"] += 1
        status = ((fields.get("status") or {}).get("name") or "").lower()
        if status == "closed":
            row["closed"] += 1
        elif status == "in progress":
            row["in_progress"] += 1
        else:
            row["new"] += 1
        if not fields.get("assignee"):
            row["unassigned"] += 1

    return sorted(buckets.values(), key=lambda r: (-r["tickets"], r["provider"]))


def _ticket_row(issue: Dict[str, Any]) -> Dict[str, Any]:
    fields = issue.get("fields") or {}
    return {
        "issue_key": issue.get("key") or "",
        "provider": parse_provider(fields.get("summary") or ""),
        "summary": fields.get("summary") or "",
        "status": (fields.get("status") or {}).get("name") or "",
        "assignee": (fields.get("assignee") or {}).get("displayName") or None,
    }


def upsert_tickets(db, issues: List[Dict[str, Any]], now: Optional[datetime] = None) -> int:
    """Store each child ticket so a provider row can open into its work.

    Replaces the previous pull: the epic is the universe, so a ticket that
    vanished from the search is removed rather than left stale on the page.
    """
    from db.models import RotationTicket

    rows = [_ticket_row(issue) for issue in issues if _is_child(issue)]
    keys = [row["issue_key"] for row in rows]
    existing = {}
    if keys:
        existing = {
            ticket.issue_key: ticket
            for ticket in db.query(RotationTicket)
            .filter(RotationTicket.issue_key.in_(keys))
            .all()
        }

    for row in rows:
        ticket = existing.get(row["issue_key"])
        if ticket is None:
            ticket = RotationTicket(issue_key=row["issue_key"])
            db.add(ticket)
        ticket.provider = row["provider"]
        ticket.summary = row["summary"]
        ticket.status = row["status"]
        ticket.assignee = row["assignee"]
        ticket.synced_at = now or datetime.now(timezone.utc)

    if keys:
        db.query(RotationTicket).filter(~RotationTicket.issue_key.in_(keys)).delete(
            synchronize_session=False
        )
    else:
        db.query(RotationTicket).delete()
    return len(rows)


def prune_stale_providers(db, day, providers: List[str]) -> int:
    """Drop provider rows that no longer exist for `day`.

    Without this, a taxonomy change (or a provider whose last ticket closed)
    leaves yesterday's name in today's totals and every number is inflated.
    Rows carrying audit evidence are kept but have their ticket counters
    zeroed — the audit saw something real, even if Jira has no ticket for it.
    """
    from db.models import RotationSnapshot

    stale = (
        db.query(RotationSnapshot)
        .filter(RotationSnapshot.snapshot_date == day)
        .filter(~RotationSnapshot.provider.in_(providers) if providers else True)
        .all()
    )
    removed = 0
    for row in stale:
        if (row.verified_live or 0) + (row.live_locations or 0) + (row.untracked_live or 0) == 0:
            db.delete(row)
            removed += 1
        else:
            row.tickets = 0
            row.closed = 0
            row.in_progress = 0
            row.new = 0
            row.unassigned = 0
    return removed


def _fetch_page(url: str, auth: str, next_token: Optional[str] = None) -> Dict[str, Any]:
    """One Jira search page. `auth` is the pre-encoded Basic credential."""
    if next_token:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}nextPageToken={urllib.parse.quote(next_token, safe='')}"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Jira search failed: {exc.code} {body}") from exc


def fetch_issues(
    base_url: str,
    email: str,
    token: str,
    jql: str = DEFAULT_JQL,
) -> List[Dict[str, Any]]:
    """Every issue matching `jql`, following nextPageToken to the end."""
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    params = {"jql": jql, "maxResults": str(PAGE_SIZE), "fields": FIELDS}
    url = f"{base_url.rstrip('/')}/rest/api/3/search/jql?" + urllib.parse.urlencode(params)

    issues: List[Dict[str, Any]] = []
    next_token: Optional[str] = None
    seen_tokens: set[str] = set()
    while True:
        page = _fetch_page(url, auth, next_token)
        issues.extend(page.get("issues") or [])
        if page.get("isLast", True):
            break
        next_token = page.get("nextPageToken")
        if not next_token:
            break
        # A server that repeats a token would loop forever. Found live once:
        # the token was computed but never sent, so page 1 repeated endlessly.
        if next_token in seen_tokens:
            raise RuntimeError("Jira pagination did not advance (repeated nextPageToken)")
        seen_tokens.add(next_token)
    return issues


def jira_configured() -> bool:
    return bool(
        os.environ.get("STARGATE_JIRA_URL", "").strip()
        and os.environ.get("STARGATE_JIRA_TOKEN", "").strip()
        and os.environ.get("STARGATE_JIRA_EMAIL", "").strip()
    )


def sync(db) -> Dict[str, Any]:
    """Pull Jira and upsert today's ticket counters.

    Verified-live columns are preserved: they belong to the audit ingest, and a
    Jira sync must never zero them out. Returns a small summary for logging.
    """
    from db.models import RotationSnapshot

    if not jira_configured():
        return {"status": "unconfigured", "providers": 0, "issues": 0}

    base_url = os.environ.get("STARGATE_JIRA_URL", DEFAULT_URL).rstrip("/")
    email = os.environ["STARGATE_JIRA_EMAIL"]
    token = os.environ["STARGATE_JIRA_TOKEN"]
    jql = os.environ.get("STARGATE_ROTATION_JQL", DEFAULT_JQL)

    issues = fetch_issues(base_url, email, token, jql)
    rows = aggregate_issues(issues)
    today = datetime.now(timezone.utc).date()
    now = datetime.now(timezone.utc)
    upsert_tickets(db, issues, now)

    for row in rows:
        record = (
            db.query(RotationSnapshot)
            .filter_by(snapshot_date=today, provider=row["provider"])
            .first()
        )
        if record is None:
            record = RotationSnapshot(
                snapshot_date=today,
                provider=row["provider"],
                verified_live=0,
                live_locations=0,
                untracked_live=0,
            )
            db.add(record)
        record.tickets = row["tickets"]
        record.closed = row["closed"]
        record.in_progress = row["in_progress"]
        record.new = row["new"]
        record.unassigned = row["unassigned"]
        record.synced_at = now

    prune_stale_providers(db, today, [row["provider"] for row in rows])
    db.commit()
    logger.info(
        "Rotation sync: %s issues → %s providers for %s", len(issues), len(rows), today
    )
    return {"status": "ok", "providers": len(rows), "issues": len(issues), "date": str(today)}
