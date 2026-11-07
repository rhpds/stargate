"""Fleet-level known-issue rollup over completed investigations.

Ten investigations of ten namespaces that all trace to one Helm chart bug
or one unstable ingress router are ONE issue. This module groups completed
investigations into issues so the platform can say "this is one bug
affecting N workloads" instead of N separate diagnoses nobody acts on.

Buckets:
  - platform       : infra-side cause (router, node, cluster, capacity)
  - platform_self  : StarGate's own evaluator/rubric is the diagnosed fault
  - lab_family     : shared chart/config artifact spanning labs
  - unknown        : anything that does not match a bucket yet

Grouping precedence: self-diagnosed investigations (root cause matches
PLATFORM_SELF_PATTERNS) group first, cross-cluster, by failure class —
our own bugs are ours to fix even when the diagnosis names a chart or
cluster. Artifact groups claim from the remainder (a shared artifact is
the strongest fleet signal); cluster groups see what is left.

Public contract (do not change signatures without updating callers in
api/mcp_server.py and api/routers/dashboard/remediation.py):

    detect_known_issues(db, window_hours=24, min_namespaces=3) -> dict

    Returns:
    {
      "window_hours": int,
      "generated_at": iso8601,
      "issues": [
        {
          "signature": str,          # stable key: failure_class|ref-or-cluster
          "bucket": "platform" | "platform_self" | "lab_family" | "unknown",
          "title": str,              # human one-liner
          "failure_class": str,      # primary class
          "cluster": str | None,     # None when a cross-cluster artifact group
          "artifact_refs": [str],    # top extracted references, capped at 3
          "namespace_count": int,
          "investigation_count": int,
          "investigation_ids": [int],          # capped at 10, newest first
          "representative_investigation_id": int | None,
          "top_root_cause_excerpt": str,       # <= 300 chars
          "remediation_excerpt": str | None,   # <= 300 chars
          "first_seen": iso8601,
          "last_seen": iso8601,
          "verdict_counts": {"ACTIONABLE": int, "TRANSIENT": int, "other": int},
        }
      ],
      "summary": {
        "issues": int,
        "platform": int,
        "platform_self": int,
        "lab_family": int,
        "unknown": int,
        "investigations_covered": int,   # sum of investigation_count
        "namespaces_covered": int,       # sum of distinct namespaces
      },
    }

    upsert_known_issues(db, report) -> dict
    Persists/refreshes rows in the known_issues table (signature upsert);
    preserves manually-set status; returns {"upserted": int, "retired": int}.
    An issue absent from the report for longer than RETIRE_AFTER_HOURS is
    marked status="retired" (never deleted — history matters).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

# Detection defaults; overridable via kwargs / env by callers.
DEFAULT_WINDOW_HOURS = 24
DEFAULT_MIN_NAMESPACES = 3
RETIRE_AFTER_HOURS = 48

# Self-referential phrases: the investigation diagnosed StarGate itself.
PLATFORM_SELF_PATTERNS = (
    "evaluation race",
    "evaluator",
    "rubric",
    "misapplied",
    "false negative",
    "stargate evaluation",
    "scanner",
)

# Infra-side phrases: the cause is the platform the labs run on.
PLATFORM_PATTERNS = (
    "router",
    "ingress",
    "ha proxy",
    "haproxy",
    "node",
    "hypervisor",
    "cluster-level",
    "capacity",
    "memory exhaustion",
    "ceph",
    "storage cluster",
    "worker instability",
    "networkpolicy" ,  # borderline: cluster policy layer
)


# ---------------------------------------------------------------------------
# Private helpers (grouping, extraction, bucketing)
# ---------------------------------------------------------------------------

_MAX_CANDIDATES = 500
_MAX_REFS_PER_INVESTIGATION = 6
_MAX_REFS_PER_ISSUE = 3
_MAX_INVESTIGATION_IDS = 10
_EXCERPT_CHARS = 300

# platform_self first (our own bugs are ours to fix), then platform, then lab_family.
_BUCKET_SORT_ORDER = {"platform_self": 0, "platform": 1, "lab_family": 2, "unknown": 3}
# Refs that look like infra components rather than lab artifacts.
_PLATFORM_REF_WORDS = ("router", "ingress", "node", "virt")

_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_CHART_VERSION_RE = re.compile(r"[a-z][a-z0-9-]*-\d+\.\d+(?:\.\d+)*", re.IGNORECASE)
_HELM_CHART_RE = re.compile(r"helm\.sh/chart[:= ]?\s*([A-Za-z0-9._-]+)", re.IGNORECASE)
_IMAGE_REF_RE = re.compile(r"(?:quay\.io/|docker\.io/)?[A-Za-z0-9._/-]+:[A-Za-z0-9._-]+")
# k8s-style tokens: >= 3 dash-separated alnum segments (pod/deployment names).
_DASHY_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9-])[A-Za-z0-9]+(?:-[A-Za-z0-9]+){2,}(?![A-Za-z0-9])")
# deployment-hash / random suffix segment: 5-10 alnum chars mixing letters and digits.
_HASH_SEGMENT_RE = re.compile(r"^[a-z0-9]{5,10}$")

_NOISE_REFS = frozenset({
    "the", "this", "that", "these", "those", "them", "they", "then",
    "none", "null", "true", "false", "yes", "and", "not", "for",
    "namespace", "cluster", "unknown", "error", "warning", "info",
    "pending", "running", "complete", "failed", "failure", "missing",
    "latest", "image", "pod", "pods", "ready", "cause", "root",
    "yaml", "json", "http", "https", "oc", "kubectl", "helm",
})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_comparable(dt: Optional[datetime]) -> Optional[datetime]:
    """Naive-UTC datetime for comparisons regardless of backend tz handling."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _isoformat(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt is not None else None


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _primary_failure_class(failure_class: Optional[str]) -> str:
    """Primary class of a (possibly comma-joined) multi-class value."""
    if not failure_class:
        return "unknown"
    primary = failure_class.split(",")[0].strip()
    return primary or "unknown"


