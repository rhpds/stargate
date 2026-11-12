"""Sync the StarGate repo docs to the Confluence page tree — idempotently.

The repo is the source of truth; Confluence is the discovery surface.
This script makes the mirror maintainable:

- Matched by title under the parent page: created if missing, UPDATED
  (version+1) only when the rendered body actually changed, untouched
  otherwise. Re-running is always safe.
- Credentials via STARGATE_CONFLUENCE_EMAIL + STARGATE_CONFLUENCE_TOKEN
  (never committed).
- Part of the Friday release: run after deploy so docs and code ship
  together.

Usage:
    STARGATE_CONFLUENCE_EMAIL=... STARGATE_CONFLUENCE_TOKEN=... \
        python3 scripts/confluence_sync.py [--check]

    --check: report drift without writing (CI/release gate friendly).
"""

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

SPACE_ID = "286752768"
PARENT_ID = "514491437"
API = "https://redhat.atlassian.net/wiki"

# (repo doc, Confluence title) — the full StarGate page tree.
# The overview and MCP guide pages were created with richer hand-built
# bodies; this sync owns the mirrored reference docs.
DOCS = [
    ("workflows.md", "StarGate Workflows — Event Flows and Data Locations"),
    ("architecture.md", "StarGate Architecture"),
    ("reference-architecture.md", "StarGate Production Reference Architecture — As Is"),
    ("runbook.md", "StarGate Runbook"),
    ("configuration.md", "StarGate Configuration Reference"),
    ("incident-validation-2026-10.md", "StarGate Incident Validation — Oct 2026"),
    ("config-management.md", "StarGate Config Management (ConfigMap + AAP pattern)"),
    ("proof-lab-ecosystem.md", "StarGate Proof Lab Ecosystem"),
    ("evidence-observation-semantics.md", "StarGate Evidence and Observation Semantics"),
    ("cascade-integration-design.md", "StarGate Cascade Integration Design — Proposed"),
    ("stargate-mcp-agent-guide.md", "StarGate MCP Agent Guide (Mirrored)"),
    ("mcp-tool-cookbook.md", "StarGate MCP Tool Cookbook — What to Ask, What You Get"),
    ("investigation-workflow.md", "StarGate Investigation Workflow"),
    ("status-update-2026-11.md", "StarGate Status Update — Failure Log Output & MCP (Nov 2026)"),
    ("cascade-shadow-validation-plan.md", "StarGate Cascade Shadow Validation Plan"),
    ("capacity-forecaster-plan.md", "StarGate Capacity Forecaster Plan"),
    ("cascade-backtest-2026-11.md", "StarGate Cascade Backtest — Phase 0 Results (Nov 2026)"),
]

REPO_URL = "https://github.com/rhpds/stargate"


# ---------------------------------------------------------------------------
# Generated pages (built at sync time from repo state, not from a .md file)
# ---------------------------------------------------------------------------

def _taxonomy_body() -> str:
    """The failure taxonomy, grouped by source file — the team's own
    troubleshooting knowledge, structured and queryable."""
    import html as _html
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from engine.failure_class_loader import get_all_classes

    classes = get_all_classes()
    by_source: dict = {}
    for c in classes:
        by_source.setdefault(c.get("_source_file", "other"), []).append(c)

    parts = [
        "<p>The structured version of the team's troubleshooting knowledge: "
        f"{len(classes)} failure classes with detection patterns, severity, "
        "owning team, and remediation guidance. 19 of these came directly "
        "from this space's troubleshooting pages and post-mortems; the rest "
        "from production failure patterns. Queryable live via the MCP "
        "<code>get_failure_classes</code> tool.</p>"
    ]
    for source_file in sorted(by_source):
        group = sorted(by_source[source_file], key=lambda c: c["name"])
        parts.append(f"<h2>{_html.escape(source_file)} ({len(group)} classes)</h2>")
        parts.append("<table><tbody><tr><th>Class</th><th>Severity</th><th>Team</th>"
                     "<th>Description</th><th>Remediation</th></tr>")
        for c in group:
            remediation = "".join(
                f"<li>{_html.escape(str(r))}</li>" for r in (c.get("remediation") or [])
            )
            remediation = f"<ul>{remediation}</ul>" if remediation else "—"
            desc = _html.escape(str(c.get("description") or ""))
            pattern = _html.escape(str(c.get("pattern") or ""))
            parts.append(
                f"<tr><td><strong><code>{_html.escape(c['name'])}</code></strong>"
                f"<br/><em>pattern:</em> <code>{pattern[:120]}</code></td>"
                f"<td>{_html.escape(str(c.get('severity') or '?'))}</td>"
                f"<td>{_html.escape(str(c.get('team') or '?'))}</td>"
                f"<td>{desc}</td><td>{remediation}</td></tr>"
            )
        parts.append("</tbody></table>")
    return "\n".join(parts)


