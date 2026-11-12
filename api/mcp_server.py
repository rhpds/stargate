"""StarGate MCP server — read-only platform intelligence for any agent.

Exposes the platform's query surfaces as MCP tools over Streamable HTTP at
/mcp (stateless, so any replica can serve any request):

- query_lifecycle_outcomes / list_reclamation_artifacts: provisioning and
  reclamation outcome episodes and left-over artifacts
- get_causal_chain: the smoking-gun assembly (symptom -> evidence ->
  diagnosis -> action -> remediation -> verification eval)
- query_evaluations: evaluation history per workload
- get_failure_classes: the classification taxonomy (wire format)
- get_proof_matrix: proof-lab state (gates, proven counts)
- get_recent_episodes: recent lifecycle episodes
- get_known_issues: fleet-level rollup — investigations sharing one
  root cause, bucketed platform / platform_self / lab_family

Read-only: no remediation, no execution, no mutation. Authentication is the
platform API key (X-API-Key), enforced by the app middleware on /mcp paths.
"""

from __future__ import annotations

import json
from typing import Optional

from mcp.server.mcpserver import MCPServer

mcp = MCPServer(
    name="stargate",
    title="StarGate Platform Intelligence",
    description=(
        "Read-only lifecycle, classification, investigation, and proof-lab "
        "intelligence for the Red Hat Demo Platform. Query provisioning and "
        "reclamation outcomes, causal chains, the failure taxonomy, and the "
        "proof lab. No remediation authority."
    ),
)


def _db():
    from db.database import get_session_factory
    return get_session_factory()()


@mcp.tool()
def ask(question: str) -> str:
    """Ask any question about the platform in natural language: lab health,
    failures, provisioning and reclamation outcomes, the failure taxonomy,
    remediation guidance, the proof lab. Answers are grounded in live
    platform data and the knowledge corpus, with cited sources; says when
    it does not know. Example: 'did sandbox-abc123 get reclaimed and did
    anything leak?' or 'what does teardown_stuck mean and how is it fixed?'
    """
    from engine.stargate_qa import ask_stargate
    return ask_stargate(question)


def _proof_matrix_summary() -> str:
    """Shared helper: one-line proof-lab summary for QA context."""
    import os
    state_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "scan-history", "proof-matrix.json"
    )
    try:
        with open(state_path) as handle:
            data = json.load(handle)
        summary = data.get("summary") or {}
        return f"Proof lab: {summary.get('total', '?')} classes, {summary.get('proven', 0)} proven ({summary.get('proven_remediation', 0)} remediation, {summary.get('proven_detection', 0)} detection), {summary.get('failed', 0)} failed."
    except Exception:
        return "Proof lab summary unavailable."


@mcp.tool()
def query_lifecycle_outcomes(namespace: str, days: int = 14) -> str:
    """Provision/reclamation outcome episodes for a workload.

    Returns the lifecycle episodes recorded for the namespace's lab:
    provisioning successes/failures, reclamation completions, failed or
    stuck teardowns, leaked resources — with interpretation guidance.
    A PASS destroy-complete episode means reclaimed; a FAIL one is the
    finding.
    """
    from engine.investigation_agent import tool_query_lifecycle_outcomes
    return tool_query_lifecycle_outcomes(namespace, days)


@mcp.tool()
def list_reclamation_artifacts(namespace: str, cluster: str = "") -> str:
    """Left-over artifacts for a tearing-down or reclaimed workload.

    Namespace existence, PVs still bound to it (leaked capacity), sandbox
    placement state, reclamation episodes, and concrete reclamation targets.
    Read-only oc queries against the workload cluster.
    """
    from engine.investigation_agent import tool_list_reclamation_artifacts
    return tool_list_reclamation_artifacts(namespace, cluster)


@mcp.tool()
def get_causal_chain(investigation_id: Optional[int] = None, namespace: Optional[str] = None) -> str:
    """The causal chain for an investigation: symptom eval -> collected
    evidence -> diagnosis -> adjudication -> action -> remediation ->
    verification eval. chain_complete only when the verification eval
    passed; missing_legs reports what is not yet proven. Provide
    investigation_id or namespace (latest for the namespace).
    """
    from db.repository import build_causal_chain
    if investigation_id is None and not namespace:
        return "ERROR: provide investigation_id or namespace"
    db = _db()
    try:
        chain = build_causal_chain(db, investigation_id=investigation_id, namespace=namespace)
        return json.dumps(chain, default=str)[:20000]
    finally:
        db.close()