def _matches_any(text: Optional[str], patterns) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(pattern in lowered for pattern in patterns)


def _is_hash_segment(segment: str) -> bool:
    """True for deployment-hash / random suffixes like 9fdb7676 or 7ksfx."""
    seg = segment.lower()
    if not _HASH_SEGMENT_RE.match(seg):
        return False
    return any(c.isdigit() for c in seg) and any(c.isalpha() for c in seg)


def _strip_pod_suffixes(token: str) -> str:
    """`router-ingress-rhdp-net-9fdb7676-7ksfx` -> `router-ingress-rhdp-net`.

    Only applies to pod-name-shaped tokens (>= 2 dash segments); trailing
    hash-like segments are stripped repeatedly, word-like segments stop it.
    """
    parts = token.split("-")
    if len(parts) < 3:
        return token
    while len(parts) > 1 and _is_hash_segment(parts[-1]):
        parts.pop()
    return "-".join(parts)


def _normalize_ref(raw: Optional[str]) -> Optional[str]:
    """Lowercase/trim a candidate ref and drop noise (words, numbers, dregs)."""
    if not raw or not isinstance(raw, str):
        return None
    ref = raw.strip().strip("`\"'")
    ref = ref.strip("()[]{}.,;:!?")
    ref = ref.strip("/._-:").lower()
    if len(ref) < 4 or ref in _NOISE_REFS:
        return None
    if any(ch.isspace() for ch in ref):
        return None
    if ref.isdigit() or not re.search(r"[a-z0-9]", ref):
        return None
    if "=" in ref:
        return None  # config key=value pairs (PORT=8501) are not artifacts
    return ref


def _is_image_ref(candidate: str) -> bool:
    """Conservative image-ref check: registry paths or version-like tags.

    Skips bare `word:number` prose (restarts:14) and host:port shapes.
    """
    cleaned = candidate.strip().strip("/._-:")
    if "/" in cleaned:
        return True
    name, _, tag = cleaned.partition(":")
    if not name or not tag:
        return False
    if not re.search(r"[A-Za-z]", name):
        return False
    return bool(re.search(r"[A-Za-z.]", tag))