def _taxonomy_hash() -> str:
    """Hash of all taxonomy YAML sources — changes when any class changes."""
    import hashlib
    fc_dir = Path(__file__).parent.parent / "failure-classes"
    h = hashlib.sha256()
    for path in sorted(fc_dir.glob("*.yaml")):
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _release_notes_body() -> str:
    """Commits to main, grouped by the Friday they ship."""
    import datetime as _dt
    import subprocess

    try:
        out = subprocess.run(
            ["git", "log", "--since=8 weeks ago", "--date=short", "--no-merges",
             "--pretty=format:%h|%ad|%s"],
            capture_output=True, text=True, timeout=30,
            cwd=Path(__file__).parent.parent,
        ).stdout.strip()
    except Exception:
        out = ""
    if not out:
        return "<p>No recent commits found.</p>"

    commits = []
    for line in out.split("\n"):
        parts = line.split("|", 2)
        if len(parts) == 3:
            commits.append({"sha": parts[0], "date": parts[1], "subject": parts[2]})

    today = _dt.date.today()
    # the release Friday for a given day: the next Friday (or today if Friday)
    days_ahead = (4 - today.weekday()) % 7  # Monday=0 ... Friday=4
    this_friday = today + _dt.timedelta(days=days_ahead)

    groups: dict = {}
    for c in commits:
        d = _dt.date.fromisoformat(c["date"])
        days_ahead = (4 - d.weekday()) % 7
        friday = d + _dt.timedelta(days=days_ahead)
        groups.setdefault(friday, []).append(c)

    parts = ["<p>Releases go out <strong>Fridays</strong>. Commits to main, "
             "grouped by the Friday they ship. Current week is "
             "<em>queued</em> until it ships.</p>"]
    for friday in sorted(groups, reverse=True):
        label = (f"Queued for Friday {friday.isoformat()}" if friday == this_friday
                 else f"Released Friday {friday.isoformat()}")
        parts.append(f"<h2>{label}</h2><ul>")
        for c in groups[friday]:
            import html as _html
            parts.append(f"<li><code>{c['sha']}</code> {_html.escape(c['subject'])}</li>")
        parts.append("</ul>")
    return "\n".join(parts)


def _release_notes_hash() -> str:
    import hashlib
    import subprocess
    try:
        out = subprocess.run(
            ["git", "log", "--since=8 weeks ago", "--no-merges", "--pretty=format:%h %s"],
            capture_output=True, text=True, timeout=30,
            cwd=Path(__file__).parent.parent,
        ).stdout
    except Exception:
        out = ""
    return hashlib.sha256(out.encode()).hexdigest()[:16]


# (title, body builder, hash builder) — generated pages
GENERATED_DOCS = [
    ("StarGate Failure Taxonomy", _taxonomy_body, _taxonomy_hash),
    ("StarGate Release Notes", _release_notes_body, _release_notes_hash),
]


def _auth():
    email = os.environ.get("STARGATE_CONFLUENCE_EMAIL", "")
    token = os.environ.get("STARGATE_CONFLUENCE_TOKEN", "")
    if not email or not token:
        print("ERROR: set STARGATE_CONFLUENCE_EMAIL and STARGATE_CONFLUENCE_TOKEN")
        sys.exit(2)
    return "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()


def _request(method: str, path: str, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        API + path, data=data, method=method,
        headers={
            "Authorization": _auth(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode()
            return json.loads(body) if body.strip() else {"status": resp.status}
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} on {method} {path}: {e.read().decode()[:200]}")
        return None


def escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline(md: str) -> str:
    out = escape_html(md)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"<em>\1</em>", out)
    out = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', out)
    return out


def code_macro(text: str) -> str:
    return ('<ac:structured-macro ac:name="code">'
            f'<ac:plain-text-body><![CDATA[{text}]]></ac:plain-text-body>'
            '</ac:structured-macro>')


def convert(md_text: str) -> str:
    """Markdown → Confluence storage XHTML (headings, tables, code, lists)."""
    lines = md_text.split("\n")
    html: list = []
    i = 0
    in_list = None
    para: list = []

    def flush_para():
        nonlocal para
        if para:
            html.append("<p>" + inline(" ".join(para)) + "</p>")
            para = []

    def close_list():
        nonlocal in_list
        if in_list:
            html.append(f"</{in_list}>")
            in_list = None

    while i < len(lines):
        line = lines[i]

        if line.strip().startswith("```"):
            flush_para(); close_list()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            html.append(code_macro("\n".join(code_lines)))
            i += 1
            continue

        if line.strip().startswith("|") and i + 1 < len(lines) and \
                re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            flush_para(); close_list()
            headers = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            t = ["<table><tbody><tr>"]
            t.extend(f"<th>{inline(h)}</th>" for h in headers)
            t.append("</tr>")
            for row in rows:
                t.append("<tr>")
                t.extend(f"<td>{inline(c)}</td>" for c in row)
                t.append("</tr>")
            t.append("</tbody></table>")
            html.append("".join(t))
            continue

        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush_para(); close_list()
            level = min(len(m.group(1)) + 1, 6)
            html.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            i += 1
            continue

        if re.match(r"^---+\s*$", line):
            flush_para(); close_list()
            html.append("<hr/>")
            i += 1
            continue

        if line.startswith("> "):
            flush_para(); close_list()
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i].lstrip("> "))
                i += 1
            html.append("<blockquote><p>" + inline(" ".join(quote)) + "</p></blockquote>")
            continue

        m_ul = re.match(r"^\s*[-*]\s+(.*)$", line)
        m_ol = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if m_ul or m_ol:
            flush_para()
            want = "ul" if m_ul else "ol"
            if in_list != want:
                close_list()
                html.append(f"<{want}>")
                in_list = want
            html.append(f"<li>{inline((m_ul or m_ol).group(1))}</li>")
            i += 1
            continue

        if not line.strip():
            flush_para(); close_list()
            i += 1
            continue

        para.append(line.strip())
        i += 1

    flush_para(); close_list()
    return "\n".join(html)