@mcp.tool()
def query_evaluations(namespace: str, limit: int = 10) -> str:
    """Recent evaluation history for a workload (outcome, failure class,
    message, timestamp)."""
    from engine.investigation_agent import tool_query_evaluations
    return tool_query_evaluations(namespace, limit)


@mcp.tool()
def get_failure_classes() -> str:
    """The failure-classification taxonomy (wire format): every class with
    its patterns, severity, source catalog, and category."""
    from engine.failure_class_loader import get_all_classes
    from contracts.failure_class_schema import normalize_raw_class
    classes = [normalize_raw_class(c) for c in get_all_classes()]
    # Compact serialization; never truncate mid-JSON.
    return json.dumps(classes, default=str, separators=(",", ":"))


@mcp.tool()
def review_diagnosis(investigation_id: int, approved: bool, notes: str = "") -> str:
    """Review a diagnosis: record your agreement or disagreement. This is an
    opinion only — it does NOT execute anything, touch any cluster, or
    trigger remediation. Approved diagnoses with a root cause and
    remediation suggestion are published to the knowledge base (versioned,
    attributed to you) so future investigations benefit from what you've
    confirmed. Rejected diagnoses are marked for re-examination.

    Provide the investigation_id (from query_evaluations, get_causal_chain,
    or ask), whether you approve (true/false), and optional notes explaining
    your reasoning.
    """
    import hashlib
    from datetime import datetime, timezone
    from db.database import get_session_factory
    from db.models import InvestigationRecord, KnowledgeEntry

    db = _db()
    _owns_session = True
    try:
        inv = db.query(InvestigationRecord).filter(
            InvestigationRecord.id == investigation_id).first()
        if not inv:
            return f"ERROR: investigation {investigation_id} not found"

        # Idempotent: skip if already reviewed AND published
        if inv.review_state == "reviewed":
            existing = db.query(KnowledgeEntry).filter(
                KnowledgeEntry.investigation_id == investigation_id,
                KnowledgeEntry.active == True,
            ).first()
            if existing:
                return (
                    f"Investigation {investigation_id} already reviewed and published "
                    f"as knowledge entry v{existing.version} by {existing.reviewed_by}. "
                    f"No changes made."
                )

        # Record the review on the investigation
        inv.review_state = "reviewed" if approved else "rejected"
        inv.reviewed_at = datetime.now(timezone.utc)
        reviewer_id = "mcp:" + hashlib.sha256(
            __import__("os").environ.get("_MCP_CALLER_KEY", "unknown").encode()
        ).hexdigest()[:8]

        result_parts = [f"Review recorded for investigation {investigation_id}: {'APPROVED' if approved else 'REJECTED'}"]

        # If approved and we have a diagnosis, publish to the knowledge base
        if approved and inv.root_cause and inv.remediation_suggestion:
            signature = f"{inv.lab_code}:{inv.failure_class}".lower()
            prior = db.query(KnowledgeEntry).filter_by(
                signature=signature, active=True
            ).order_by(KnowledgeEntry.version.desc()).first()
            version = (prior.version + 1) if prior else 1
            now = datetime.now(timezone.utc)
            if prior:
                prior.active = False
                prior.retired_at = now
            entry = KnowledgeEntry(
                signature=signature, version=version, active=True,
                root_cause=inv.root_cause,
                remediation=inv.remediation_suggestion,
                metadata_json={"lab_code": inv.lab_code, "failure_class": inv.failure_class,
                              "review_notes": notes[:500] if notes else None},
                provenance={"investigation_id": inv.id, "job_id": inv.job_id,
                           "evidence_hash": inv.evidence_hash},
                confidence=(inv.trust_dimensions or {}).get("confidence"),
                investigation_id=inv.id,
                reviewed_by=reviewer_id, reviewed_at=now,
            )
            db.add(entry)
            result_parts.append(
                f"Published to knowledge base as {signature} v{version}. "
                f"Future investigations for this failure class will reference this diagnosis."
            )
        elif approved:
            result_parts.append(
                "NOTE: this investigation has no root_cause/remediation_suggestion, "
                "so nothing was published to the knowledge base. The review is recorded."
            )
        else:
            result_parts.append(
                "Marked as rejected. This diagnosis will not be used as reference knowledge."
            )

        if notes:
            result_parts.append(f"Notes: {notes[:200]}")

        db.commit()
        return " | ".join(result_parts)
    except Exception as error:
        db.rollback()
        return f"ERROR reviewing diagnosis: {str(error)[:200]}"


