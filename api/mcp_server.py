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