def existing_children() -> dict:
    """{title: page} for the parent's children (single page, 50 max)."""
    data = _request("GET", f"/api/v2/pages/{PARENT_ID}/children?limit=50&body-format=storage")
    if not data:
        return {}
    return {p["title"]: p for p in data.get("results", [])}


def get_sync_label(page_id: str):
    """The stargate-sync-<hash> label on a page, if any. Labels are stable
    metadata — Confluence strips HTML comments but preserves labels."""
    data = _request("GET", f"/rest/api/content/{page_id}?expand=metadata.labels")
    if not data:
        return None
    for label in (data.get("metadata", {}).get("labels", {}).get("results", [])):
        name = label.get("name", "")
        if name.startswith("stargate-sync-"):
            return name[len("stargate-sync-"):]
    return None


def set_sync_label(page_id: str, new_hash: str):
    """Replace the sync label (best-effort; failure is non-fatal)."""
    old = get_sync_label(page_id)
    if old:
        _request("DELETE", f"/rest/api/content/{page_id}/label/stargate-sync-{old}")
    _request("POST", f"/rest/api/content/{page_id}/label",
             [{"prefix": "global", "name": f"stargate-sync-{new_hash}"}])


def main():
    check_only = "--check" in sys.argv
    docs_dir = Path(__file__).parent.parent / "docs"
    children = existing_children()
    created = updated = unchanged = 0

    def sync_one(title: str, body: str, source_hash: str, footer_note: str):
        nonlocal created, updated, unchanged
        existing = children.get(title)
        if existing is None:
            if check_only:
                print(f"  DRIFT: {title} — missing on Confluence")
                return
            page = _request("POST", "/api/v2/pages", {
                "spaceId": SPACE_ID, "status": "current", "title": title,
                "parentId": PARENT_ID,
                "body": {"representation": "storage", "value": body},
            })
            if page:
                set_sync_label(page["id"], source_hash)
                print(f"  created: {title}")
                created += 1
            return

        full = _request("GET", f"/api/v2/pages/{existing['id']}?body-format=storage")
        if not full:
            print(f"  ERROR: could not fetch existing page for {title}")
            return
        current_hash = get_sync_label(existing["id"])
        if current_hash == source_hash:
            unchanged += 1
            return
        if check_only:
            print(f"  DRIFT: {title} — content changed in repo")
            return
        result = _request("PUT", f"/api/v2/pages/{existing['id']}", {
            "id": existing["id"], "status": "current", "title": title,
            "body": {"representation": "storage", "value": body},
            "version": {"number": full["version"]["number"] + 1,
                        "message": f"sync: {footer_note}"},
        })
        if result:
            set_sync_label(existing["id"], source_hash)
            print(f"  updated: {title} → v{result['version']['number']}")
            updated += 1

    for filename, title in DOCS:
        path = docs_dir / filename
        if not path.exists():
            print(f"  SKIP {filename} (missing)")
            continue
        md_source = path.read_text()
        source_hash = __import__("hashlib").sha256(md_source.encode()).hexdigest()[:16]
        body = convert(md_source) + (
            f'<hr/><p><em>Mirrored from <a href="{REPO_URL}/blob/main/docs/{filename}">'
            f"docs/{filename}</a> — the repo is the source of truth; edits belong there. "
            "This page refreshes on release (Fridays).</em></p>"
        )
        sync_one(title, body, source_hash, f"from repo docs/{filename}")

    for title, body_fn, hash_fn in GENERATED_DOCS:
        source_hash = hash_fn()
        body = body_fn() + (
            '<hr/><p><em>Generated from the repository at sync time — '
            "failure-classes/*.yaml and git history respectively. The repo is the "
            "source of truth; this page refreshes on release (Fridays).</em></p>"
        )
        sync_one(title, body, source_hash, "generated page refresh")

    action = "would update" if check_only else "synced"
    print(f"\n{action}: {created} created, {updated} updated, {unchanged} unchanged")


if __name__ == "__main__":
    main()