@mcp.tool()
def comment_action(action_id: int, comment: str) -> str:
    """Add a comment to a pending remediation action. Your comment is
    visible to whoever reviews or approves the action in the dashboard.
    This does NOT approve, reject, or execute anything — it's context
    for the human approver.

    Provide the action_id (from get_causal_chain or ask) and your comment.
    """
    from datetime import datetime, timezone
    from db.database import get_session_factory
    from db.models import PendingAction

    if not comment or not comment.strip():
        return "ERROR: comment cannot be empty"

    db = _db()
    try:
        action = db.query(PendingAction).filter(PendingAction.id == action_id).first()
        if not action:
            return f"ERROR: action {action_id} not found"

        params = dict(action.parameters or {})
        comments = params.get("reviewer_comments", [])
        comments.append({
            "comment": comment.strip()[:500],
            "at": datetime.now(timezone.utc).isoformat(),
            "via": "mcp",
        })
        params["reviewer_comments"] = comments
        action.parameters = params
        db.commit()

        return (
            f"Comment added to action {action_id} ({action.action_type} → {action.target}). "
            f"The approver will see it when reviewing this action. "
            f"This does NOT approve or execute anything."
        )
    except Exception as error:
        db.rollback()
        return f"ERROR adding comment: {str(error)[:200]}"


@mcp.tool()
def get_proof_matrix() -> str:
    """Proof-lab state: per failure class — status, cycles, consecutive
    passes, gate (full_auto = remediation-proven, investigation_proven =
    detection-proven), last run — plus the summary by accumulated proof."""
    import os
    state_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "scan-history", "proof-matrix.json"
    )
    try:
        with open(state_path) as handle:
            return handle.read()[:30000]
    except FileNotFoundError:
        return "No proof matrix recorded yet."
    except Exception as error:
        return f"ERROR reading proof matrix: {str(error)[:200]}"


@mcp.tool()
def get_recent_episodes(hours: int = 24, stage: Optional[str] = None) -> str:
    """Recent lifecycle episodes (gap-% run_ids): provisioning and
    reclamation outcomes with stage, outcome, failure class, and message.
    Optionally filter by stage (provisioning, destroy-complete,
    cluster-health)."""
    from datetime import datetime, timedelta, timezone
    from db.models import EvaluationRecord
    db = _db()
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=min(max(hours, 1), 168))
        query = db.query(EvaluationRecord).filter(
            EvaluationRecord.run_id.like("gap-%"),
            EvaluationRecord.evaluated_at > since,
        )
        if stage:
            query = query.filter(EvaluationRecord.stage_id == stage)
        rows = query.order_by(EvaluationRecord.evaluated_at.desc()).limit(50).all()
        if not rows:
            return f"No lifecycle episodes in the last {hours}h" + (f" for stage {stage}" if stage else "")
        lines = [f"Recent lifecycle episodes (last {hours}h{', stage ' + stage if stage else ''}):"]
        for row in rows:
            lines.append(
                f"  {row.stage_id} | {row.outcome} | {row.failure_class or 'reclaimed'} | "
                f"{(row.message or '')[:120]} | {row.evaluated_at}"
            )
        return "\n".join(lines)
    finally:
        db.close()


