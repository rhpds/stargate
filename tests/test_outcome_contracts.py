"""Tests for the provisioning and reclamation outcome contracts.

These pin the contract semantics: tri-state evidence (unobserved is never
coerced), explicit outcomes only (termination ≠ success), failure
precedence across levels, and observed-evidence-only success.
"""

import pytest

from contracts.outcome_contracts import (
    PROVISIONING_OUTCOME_CONTRACT_VERSION,
    RECLAMATION_OUTCOME_CONTRACT_VERSION,
    ProvisionOutcome,
    ReclamationOutcome,
    resolve_provision_outcome,
    resolve_reclamation_outcome,
)
from collectors.babylon.collect_anarchy_state import _check_destroy_succeeded


# --- Provisioning -----------------------------------------------------------


class TestProvisionOutcomeResolution:
    def test_collection_failure_is_not_a_workload_outcome(self):
        assert resolve_provision_outcome({"collection_ok": False}) is ProvisionOutcome.COLLECTION_UNAVAILABLE

    def test_collection_failure_beats_everything(self):
        evidence = {"collection_ok": False, "provision_job_succeeded": True, "state_is_started": True}
        assert resolve_provision_outcome(evidence) is ProvisionOutcome.COLLECTION_UNAVAILABLE

    def test_subject_explicit_failure(self):
        assert resolve_provision_outcome({"provision_job_succeeded": False}) is ProvisionOutcome.FAILED

    def test_cohort_failed_condition(self):
        assert resolve_provision_outcome({"workshopprovision_failed_condition": True}) is ProvisionOutcome.FAILED

    def test_aap_job_failure(self):
        assert resolve_provision_outcome({"aap_job_successful": False}) is ProvisionOutcome.FAILED

    def test_stage_failure(self):
        assert resolve_provision_outcome({"stage_provision_complete_pass": False}) is ProvisionOutcome.FAILED

    def test_failure_precedence_over_cohort_success(self):
        evidence = {"workshopprovision_ready": True, "provision_job_succeeded": False}
        assert resolve_provision_outcome(evidence) is ProvisionOutcome.FAILED

    def test_stalled(self):
        assert resolve_provision_outcome({"workshopprovision_stalled": True}) is ProvisionOutcome.STALLED

    def test_failure_beats_stall(self):
        assert resolve_provision_outcome(
            {"workshopprovision_stalled": True, "provision_job_succeeded": False}
        ) is ProvisionOutcome.FAILED

    def test_controller_lag(self):
        assert resolve_provision_outcome({"controller_lag": True}) is ProvisionOutcome.CONTROLLER_LAG

    def test_lag_precedes_stall(self):
        # A Ready=False condition from a previous generation cannot be trusted
        # to indicate a stall: lag wins.
        evidence = {"controller_lag": True, "workshopprovision_stalled": True}
        assert resolve_provision_outcome(evidence) is ProvisionOutcome.CONTROLLER_LAG

    def test_success_via_subject_evidence(self):
        evidence = {"provision_job_succeeded": True, "state_is_started": True}
        assert resolve_provision_outcome(evidence) is ProvisionOutcome.SUCCEEDED

    def test_success_requires_started_state_alongside_job_success(self):
        # Job succeeded but state never reached started: not success, not
        # failure — indeterminate (mirrors provision_not_started severity).
        evidence = {"provision_job_succeeded": True, "state_is_started": False}
        assert resolve_provision_outcome(evidence) is ProvisionOutcome.INDETERMINATE

    def test_success_via_cohort_ready(self):
        assert resolve_provision_outcome({"workshopprovision_ready": True}) is ProvisionOutcome.SUCCEEDED

    def test_success_via_stage_pass(self):
        assert resolve_provision_outcome({"stage_provision_complete_pass": True}) is ProvisionOutcome.SUCCEEDED

    def test_aap_success_alone_is_corroborating_not_sufficient(self):
        assert resolve_provision_outcome({"aap_job_successful": True}) is ProvisionOutcome.INDETERMINATE

    def test_unobserved_is_indeterminate_never_failure(self):
        assert resolve_provision_outcome({}) is ProvisionOutcome.INDETERMINATE
        assert resolve_provision_outcome({"provision_job_succeeded": None}) is ProvisionOutcome.INDETERMINATE

    def test_observed_not_ready_without_stall_is_indeterminate(self):
        # WorkshopProvision Ready=False observed, no stall (young), no failure:
        # not yet determined — never a fabricated failure.
        assert resolve_provision_outcome({"workshopprovision_ready": False}) is ProvisionOutcome.INDETERMINATE

    def test_empty_is_never_returned_by_the_per_provision_resolver(self):
        # EMPTY is a collection-layer outcome only.
        assert resolve_provision_outcome({"collection_ok": True}) is ProvisionOutcome.INDETERMINATE