def _extract_artifact_refs(
    root_cause: Optional[str],
    failure_class: Optional[str],
    cluster: Optional[str],
) -> List[str]:
    """Pull artifact references out of a root-cause diagnosis.

    Sources, most reliable first: backticked tokens (with pod-hash suffixes
    normalized away), helm.sh/chart labels, bare chart-version tokens,
    image refs, and bare pod-style tokens with hash suffixes. Refs that just
    restate the failure class or the cluster are skipped — they group nothing.
    """
    text = root_cause or ""
    skip = {t for t in re.split(r"[,\s]+", (failure_class or "").lower()) if t}
    if cluster:
        skip.add(cluster.strip().lower())

    refs: List[str] = []

    def _add(raw: Optional[str]) -> None:
        ref = _normalize_ref(raw)
        if ref is None or ref in skip or ref in refs:
            return
        if len(refs) >= _MAX_REFS_PER_INVESTIGATION:
            return
        refs.append(ref)

    # 1. Backticked tokens — the strongest signal (diagnoses quote resources).
    for raw in _BACKTICK_RE.findall(text):
        if any(ch.isspace() for ch in raw):
            continue  # commands / prose fragments, not a single artifact
        _add(_strip_pod_suffixes(raw))

    # 2. Helm chart labels.
    for raw in _HELM_CHART_RE.findall(text):
        _add(raw)

    # 3. Bare chart-version tokens (zerotouch-1.10.2).
    for raw in _CHART_VERSION_RE.findall(text):
        _add(raw)

    # 4. Image refs (conservative).
    for raw in _IMAGE_REF_RE.findall(text):
        if _is_image_ref(raw):
            _add(raw)

    # 5. Bare pod-style tokens with hash suffixes -> base deployment name.
    for raw in _DASHY_TOKEN_RE.findall(text):
        base = _strip_pod_suffixes(raw)
        if base != raw:
            _add(base)

    return refs


def _self_groups(candidates, primary_fc_by_id, min_namespaces) -> List[Dict[str, Any]]:
    """Groups of investigations that diagnosed StarGate itself.

    These claim members BEFORE artifact and cluster grouping: a root cause
    that says "evaluation race" or "evaluator misapplied" is our bug even
    when it names a chart or a cluster. Cross-cluster by construction —
    our evaluator misbehaving is not cluster-specific.
    """
    by_fc: Dict[str, list] = {}
    for inv in candidates:
        if _matches_any(inv.root_cause, PLATFORM_SELF_PATTERNS):
            by_fc.setdefault(primary_fc_by_id[inv.id], []).append(inv)

    groups: List[Dict[str, Any]] = []
    for fc, members in sorted(by_fc.items()):
        if len({m.lab_code for m in members}) < min_namespaces:
            continue
        groups.append({
            "kind": "self",
            "signature": f"{fc}|self",
            "failure_class": fc,
            "key": "self",
            "members": members,
        })
    return groups


def _artifact_groups(candidates, refs_by_id, primary_fc_by_id, min_namespaces, assigned_ids=None) -> List[Dict[str, Any]]:
    """Groups keyed on (primary failure class, shared artifact ref).

    Greedy: an investigation belongs to at most ONE artifact group — the
    largest qualifying group claims its members first, so counts never
    double across groups.
    """
    pair_members: Dict[tuple, list] = {}
    skip_ids = set(assigned_ids or ())
    for inv in candidates:
        if inv.id in skip_ids:
            continue
        for ref in refs_by_id.get(inv.id, []):
            pair_members.setdefault((primary_fc_by_id[inv.id], ref), []).append(inv)

    qualifying = [
        (fc, ref, members)
        for (fc, ref), members in pair_members.items()
        if len({m.lab_code for m in members}) >= min_namespaces
    ]
    qualifying.sort(key=lambda g: (-len(g[2]), g[0], g[1]))

    groups: List[Dict[str, Any]] = []
    assigned = set()
    for fc, ref, members in qualifying:
        remaining = [m for m in members if m.id not in assigned]
        if len({m.lab_code for m in remaining}) < min_namespaces:
            continue  # drained by larger groups — no longer fleet-level
        assigned.update(m.id for m in remaining)
        groups.append({
            "kind": "artifact",
            "signature": f"{fc}|artifact:{ref}",
            "failure_class": fc,
            "key": ref,
            "members": remaining,
        })
    return groups


