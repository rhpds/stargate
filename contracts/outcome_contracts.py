"""Provisioning and reclamation outcome contracts.

One definition site for the outcome vocabulary of both lifecycle domains.
This exists because the same conceptual outcomes were previously scattered
across collector inline strings, rubric YAMLs, hardcoded Python dicts, and
the remediation catalog — with no single contract binding them.

Contract semantics (shared by both domains):

1. TRI-STATE EVIDENCE. Every evidence key carries True (observed true),
   False (observed false), or None/absent (unobserved). Unobserved is
   never silently coerced to false: it resolves to INDETERMINATE, never
   to a fabricated success or failure. See docs/evidence-observation-semantics.md.

2. EXPLICIT OUTCOMES. Termination alone cannot establish success. Job
   histories count only explicit statuses (successful / failed / error /
   canceled); running, malformed, or mixed histories stay unverified.
   Empty job history is an observed not-succeeded (False), mirroring the
   provision contract in collectors/babylon/collect_anarchy_state.py.

3. FAILURE PRECEDENCE. An observed failure at any level beats an observed
   success elsewhere: a cohort cannot be healthy if its subject's job
   explicitly failed, and a destroy is not reclaimed if its job explicitly
   failed — regardless of what disappeared.

4. COLLECTION HEALTH IS NOT A WORKLOAD OUTCOME. A failed collection is
   COLLECTION_UNAVAILABLE (visible, non-actionable); a successful query
   returning zero items is EMPTY at the collection layer. Neither is ever
   reported as a workload failure, and zero is only healthy when the
   query explicitly succeeded.

Resolution order (both resolvers): collection failure → explicit failure →
controller lag (provisioning only) → stalled → success → indeterminate.
Controller lag precedes stalled because conditions belonging to a previous
generation cannot be trusted to indicate a stall.

Consumers: collectors normalize raw signals into these evidence keys;
rubric stages (rubrics/platform/destroy-complete.yaml) and the gap-detection
layer evaluate them; events and metrics should carry the enum values and
the contract version so downstream systems (DeepField) can version-match.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional, Tuple

PROVISIONING_OUTCOME_CONTRACT_VERSION = "provisioning-outcome/v1"
RECLAMATION_OUTCOME_CONTRACT_VERSION = "reclamation-outcome/v1"


class ProvisionOutcome(str, Enum):
    """Unified provisioning outcome vocabulary.

    FAILED / STALLED / CONTROLLER_LAG / COLLECTION_UNAVAILABLE replace the
    inline ``workshop_provision_*`` strings; SUCCEEDED gives first-class
    standing to observed success (previously only counted, never recorded).
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STALLED = "stalled"
    CONTROLLER_LAG = "controller_lag"
    COLLECTION_UNAVAILABLE = "collection_unavailable"
    EMPTY = "empty"  # collection-layer outcome: successful query, zero provisions
    INDETERMINATE = "indeterminate"


class ReclamationOutcome(str, Enum):
    """Unified reclamation (destroy/teardown) outcome vocabulary.

    RECLAIMED requires observed evidence, never inferred from disappearance
    alone; RESOURCE_LEAK covers reclaimed workloads that leaked resources
    (orphaned PVs); DESTROY_STALLED / DESTROY_FAILED mirror the provision
    stalled/failed semantics for the destroy lifecycle.
    """

    RECLAIMED = "reclaimed"
    DESTROY_FAILED = "destroy_failed"
    DESTROY_STALLED = "destroy_stalled"
    RESOURCE_LEAK = "resource_leak"
    COLLECTION_UNAVAILABLE = "collection_unavailable"
    INDETERMINATE = "indeterminate"


# --- Evidence keys -----------------------------------------------------------
#
# Every key is tri-state: True / False = observed, None or absent = unobserved.
# Collectors produce these keys; the resolvers below are the only place that
# maps them to outcomes.

PROVISION_EVIDENCE_KEYS = (
    # Collection layer health (False → COLLECTION_UNAVAILABLE)
    "collection_ok",
    # WorkshopProvision (cohort authority): a condition with "fail" in the
    # type and status=True; Ready=False/absent plus age ≥ threshold
    # (caller-computed); generation > observedGeneration.
    "workshopprovision_failed_condition",
    "workshopprovision_stalled",
    "controller_lag",
    # AnarchySubject (subject authority): explicit towerJobs provision|start
    # outcome; state == started.
    "provision_job_succeeded",
    "state_is_started",
    # AAP job outcome (job authority) and the provision-complete rubric stage.
    "aap_job_successful",
    "stage_provision_complete_pass",
)