# --- Reclamation ------------------------------------------------------------


class TestReclamationOutcomeResolution:
    def test_collection_failure(self):
        assert resolve_reclamation_outcome({"collection_ok": False}) is ReclamationOutcome.COLLECTION_UNAVAILABLE

    def test_destroy_job_explicit_failure(self):
        assert resolve_reclamation_outcome({"destroy_job_succeeded": False}) is ReclamationOutcome.DESTROY_FAILED

    def test_destroy_failed_state(self):
        assert resolve_reclamation_outcome({"state_is_destroy_failed": True}) is ReclamationOutcome.DESTROY_FAILED

    def test_failure_precedence_over_disappearance(self):
        # Subject and namespace gone, but the destroy job explicitly failed:
        # someone or something removed them — the destroy did not succeed.
        evidence = {
            "destroy_job_succeeded": False,
            "anarchysubject_gone": True,
            "namespace_gone": True,
            "pvs_released": True,
        }
        assert resolve_reclamation_outcome(evidence) is ReclamationOutcome.DESTROY_FAILED

    def test_destroy_stalled(self):
        assert resolve_reclamation_outcome({"destroy_stalled": True}) is ReclamationOutcome.DESTROY_STALLED

    def test_failure_beats_stall(self):
        assert resolve_reclamation_outcome(
            {"destroy_stalled": True, "destroy_job_succeeded": False}
        ) is ReclamationOutcome.DESTROY_FAILED

    def test_reclaimed_via_explicit_job_outcome(self):
        assert resolve_reclamation_outcome({"destroy_job_succeeded": True}) is ReclamationOutcome.RECLAIMED

    def test_reclaimed_via_corroborated_disappearance(self):
        evidence = {"anarchysubject_gone": True, "namespace_gone": True, "pvs_released": True}
        assert resolve_reclamation_outcome(evidence) is ReclamationOutcome.RECLAIMED

    def test_disappearance_alone_is_not_success(self):
        assert resolve_reclamation_outcome({"anarchysubject_gone": True}) is ReclamationOutcome.INDETERMINATE
        assert resolve_reclamation_outcome({"namespace_gone": True}) is ReclamationOutcome.INDETERMINATE

    def test_partial_disappearance_is_indeterminate(self):
        evidence = {"anarchysubject_gone": True, "namespace_gone": False}
        assert resolve_reclamation_outcome(evidence) is ReclamationOutcome.INDETERMINATE

    def test_resource_leak_overrides_reclaimed(self):
        evidence = {
            "destroy_job_succeeded": True,
            "anarchysubject_gone": True,
            "namespace_gone": True,
            "pvs_released": False,
        }
        assert resolve_reclamation_outcome(evidence) is ReclamationOutcome.RESOURCE_LEAK

    def test_resource_leak_via_disappearance(self):
        evidence = {"anarchysubject_gone": True, "namespace_gone": True, "pvs_released": False}
        assert resolve_reclamation_outcome(evidence) is ReclamationOutcome.RESOURCE_LEAK

    def test_unobserved_is_indeterminate(self):
        assert resolve_reclamation_outcome({}) is ReclamationOutcome.INDETERMINATE
        assert resolve_reclamation_outcome({"destroy_job_succeeded": None}) is ReclamationOutcome.INDETERMINATE


# --- Destroy towerJobs parsing (Anarchy collector) --------------------------


