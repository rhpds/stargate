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