@mcp.tool()
def get_cluster_saturation(window_hours: int = 6) -> str:
    """Cluster capacity saturation status: which clusters show the
    saturation signature (failure-rate spike vs own baseline + diverse
    symptom classes + labs failing here while passing elsewhere).
    Returns per-cluster signals, severity, confidence, top failure
    classes, divergent labs, and the remediation guidance."""
    from engine.cluster_saturation import detect_cluster_saturation
    db = _db()
    try:
        report = detect_cluster_saturation(db, window_hours=min(max(window_hours, 1), 72))
        lines = [
            f"Cluster saturation report (window: last {report['window']['hours']}h, "
            f"baseline: {report['baseline_days']}d, clusters analyzed: {report['clusters_analyzed']}):"
        ]
        if not report["saturated_clusters"]:
            lines.append("  No clusters currently show the saturation signature.")
        for c in report["saturated_clusters"]:
            entry = next(x for x in report["clusters"] if x["cluster"] == c)
            rs = entry["signals"]["rate_spike"]
            sd = entry["signals"]["symptom_diversity"]
            ld = entry["signals"]["lab_differential"]
            lines.append(f"  {c}: {entry['severity']} (confidence {entry['confidence']})")
            lines.append(
                f"    failure rate {rs['window_rate']:.1%} vs {rs['baseline_rate']:.1%} baseline "
                f"({rs['rate_multiplier_observed']}x, {rs['window_fails']} fails)"
            )
            lines.append(
                f"    {sd['distinct_failure_classes']} distinct failure classes; top: "
                + ", ".join(f"{t['class']} ({t['count']})" for t in sd["top_classes"][:5])
            )
            lines.append(
                f"    {ld['divergent_lab_count']} labs failing here while passing elsewhere: "
                + ", ".join(d["lab"] for d in ld["divergent_labs"][:5])
            )
            lines.append(f"    {entry.get('interpretation', '')}")
        lines.append(
            "  Remediation for saturated clusters: check node memory and NotReady status; "
            "if confirmed, disable the cluster in the catalog and let the queue drain. "
            "Do not chase individual symptom failures — they share one cause."
        )
        return "\n".join(lines)
    finally:
        db.close()


@mcp.tool()
def get_known_issues(window_hours: int = 24, bucket: str = "") -> str:
    """Fleet-level known-issue rollup: completed investigations that share
    one root cause, grouped into issues bucketed by who owns the fix —
    platform (infra-side: router, node, cluster, capacity), platform_self
    (StarGate's own evaluator/rubric at fault), or lab_family (a shared
    chart/config bug spanning labs). Says "one bug affecting N workloads"
    instead of N separate diagnoses. Per issue: signature, scope
    (investigations, namespaces, cluster), root-cause and remediation
    excerpts, and a representative investigation id — call
    get_causal_chain on it for the full evidence chain."""
    from engine.known_issues import detect_known_issues

    window_hours = min(max(window_hours, 1), 168)
    bucket = (bucket or "").strip()
    valid_buckets = ("platform", "platform_self", "lab_family", "unknown")
    if bucket and bucket not in valid_buckets:
        return (
            "ERROR: bucket must be one of "
            + ", ".join(valid_buckets) + " (or empty for all)"
        )

    db = _db()
    try:
        report = detect_known_issues(db, window_hours=window_hours)
        issues = [
            i for i in (report.get("issues") or [])
            if not bucket or i.get("bucket") == bucket
        ]

        if not issues:
            scope = f" in bucket {bucket}" if bucket else ""
            return (
                f"No known issues in the last {window_hours}h{scope} — no failure "
                f"class spans 3+ namespaces with a shared root cause."
            )

        summary = report.get("summary") or {}
        if bucket:
            covered_inv = sum(i.get("investigation_count", 0) for i in issues)
            covered_ns = sum(i.get("namespace_count", 0) for i in issues)
        else:
            covered_inv = summary.get("investigations_covered", 0)
            covered_ns = summary.get("namespaces_covered", 0)

        def _ts(value):
            text = str(value or "?")
            return text[:-6] + "Z" if text.endswith("+00:00") else text

        def _count(value, noun):
            return f"{value} {noun}" + ("" if value == 1 else "s")

        lines = [
            f"Known issues (last {report.get('window_hours', window_hours)}h"
            + (f", bucket {bucket}" if bucket else "")
            + f"): {_count(len(issues), 'issue')} covering "
            + f"{_count(covered_inv, 'investigation')} across "
            + f"{_count(covered_ns, 'namespace')}"
        ]
        if not bucket:
            parts = [f"{summary.get(b, 0)} {b}" for b in valid_buckets if summary.get(b, 0)]
            if parts:
                lines.append("  Buckets: " + ", ".join(parts))

        for issue in issues:
            lines.append("")
            lines.append(f"  [{issue.get('bucket')}] {issue.get('title')}")
            lines.append(f"    signature: {issue.get('signature')}")
            scope_line = (
                f"{_count(issue.get('investigation_count', 0), 'investigation')} across "
                f"{_count(issue.get('namespace_count', 0), 'namespace')}"
            )
            if issue.get("cluster"):
                scope_line += f" on {issue['cluster']}"
            lines.append(
                f"    {scope_line}, first seen {_ts(issue.get('first_seen'))}, "
                f"last seen {_ts(issue.get('last_seen'))}"
            )
            refs = [
                r for r in (issue.get("artifact_refs") or [])
                if r and r not in str(issue.get("signature") or "")
            ]
            if refs:
                lines.append(f"    artifacts: {', '.join(refs)}")
            if issue.get("top_root_cause_excerpt"):
                lines.append(f"    root cause: {issue['top_root_cause_excerpt']}")
            if issue.get("remediation_excerpt"):
                lines.append(f"    remediation: {issue['remediation_excerpt']}")
            rep = issue.get("representative_investigation_id")
            if rep:
                lines.append(
                    f"    representative investigation: #{rep} "
                    f"(get_causal_chain(investigation_id={rep}) for the full chain)"
                )

        lines.append("")
        lines.append(
            "  Guidance: platform_self issues are StarGate bugs — file them in "
            "the stargate repo. platform issues are infra-side — check the named "
            "component on the named cluster. lab_family issues are chart/config "
            "bugs — one fix eliminates the whole class. Use "
            "get_causal_chain(investigation_id=...) for any issue's full "
            "evidence chain."
        )
        return "\n".join(lines)
    finally:
        db.close()