class TestCheckDestroySucceeded:
    def test_successful_destroy(self):
        assert _check_destroy_succeeded({"destroy": {"status": "successful"}}) is True

    def test_stop_key_fallback(self):
        assert _check_destroy_succeeded({"stop": {"status": "successful"}}) is True

    def test_failed_destroy(self):
        assert _check_destroy_succeeded({"destroy": {"status": "failed"}}) is False

    def test_error_and_canceled_are_failures(self):
        assert _check_destroy_succeeded({"destroy": {"status": "error"}}) is False
        assert _check_destroy_succeeded({"destroy": {"status": "canceled"}}) is False

    def test_running_is_unverified(self):
        assert _check_destroy_succeeded({"destroy": {"status": "running"}}) is None

    def test_malformed_job_is_unverified(self):
        assert _check_destroy_succeeded({"destroy": "not-a-dict"}) is None

    def test_empty_history_is_observed_not_succeeded(self):
        assert _check_destroy_succeeded({}) is False
        assert _check_destroy_succeeded({"destroy": {}}) is False

    def test_mixed_history_is_unverified(self):
        jobs = [{"status": "successful"}, {"status": "failed"}]
        assert _check_destroy_succeeded({"destroy": jobs}) is None

    def test_all_successful_list_history(self):
        jobs = [{"status": "successful"}, {"status": "successful"}]
        assert _check_destroy_succeeded({"destroy": jobs}) is True

    def test_all_failed_list_history(self):
        jobs = [{"status": "failed"}, {"status": "error"}]
        assert _check_destroy_succeeded({"destroy": jobs}) is False

    def test_provision_jobs_do_not_leak_into_destroy_check(self):
        # A successful provision must not imply a successful destroy.
        assert _check_destroy_succeeded({"provision": {"status": "successful"}}) is False


# --- Taxonomy adoption ------------------------------------------------------


class TestTaxonomyAdoption:
    """The lifecycle classes must be first-class taxonomy citizens: served on
    the DeepField wire format with categories, and loadable by source."""

    def test_workshop_provision_classes_are_served(self):
        from engine.failure_class_loader import get_classes_by_source

        wp = get_classes_by_source("workshop_provision")
        assert {
            "workshop_provision_failed", "workshop_provision_controller_lag",
            "workshop_provision_stalled", "workshop_provision_crd_unavailable",
        } <= set(wp)

    def test_reclamation_classes_are_served(self):
        from engine.failure_class_loader import get_classes_by_source

        rec = get_classes_by_source("reclamation")
        assert {
            "destroy_failed", "teardown_incomplete", "teardown_namespace_lingering",
        } <= set(rec)

    def test_wire_format_categories(self):
        from contracts.failure_class_schema import normalize_raw_class
        from engine.failure_class_loader import get_class

        assert normalize_raw_class(get_class("destroy_failed"))["category"] == "reclamation"
        assert normalize_raw_class(get_class("teardown_incomplete"))["category"] == "reclamation"
        assert normalize_raw_class(get_class("workshop_provision_failed"))["category"] == "provisioning"

    def test_new_patterns_do_not_shift_the_frozen_qualification_baseline(self):
        """Lifecycle catalog patterns must not match any frozen case evidence.

        The regex baseline's results on the frozen case set are part of the
        qualification contract; a new taxonomy entry that matches frozen
        evidence would silently change the control's score.
        """
        import json as _json
        from pathlib import Path
        from qualify.qualify_classifier import load_taxonomy

        cases = _json.loads(
            (Path(__file__).resolve().parents[1] / "qualify" / "classifier_cases.json").read_text()
        )["cases"]
        lifecycle = {
            name: pattern
            for name, pattern in load_taxonomy()
            if name.startswith("workshop_provision")
            or name in ("destroy_failed", "teardown_incomplete", "teardown_namespace_lingering")
        }
        assert lifecycle, "lifecycle classes missing from taxonomy"
        for case in cases:
            for name, pattern in lifecycle.items():
                assert not pattern.search(case["evidence"]), (
                    f"lifecycle pattern {name} matches frozen case {case['id']}"
                )


class TestContractIdentity:
    def test_versions_are_pinned(self):
        assert PROVISIONING_OUTCOME_CONTRACT_VERSION == "provisioning-outcome/v1"
        assert RECLAMATION_OUTCOME_CONTRACT_VERSION == "reclamation-outcome/v1"

    def test_enum_values_are_snake_case_wire_safe(self):
        for outcome in ProvisionOutcome:
            assert outcome.value == outcome.value.lower()
        for outcome in ReclamationOutcome:
            assert outcome.value == outcome.value.lower()

    def test_destroy_evidence_reaches_collector_output(self):
        from collectors.babylon.collect_anarchy_state import collect_anarchysubject

        subject = {
            "metadata": {"name": "subj-1", "namespace": "babylon-anarchy-events"},
            "status": {"state": "destroying", "towerJobs": {"destroy": {"status": "successful"}}},
            "spec": {"vars": {}},
        }
        evidence = collect_anarchysubject(subject)
        assert evidence.observed["destroy_job_succeeded"] is True
