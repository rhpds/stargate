"""Advisory-only admission checks. No collectors, models, claims, or executor."""
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool

Name = Annotated[str, Field(strict=True, min_length=1, max_length=253, pattern=r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")]
Identity = Annotated[str, Field(strict=True, min_length=1, max_length=253)]
Count = Annotated[int, Field(strict=True, ge=0)]


class PilotPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    cluster: Literal["infra01"] = "infra01"
    server: Annotated[str, Field(strict=True, pattern=r"^https://[a-zA-Z0-9.-]+:6443$")]
    cluster_uid: Identity
    namespace: Literal["stargate-test"] = "stargate-test"
    namespace_uid: Identity
    deployment: Name
    deployment_uid: Identity
    owner: Identity


class PilotEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    cluster: str
    server: str
    cluster_uid: str
    namespace: str
    namespace_uid: str
    deployment: str
    deployment_uid: str
    pod: str
    pod_uid: str
    controller_deployment_uid: str
    observed_at: AwareDatetime
    evidence_refs: list[Identity] = Field(default_factory=list, max_length=32)
    reviewer: str = ""
    condition: str = "unknown"
    restart_supported: StrictBool = False
    consecutive_failed_probes: Count = 0
    failure_duration_seconds: Count = 0
    desired_replicas: Count = 0
    ready_other_replicas: Count = 0
    pdb_disruptions_allowed: Optional[Count] = None
    stateless: StrictBool = False
    persistent_storage_attached: Optional[StrictBool] = None
    pod_ready: Optional[StrictBool] = None
    dependencies_healthy: StrictBool = False
    controller_healthy: StrictBool = False
    confounding_failures: list[Identity] = Field(default_factory=lambda: ["unassessed"], max_length=32)
    rollout_in_progress: Optional[StrictBool] = None
    deletion_in_progress: Optional[StrictBool] = None
    action_history_verified: StrictBool = False
    attempts_for_incident: Count = 0
    seconds_since_last_action: Optional[Count] = None


def assess(evidence: PilotEvidence, policy: Optional[PilotPolicy], *, now=None):
    """Screen supplied assertions for operator review, never authorize execution.

    UID, opt-in, snapshot, PDB and history must eventually come from trusted
    collectors/ledgers and be rechecked after approval. This endpoint cannot
    establish their truth or reserve concurrency/cooldown ownership.
    """
    blockers = []
    if policy is None:
        blockers.append("target_not_opted_in")
    else:
        if (evidence.cluster != policy.cluster or evidence.server != policy.server or evidence.cluster_uid != policy.cluster_uid or
                evidence.namespace != policy.namespace or evidence.namespace_uid != policy.namespace_uid or
                evidence.deployment != policy.deployment or evidence.deployment_uid != policy.deployment_uid):
            blockers.append("target_identity_mismatch")
        if not evidence.controller_deployment_uid or evidence.controller_deployment_uid != policy.deployment_uid:
            blockers.append("controller_identity_mismatch")
        if not evidence.pod.strip() or not evidence.pod_uid.strip():
            blockers.append("pod_identity_missing")
        age = ((now or datetime.now(timezone.utc)) - evidence.observed_at).total_seconds()
        if not -5 <= age <= 120:
            blockers.append("evidence_not_fresh")
        if not evidence.reviewer.strip() or not evidence.evidence_refs:
            blockers.append("review_or_evidence_missing")
        if not evidence.stateless or evidence.persistent_storage_attached is not False:
            blockers.append("stateful_or_storage_attached")
        if evidence.condition != "confirmed_application_deadlock" or not evidence.restart_supported:
            blockers.append("restart_not_justified")
        if evidence.consecutive_failed_probes < 3 or evidence.failure_duration_seconds < 300 or evidence.pod_ready is not False:
            blockers.append("failure_not_persistent")
        if (evidence.desired_replicas < 2 or evidence.ready_other_replicas < max(1, evidence.desired_replicas - 1) or
                evidence.pdb_disruptions_allowed is None or evidence.pdb_disruptions_allowed < 1):
            blockers.append("availability_not_protected")
        if evidence.confounding_failures:
            blockers.append("confounding_failure")
        if not evidence.dependencies_healthy or not evidence.controller_healthy:
            blockers.append("dependency_or_controller_unhealthy")
        if evidence.rollout_in_progress is not False or evidence.deletion_in_progress is not False:
            blockers.append("rollout_or_deletion_in_progress")
        if (not evidence.action_history_verified or evidence.attempts_for_incident != 0 or
                (evidence.seconds_since_last_action is not None and evidence.seconds_since_last_action < 3600)):
            blockers.append("attempt_or_cooldown_limit")
    return {"action": "replace_single_stateless_pod", "status": "blocked" if blockers else "candidate_for_operator_review",
            "blockers": blockers, "execution_authorized": False, "approval_required": True,
            "evidence_trust": "caller_supplied_not_independently_verified",
            "assessment_version": "stateless-pilot-v1", "evidence_refs": evidence.evidence_refs,
            "next_requirements": ["trusted collection and target identity verification", "operator approval bound to evidence and pod UID",
                                  "transactional claim and fresh pre-action safety recheck", "approved fixed action and bounded execution",
                                  "sustained recovery proof, abort handling and audit receipt"]}