def _cluster_groups(candidates, primary_fc_by_id, assigned_ids, min_namespaces) -> List[Dict[str, Any]]:
    """Groups keyed on (primary failure class, cluster) for what is left.

    Qualifies only when the majority of root causes read as infra-side
    (PLATFORM_PATTERNS) — a shared lab misconfig on one cluster is not a
    platform issue.
    """
    by_cluster: Dict[tuple, list] = {}
    for inv in candidates:
        if inv.id in assigned_ids or not inv.cluster:
            continue
        by_cluster.setdefault((primary_fc_by_id[inv.id], inv.cluster), []).append(inv)

    groups: List[Dict[str, Any]] = []
    for (fc, cluster), members in sorted(by_cluster.items()):
        if len({m.lab_code for m in members}) < min_namespaces:
            continue
        platform_hits = sum(1 for m in members if _matches_any(m.root_cause, PLATFORM_PATTERNS))
        if platform_hits * 2 <= len(members):
            continue
        groups.append({
            "kind": "cluster",
            "signature": f"{fc}|cluster:{cluster}",
            "failure_class": fc,
            "key": cluster,
            "members": members,
        })
    return groups


def _confidence_of(inv) -> float:
    td = inv.trust_dimensions if isinstance(inv.trust_dimensions, dict) else {}
    try:
        return float(td.get("confidence"))
    except (TypeError, ValueError):
        return -1.0


def _tool_call_count(inv) -> int:
    return len(inv.tool_calls) if isinstance(inv.tool_calls, list) else 0


def _pick_representative(members):
    """Highest trust confidence; ties break on tool_calls, then newest."""
    if not members:
        return None

    def sort_key(m):
        created = _to_comparable(m.created_at) or datetime.min
        return (_confidence_of(m), _tool_call_count(m), created, m.id or 0)

    return max(members, key=sort_key)