@mcp.tool()
def get_recent_changes(lab_code: Optional[str] = None, lookback_hours: int = 72) -> str:
    """Changes that could explain current or recent failures: GitHub PRs
    merged in the platform repos (agnosticv, agnosticd) and recently
    updated Jira tickets (RHDPOPS, GPTEINFRA). With lab_code, correlates
    against that lab's failure onset: PRs touching its AgnosticV files and
    tickets mentioning it, with resolved-in-window (the fix) annotated.
    RHDP has no formal change management — this IS the change record."""
    from engine.github_changes import list_recent_changes, correlate_changes_for_lab
    from engine.jira_changes import list_recent_incidents, correlate_issues_for_lab

    if lab_code:
        db = _db()
        try:
            prs = correlate_changes_for_lab(db, lab_code, lookback_hours=lookback_hours)
            issues = correlate_issues_for_lab(db, lab_code, lookback_hours=max(lookback_hours * 2, 168))
        finally:
            db.close()
        lines = [f"Change correlation for {lab_code} (onset: {prs.get('onset', 'unknown')}):"]
        if prs.get("changes"):
            lines.append(f"  GitHub PRs in window ({prs['prs_merged_in_window']} merged, {prs['lab_specific_changes']} lab-path match, {prs['fleet_wide_changes']} fleet-wide):")
            for pr in prs["changes"][:10]:
                lines.append(f"    [{pr['correlation']}] {pr['repo']}#{pr['number']} — {pr['title'][:70]} (merged {pr['merged_at'][:16]}, {pr['author']})")
        else:
            lines.append(f"  GitHub: {prs.get('note', 'no matches')}")
        if issues.get("issues"):
            lines.append(f"  Jira issues mentioning this lab ({len(issues['issues'])}):")
            for i in issues["issues"][:10]:
                align = "; ".join(i.get("alignment", [])) or "no temporal alignment"
                lines.append(f"    {i['key']} [{i['status']}] {i['summary'][:60]} — {align}")
        else:
            lines.append(f"  Jira: {issues.get('note', 'no matches')}")
        return "\n".join(lines)

    prs = list_recent_changes(hours=lookback_hours)
    incidents = list_recent_incidents(hours=max(lookback_hours, 168))
    lines = [f"Recent changes (last {lookback_hours}h PRs, 7d tickets):"]
    lines.append(f"  GitHub ({prs['count']} merged PRs):")
    for pr in prs["merged_prs"][:15]:
        lines.append(f"    {pr['repo']}#{pr['number']} — {pr['title'][:70]} (merged {pr['merged_at'][:16]}, {pr['author']})")
    lines.append(f"  Jira ({incidents['count']} recently updated):")
    for i in incidents["issues"][:15]:
        lines.append(f"    {i['key']} [{i['status']}] {i['summary'][:65]}")
    if not incidents.get("issues") and incidents.get("count", 0) == 0:
        lines.append("    (Jira credentials not configured or search failed — set STARGATE_JIRA_EMAIL/STARGATE_JIRA_TOKEN)")
    return "\n".join(lines)