RECLAMATION_EVIDENCE_KEYS = (
    # Collection layer health
    "collection_ok",
    # AnarchySubject: explicit towerJobs destroy|stop outcome; state in
    # destroy-failed/destroy-error; destroying plus age ≥ threshold
    # (caller-computed).
    "destroy_job_succeeded",
    "state_is_destroy_failed",
    "destroy_stalled",
    # Post-destroy observations: subject deleted, namespace deleted, no PVs
    # left bound to the workload namespace, pool placement returned.
    "anarchysubject_gone",
    "namespace_gone",
    "pvs_released",
    "placement_returned",
)


def _observed(evidence: Dict, key: str) -> bool:
    """True only when the key is present and explicitly True."""
    return evidence.get(key) is True


def resolve_provision_outcome(evidence: Dict) -> ProvisionOutcome:
    """Resolve per-provision outcome from tri-state evidence.

    EMPTY is a collection-layer outcome and is never returned here; the
    collection layer emits it when a successful query returns zero items.
    """
    if evidence.get("collection_ok") is False:
        return ProvisionOutcome.COLLECTION_UNAVAILABLE

    # Observed failure at any level wins (failure precedence).
    if (
        _observed(evidence, "workshopprovision_failed_condition")
        or evidence.get("provision_job_succeeded") is False
        or evidence.get("aap_job_successful") is False
        or evidence.get("stage_provision_complete_pass") is False
    ):
        return ProvisionOutcome.FAILED

    # Controller lag precedes stalled: a Ready=False condition from a previous
    # generation cannot be trusted to indicate a stall (matches the babylon
    # worker's tested classification order).
    if _observed(evidence, "controller_lag"):
        return ProvisionOutcome.CONTROLLER_LAG

    if _observed(evidence, "workshopprovision_stalled"):
        return ProvisionOutcome.STALLED
    # Success requires observed positive evidence. Subject-level (Anarchy
    # explicit job outcome + started state) and cohort-level (WorkshopProvision
    # Ready) are each sufficient; AAP job success alone is corroborating only
    # (a successful playbook does not prove the workload started).
    if (
        (_observed(evidence, "provision_job_succeeded") and _observed(evidence, "state_is_started"))
        or _observed(evidence, "workshopprovision_ready")
        or _observed(evidence, "stage_provision_complete_pass")
    ):
        return ProvisionOutcome.SUCCEEDED

    # Observed not-ready without failure, stall, or lag evidence: not yet
    # determined. Everything unobserved is indeterminate, never false.
    return ProvisionOutcome.INDETERMINATE


def resolve_reclamation_outcome(evidence: Dict) -> ReclamationOutcome:
    """Resolve per-workload reclamation outcome from tri-state evidence.

    RECLAIMED requires either the explicit destroy-job success or the full
    corroborated disappearance set (subject gone AND namespace gone AND PVs
    observed released). Disappearance alone is an evidence input, not a
    verdict: a manually deleted subject or namespace proves nothing about
    the destroy job.
    """
    if evidence.get("collection_ok") is False:
        return ReclamationOutcome.COLLECTION_UNAVAILABLE

    # Explicit destroy failure or destroy-failed state wins (failure
    # precedence), even if the subject or namespace is already gone.
    if (
        evidence.get("destroy_job_succeeded") is False
        or _observed(evidence, "state_is_destroy_failed")
    ):
        return ReclamationOutcome.DESTROY_FAILED

    if _observed(evidence, "destroy_stalled"):
        return ReclamationOutcome.DESTROY_STALLED

    # Reclaimed-with-leak: workload gone but resources observed not released.
    gone = _observed(evidence, "anarchysubject_gone") or _observed(evidence, "namespace_gone")
    if gone and evidence.get("pvs_released") is False:
        return ReclamationOutcome.RESOURCE_LEAK

    if _observed(evidence, "destroy_job_succeeded"):
        return ReclamationOutcome.RECLAIMED

    if (
        _observed(evidence, "anarchysubject_gone")
        and _observed(evidence, "namespace_gone")
        and _observed(evidence, "pvs_released")
    ):
        return ReclamationOutcome.RECLAIMED

    # Partial disappearance (e.g. subject gone, namespace still present, no
    # explicit job outcome) proves neither success nor failure.
    return ReclamationOutcome.INDETERMINATE