def _build_issue(group: Dict[str, Any], refs_by_id: Dict[int, List[str]]) -> Dict[str, Any]:
    members = group["members"]
    fc = group["failure_class"]
    labs = {m.lab_code for m in members}
    clusters = {m.cluster for m in members if m.cluster}
    total = len(members)

    # Ref frequency across the group; the signature ref is guaranteed max.
    freq: Dict[str, int] = {}
    for m in members:
        for ref in refs_by_id.get(m.id, []):
            freq[ref] = freq.get(ref, 0) + 1
    ranked = [ref for ref, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))]
    if group["kind"] == "artifact":
        top_refs = ([group["key"]] + [r for r in ranked if r != group["key"]])[:_MAX_REFS_PER_ISSUE]
    else:
        top_refs = ranked[:_MAX_REFS_PER_ISSUE]

    # Bucket: platform_self first (our own bugs are ours to fix).
    self_hits = sum(1 for m in members if _matches_any(m.root_cause, PLATFORM_SELF_PATTERNS))
    refs_to_check = set(top_refs) | {group["key"]}
    if self_hits * 2 > total:
        bucket = "platform_self"
    elif group["kind"] == "cluster":
        bucket = "platform"
    elif any(word in ref for ref in refs_to_check for word in _PLATFORM_REF_WORDS):
        bucket = "platform"
    else:
        bucket = "lab_family"

    if group["kind"] == "artifact":
        base_title = f"{fc} across {len(labs)} namespaces — {group['key']}"
    elif group["kind"] == "self":
        base_title = f"{fc} across {len(labs)} namespaces — evaluator/rubric (self-diagnosed)"
    else:
        base_title = f"{fc} on {group['key']}: platform-side pattern"
    title = f"StarGate self-issue: {base_title}" if bucket == "platform_self" else base_title

    # Cross-cluster artifact groups are the artifact's fault, not a cluster's.
    cluster_value = next(iter(clusters)) if len(clusters) == 1 else None

    rep = _pick_representative(members)
    top_root_cause = (rep.root_cause or "")[:_EXCERPT_CHARS] if rep else None
    remediation = None
    if rep and rep.remediation_suggestion:
        remediation = rep.remediation_suggestion[:_EXCERPT_CHARS]

    ordered = sorted(
        members,
        key=lambda m: (_to_comparable(m.created_at) or datetime.min, m.id or 0),
        reverse=True,
    )
    inv_ids = [m.id for m in ordered[:_MAX_INVESTIGATION_IDS]]

    verdict_counts = {"ACTIONABLE": 0, "TRANSIENT": 0, "other": 0}
    for m in members:
        td = m.trust_dimensions if isinstance(m.trust_dimensions, dict) else {}
        verdict = td.get("verdict")
        if verdict == "ACTIONABLE":
            verdict_counts["ACTIONABLE"] += 1
        elif verdict == "TRANSIENT":
            verdict_counts["TRANSIENT"] += 1
        else:
            verdict_counts["other"] += 1

    created_values = [_to_comparable(m.created_at) for m in members if m.created_at]
    first_seen = min(created_values) if created_values else None
    last_seen = max(created_values) if created_values else None

    return {
        "signature": group["signature"],
        "bucket": bucket,
        "title": title,
        "failure_class": fc,
        "cluster": cluster_value,
        "artifact_refs": top_refs,
        "namespace_count": len(labs),
        "investigation_count": total,
        "investigation_ids": inv_ids,
        "representative_investigation_id": rep.id if rep else None,
        "top_root_cause_excerpt": top_root_cause,
        "remediation_excerpt": remediation,
        "first_seen": _isoformat(first_seen),
        "last_seen": _isoformat(last_seen),
        "verdict_counts": verdict_counts,
    }


def _empty_report(window_hours: int) -> Dict[str, Any]:
    return {
        "window_hours": window_hours,
        "generated_at": None,
        "issues": [],
        "summary": {
            "issues": 0,
            "platform": 0,
            "platform_self": 0,
            "lab_family": 0,
            "unknown": 0,
            "investigations_covered": 0,
            "namespaces_covered": 0,
        },
    }


def detect_known_issues(
    db, window_hours: int = DEFAULT_WINDOW_HOURS, min_namespaces: int = DEFAULT_MIN_NAMESPACES
) -> Dict[str, Any]:
    """Group completed investigations into fleet-level issues.

    Pure read: no writes, no side effects. See module docstring for the
    exact return contract.
    """
    from db.models import InvestigationRecord

    report = _empty_report(window_hours)
    report["generated_at"] = _isoformat(_utcnow())

    now = _utcnow()
    cutoff = now - timedelta(hours=window_hours)
    rows = (
        db.query(InvestigationRecord)
        .filter(
            InvestigationRecord.status == "complete",
            InvestigationRecord.root_cause.isnot(None),
            InvestigationRecord.created_at >= cutoff,
        )
        .order_by(InvestigationRecord.created_at.desc(), InvestigationRecord.id.desc())
        .limit(_MAX_CANDIDATES)
        .all()
    )
    candidates = [r for r in rows if (r.root_cause or "").strip()]
    if not candidates:
        return report

    refs_by_id: Dict[int, List[str]] = {}
    primary_fc_by_id: Dict[int, str] = {}
    for inv in candidates:
        refs_by_id[inv.id] = _extract_artifact_refs(inv.root_cause, inv.failure_class, inv.cluster)
        primary_fc_by_id[inv.id] = _primary_failure_class(inv.failure_class)

    # Self-diagnosed issues claim members first: a root cause that blames
    # our own evaluator/rubric is our bug even when it names a chart or
    # cluster. Artifact groups then claim from what remains (a shared
    # artifact beats a shared cluster), and cluster groups see the rest.
    groups = _self_groups(candidates, primary_fc_by_id, min_namespaces)
    assigned_ids = {m.id for g in groups for m in g["members"]}
    groups.extend(_artifact_groups(candidates, refs_by_id, primary_fc_by_id, min_namespaces, assigned_ids))
    assigned_ids |= {m.id for g in groups for m in g["members"]}
    groups.extend(_cluster_groups(candidates, primary_fc_by_id, assigned_ids, min_namespaces))

    issues = [_build_issue(g, refs_by_id) for g in groups]
    issues.sort(
        key=lambda i: (
            _BUCKET_SORT_ORDER.get(i["bucket"], 99),
            -i["investigation_count"],
            i["signature"],
        )
    )
    report["issues"] = issues

    summary = report["summary"]
    summary["issues"] = len(issues)
    for issue in issues:
        if issue["bucket"] in summary:
            summary[issue["bucket"]] += 1
    summary["investigations_covered"] = sum(i["investigation_count"] for i in issues)
    summary["namespaces_covered"] = sum(i["namespace_count"] for i in issues)
    return report