@mcp.tool()
def get_capacity_forecast(hours: int = 24) -> str:
    """Advisory capacity forecast (capacity-forecast/v1): projected per-hour
    resource demand — VM slots and AI cores/GiB — from the upcoming session
    schedule and catalog resource profiles. Coverage is tri-state: labs
    without parsed resource profiles contribute unquantified demand, so
    observed demand is a lower bound. Risk follows the contract rubric and
    is at most amber while supply evidence is unwired."""
    from api.routers import capacity as capacity_router
    from contracts.capacity_forecast import build_capacity_forecast
    from engine.capacity_projector import project_resource_demand

    hours = min(max(hours, 1), 72)
    sessions = capacity_router._upcoming_sessions(hours)
    profiles = capacity_router._resource_profiles()
    supply = capacity_router.fleet_supply_vm_slots(window_hours=48)
    projection = project_resource_demand(sessions, profiles, hours=hours)
    forecast = build_capacity_forecast(
        projection,
        supply_vm_slots=(supply or {}).get("vm_slots"),
        window_hours=hours,
    )

    coverage = forecast.get("coverage", {})
    lines = [
        f"Capacity forecast (advisory, {forecast['contract']}), next {hours}h:",
        f"Risk: {forecast['risk'].value}",
    ]

    if not sessions:
        lines.append("No sessions scheduled in the window (demand unobserved).")
    else:
        lines.append(
            "Sessions: %d scheduled, %d with resource profiles, %d fallback"
            % (coverage.get("sessions_total", 0),
               coverage.get("sessions_with_profiles", 0),
               coverage.get("sessions_fallback", 0))
        )
        if coverage.get("sessions_fallback"):
            lines.append(
                "Demand is a LOWER BOUND: %d session(s) belong to labs without "
                "parsed resource profiles." % coverage.get("sessions_fallback"))

    peak = forecast.get("peak_hour")
    if peak and peak.get("vm_slots") is not None:
        parts = [f"Peak demand: {peak['hour']} — {peak['vm_slots']} VM slots"]
        if peak.get("ai_cores") is not None:
            parts.append(f"{peak['ai_cores']} AI cores")
        if peak.get("ai_memory_gib") is not None:
            parts.append(f"{peak['ai_memory_gib']} GiB AI memory")
        lines.append(", ".join(parts) + " (observed)")

    demanding = [h for h in forecast.get("hourly", []) if h.get("vm_slots")]
    if demanding:
        lines.append("Hours with observed demand:")
        for h in demanding[:12]:
            lines.append("  %s — %s VM slots (%d session(s))"
                         % (h["hour"], h["vm_slots"], h["sessions"]))

    if supply is not None:
        lines.append(
            "Supply: %s VM slots (observed peak density, %sh window) — deficits "
            "against it are early warnings, not hard walls."
            % (supply["vm_slots"], supply["window_hours"]))
    else:
        lines.append(
            "Supply evidence is not yet wired: hours resolve INDETERMINATE and "
            "risk cannot be green. Treat demand as a floor, not a ceiling.")
    return "\n".join(lines)