def upsert_known_issues(db, report: Dict[str, Any]) -> Dict[str, int]:
    """Persist a detect_known_issues report into the known_issues table.

    Upsert on signature: refresh counts/excerpts/first_seen/last_seen,
    keep a manually-set status unless the issue re-appears (re-open).
    Issues absent from the report beyond RETIRE_AFTER_HOURS get
    status="retired". Returns {"upserted": n, "retired": n}.
    """
    from db.models import KnownIssue

    now = _utcnow()
    upserted = 0
    retired = 0
    seen_rows: Dict[str, Any] = {}

    for issue in (report or {}).get("issues", []):
        signature = issue.get("signature")
        if not signature:
            continue
        first_seen = _parse_dt(issue.get("first_seen"))
        last_seen = _parse_dt(issue.get("last_seen"))

        row = seen_rows.get(signature)
        if row is None:
            row = db.query(KnownIssue).filter(KnownIssue.signature == signature).first()
        if row is None:
            row = KnownIssue(
                signature=signature,
                status="open",
                created_at=now,
                first_seen=first_seen,
            )
            db.add(row)
        elif row.status == "retired":
            # The issue reappeared — re-open it.
            row.status = "open"
        # Any other existing status (mitigated, manual) is never overwritten.
        seen_rows[signature] = row

        row.bucket = issue.get("bucket") or "unknown"
        row.title = (issue.get("title") or signature)[:500]
        row.failure_class = issue.get("failure_class")
        row.cluster = issue.get("cluster")
        row.artifact_refs = issue.get("artifact_refs") or []
        row.namespace_count = int(issue.get("namespace_count") or 0)
        row.investigation_count = int(issue.get("investigation_count") or 0)
        row.investigation_ids = issue.get("investigation_ids") or []
        row.representative_investigation_id = issue.get("representative_investigation_id")
        row.top_root_cause_excerpt = issue.get("top_root_cause_excerpt")
        row.remediation_excerpt = issue.get("remediation_excerpt")
        if first_seen is not None and row.first_seen is None:
            row.first_seen = first_seen  # keep the original otherwise
        row.last_seen = last_seen
        row.updated_at = now
        upserted += 1

    db.flush()

    # Retire stale open issues that this report no longer detects.
    retire_cutoff = _to_comparable(now - timedelta(hours=RETIRE_AFTER_HOURS))
    reported_signatures = set(seen_rows)
    for row in db.query(KnownIssue).filter(KnownIssue.status == "open").all():
        if row.signature in reported_signatures:
            continue
        row_last = _to_comparable(row.last_seen)
        if row_last is not None and row_last < retire_cutoff:
            row.status = "retired"
            row.updated_at = now
            retired += 1

    db.commit()
    return {"upserted": upserted, "retired": retired}
