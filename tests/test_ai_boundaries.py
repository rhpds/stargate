"""AI boundary enforcement tests.

Verifies:
- Proposals never self-approve
- Proposals cannot mutate rubrics directly
- All output labeled proposed/unapproved
- Deterministic gates unaffected by AI layer
- Proposals reference source evidence
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from proposals.models import (
    AIProposal,
    FailureSummary,
    ProposalStatus,
    ProposalType,
    RubricDiff,
    RunbookUpdate,
)
from proposals.failure_summarizer import summarize_failures
from proposals.rubric_proposer import propose_new_failure_class, propose_additional_criterion
from proposals.runbook_proposer import propose_runbook_update
from engine.models import Rubric, RubricCriterion, StageOutcome
from engine.rubric_evaluator import CriterionResult, EvaluationResult, evaluate_rubric


# --- Safety constraint tests ---

class TestProposalSafetyConstraints:
    """AI proposals must never be created as approved."""

    def test_cannot_create_approved_proposal(self):
        with pytest.raises(ValidationError, match="cannot be created as approved"):
            FailureSummary(
                proposal_id="test",
                source_run_id="run-001",
                approved=True,
            )

    def test_cannot_create_with_approved_status(self):
        with pytest.raises(ValidationError, match="must be created with status='proposed'"):
            FailureSummary(
                proposal_id="test",
                source_run_id="run-001",
                status="approved",
            )

    def test_cannot_skip_human_review(self):
        with pytest.raises(ValidationError, match="must require human review"):
            FailureSummary(
                proposal_id="test",
                source_run_id="run-001",
                requires_human_review=False,
            )

    def test_default_proposal_is_safe(self):
        proposal = FailureSummary(
            proposal_id="test",
            source_run_id="run-001",
        )
        assert proposal.status == ProposalStatus.PROPOSED
        assert proposal.approved is False
        assert proposal.requires_human_review is True

    def test_rubric_diff_is_safe(self):
        diff = RubricDiff(
            proposal_id="test",
            source_run_id="run-001",
            rubric_id="test-rubric",
            rubric_version="v0.1.0",
        )
        assert diff.status == ProposalStatus.PROPOSED
        assert diff.approved is False
        assert diff.requires_human_review is True

    def test_runbook_update_is_safe(self):
        update = RunbookUpdate(
            proposal_id="test",
            source_run_id="run-001",
            target_id="test-target",
        )
        assert update.status == ProposalStatus.PROPOSED
        assert update.approved is False

    def test_all_proposal_types_enforce_safety(self):
        """Every proposal subclass must enforce the same safety constraints."""
        for cls in [FailureSummary, RubricDiff, RunbookUpdate]:
            with pytest.raises(ValidationError):
                cls(
                    proposal_id="test",
                    source_run_id="run-001",
                    rubric_id="x",
                    rubric_version="v1",
                    target_id="x",
                    approved=True,
                )


# --- Failure summarizer tests ---

class TestFailureSummarizer:
    def _make_fail_result(self, stage_id="route-ready", failure_class="service_has_no_endpoints"):
        return EvaluationResult(
            stage_id=stage_id,
            outcome=StageOutcome.FAIL,
            failure_class=failure_class,
            message="Required criteria failed: service_has_ready_endpoints",
            criteria_results=[
                CriterionResult(name="service_exists", required=True, passed=True),
                CriterionResult(name="service_has_ready_endpoints", required=True, passed=False),
            ],
        )

    def _make_pass_result(self, stage_id="namespace-ready"):
        return EvaluationResult(
            stage_id=stage_id,
            outcome=StageOutcome.PASS,
            message="All criteria passed",
            criteria_results=[
                CriterionResult(name="namespace_exists", required=True, passed=True),
            ],
        )

    def test_summary_is_proposed(self):
        result = self._make_fail_result()
        summary = summarize_failures("run-001", [result])
        assert summary.status == ProposalStatus.PROPOSED
        assert summary.approved is False
        assert summary.requires_human_review is True

    def test_summary_references_source_run(self):
        result = self._make_fail_result()
        summary = summarize_failures("run-001", [result])
        assert summary.source_run_id == "run-001"

    def test_summary_identifies_failed_stages(self):
        result = self._make_fail_result()
        summary = summarize_failures("run-001", [result])
        assert "route-ready" in summary.failed_stages

    def test_summary_includes_failure_class(self):
        result = self._make_fail_result()
        summary = summarize_failures("run-001", [result])
        assert "service_has_no_endpoints" in summary.summary

    def test_summary_includes_root_cause(self):
        result = self._make_fail_result()
        summary = summarize_failures("run-001", [result])
        assert len(summary.root_cause_hypothesis) > 0
        assert "endpoint" in summary.root_cause_hypothesis.lower()

    def test_summary_includes_recommended_actions(self):
        result = self._make_fail_result()
        summary = summarize_failures("run-001", [result])
        assert len(summary.recommended_actions) > 0

    def test_summary_includes_supporting_evidence(self):
        result = self._make_fail_result()
        summary = summarize_failures("run-001", [result])
        assert len(summary.supporting_evidence) > 0
        ev = summary.supporting_evidence[0]
        assert ev["stage_id"] == "route-ready"
        assert ev["failure_class"] == "service_has_no_endpoints"

    def test_all_pass_summary(self):
        result = self._make_pass_result()
        summary = summarize_failures("run-001", [result])
        assert summary.failed_stages == []
        assert "passed" in summary.summary.lower()

    def test_crashloop_summary(self):
        result = self._make_fail_result(
            stage_id="deployment-ready",
            failure_class="pods_crashlooping",
        )
        summary = summarize_failures("run-001", [result])
        assert "CrashLoopBackOff" in summary.root_cause_hypothesis


# --- Rubric proposer tests ---

class TestRubricProposer:
    def _make_rubric(self):
        return Rubric(
            id="route-ready",
            version="v0.1.0",
            stage="route-ready",
            entry_criteria=[RubricCriterion(name="service_exists", required=True)],
            exit_criteria=[
                RubricCriterion(name="route_exists", required=True),
                RubricCriterion(name="service_has_ready_endpoints", required=True),
            ],
            failure_classes={},
        )

    def test_proposes_new_failure_class_for_unclassified(self):
        rubric = self._make_rubric()
        result = EvaluationResult(
            stage_id="route-ready",
            outcome=StageOutcome.FAIL,
            failure_class=None,
            message="Required criteria failed",
            criteria_results=[
                CriterionResult(name="service_exists", required=True, passed=True),
                CriterionResult(name="route_exists", required=True, passed=False),
                CriterionResult(name="service_has_ready_endpoints", required=True, passed=False),
            ],
        )
        diff = propose_new_failure_class("run-001", rubric, result)
        assert diff is not None
        assert diff.status == ProposalStatus.PROPOSED
        assert diff.approved is False
        assert diff.change_type == "add_failure_class"
        assert "route_exists" in diff.proposed_yaml

    def test_does_not_propose_for_classified_failure(self):
        rubric = self._make_rubric()
        result = EvaluationResult(
            stage_id="route-ready",
            outcome=StageOutcome.FAIL,
            failure_class="already_classified",
        )
        diff = propose_new_failure_class("run-001", rubric, result)
        assert diff is None

    def test_does_not_propose_for_pass(self):
        rubric = self._make_rubric()
        result = EvaluationResult(
            stage_id="route-ready",
            outcome=StageOutcome.PASS,
        )
        diff = propose_new_failure_class("run-001", rubric, result)
        assert diff is None

    def test_proposed_diff_references_evidence(self):
        rubric = self._make_rubric()
        result = EvaluationResult(
            stage_id="route-ready",
            outcome=StageOutcome.FAIL,
            failure_class=None,
            criteria_results=[
                CriterionResult(name="route_exists", required=True, passed=False),
            ],
        )
        diff = propose_new_failure_class("run-001", rubric, result)
        assert len(diff.supporting_evidence) > 0
        assert diff.supporting_evidence[0]["stage_id"] == "route-ready"

    def test_propose_additional_criterion(self):
        rubric = self._make_rubric()
        diff = propose_additional_criterion(
            "run-001", rubric,
            criterion_name="tls_configured",
            required=False,
            rationale="TLS should be verified for production routes",
        )
        assert diff.status == ProposalStatus.PROPOSED
        assert diff.change_type == "add_exit_criterion"
        assert "tls_configured" in diff.proposed_yaml


# --- Runbook proposer tests ---

class TestRunbookProposer:
    def test_proposes_remediation_for_known_failure(self):
        result = EvaluationResult(
            stage_id="deployment-ready",
            outcome=StageOutcome.FAIL,
            failure_class="pods_crashlooping",
        )
        update = propose_runbook_update("run-001", result)
        assert update is not None
        assert update.status == ProposalStatus.PROPOSED
        assert update.approved is False
        assert "crashloop" in update.target_id.lower() or "crashloop" in update.description.lower()
        assert "pods_crashlooping" in update.applicable_failure_classes

    def test_proposes_generic_for_unknown_failure(self):
        result = EvaluationResult(
            stage_id="custom-stage",
            outcome=StageOutcome.FAIL,
            failure_class="totally_unknown",
            criteria_results=[
                CriterionResult(name="check1", required=True, passed=False),
            ],
        )
        update = propose_runbook_update("run-001", result)
        assert update is not None
        assert update.status == ProposalStatus.PROPOSED
        assert "investigate" in update.target_id

    def test_no_proposal_for_pass(self):
        result = EvaluationResult(
            stage_id="namespace-ready",
            outcome=StageOutcome.PASS,
        )
        update = propose_runbook_update("run-001", result)
        assert update is None

    def test_skips_existing_remediation(self):
        result = EvaluationResult(
            stage_id="deployment-ready",
            outcome=StageOutcome.FAIL,
            failure_class="pods_crashlooping",
        )
        update = propose_runbook_update(
            "run-001", result,
            existing_remediation_ids=["collect_crashloop_diagnostics"],
        )
        assert update is None


# --- Deterministic gate isolation ---

class TestDeterministicGateIsolation:
    """AI layer must not affect deterministic rubric evaluation."""

    RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "platform"

    def test_rubric_evaluation_unchanged_by_ai(self):
        """Rubric evaluation produces the same result regardless of AI proposals."""
        from engine.rubric_loader import load_rubric

        rubric = load_rubric(self.RUBRIC_DIR / "namespace-ready.yaml")

        evidence_pass = {"namespace_exists": True}
        evidence_fail = {"namespace_exists": False}

        result_pass = evaluate_rubric(rubric, evidence_pass)
        result_fail = evaluate_rubric(rubric, evidence_fail)

        assert result_pass.outcome == StageOutcome.PASS
        assert result_fail.outcome == StageOutcome.FAIL

        # Generate AI proposals — they should not alter the results
        summary = summarize_failures("run-001", [result_fail])
        diff = propose_new_failure_class("run-001", rubric, result_fail)

        # Re-evaluate — results must be identical
        result_pass_2 = evaluate_rubric(rubric, evidence_pass)
        result_fail_2 = evaluate_rubric(rubric, evidence_fail)

        assert result_pass_2.outcome == result_pass.outcome
        assert result_fail_2.outcome == result_fail.outcome
        assert result_fail_2.failure_class == result_fail.failure_class

    def test_ai_proposals_are_output_only(self):
        """Proposals are data objects, not side-effecting operations."""
        from engine.rubric_loader import load_rubric

        rubric = load_rubric(self.RUBRIC_DIR / "route-ready.yaml")
        original_criteria_count = len(rubric.exit_criteria)
        original_classes_count = len(rubric.failure_classes)

        diff = propose_additional_criterion(
            "run-001", rubric,
            criterion_name="new_check",
            required=True,
            rationale="test",
        )

        assert len(rubric.exit_criteria) == original_criteria_count
        assert len(rubric.failure_classes) == original_classes_count


# --- PR text generator tests ---

class TestPRGenerator:
    def _make_summary(self):
        return FailureSummary(
            proposal_id="summary-001",
            source_run_id="run-001",
            failed_stages=["route-ready"],
            summary="Stage route-ready failed",
            root_cause_hypothesis="Service has no endpoints",
            recommended_actions=["Check service selector"],
            confidence="medium",
        )

    def _make_diff(self):
        return RubricDiff(
            proposal_id="diff-001",
            source_run_id="run-001",
            rubric_id="route-ready",
            rubric_version="v0.1.0",
            change_type="add_failure_class",
            description="Add new failure class",
            proposed_yaml="failure_classes:\n  new_class: ...\n",
            rationale="Unclassified failure observed",
        )

    def _make_update(self):
        return RunbookUpdate(
            proposal_id="runbook-001",
            source_run_id="run-001",
            target_id="collect_diagnostics",
            change_type="add_remediation",
            description="Add diagnostic collection",
            proposed_content="id: collect_diagnostics\ncommands: []\n",
            rationale="No remediation existed for this failure",
            applicable_failure_classes=["new_class"],
        )

    def test_pr_text_generated(self):
        from proposals.pr_generator import generate_pr_text
        result = generate_pr_text([self._make_summary()], "run-001")
        assert "run-001" in result["title"]
        assert result["status"] == "proposed"
        assert result["approved"] is False
        assert result["requires_human_review"] is True

    def test_pr_body_contains_summary(self):
        from proposals.pr_generator import generate_pr_text
        result = generate_pr_text([self._make_summary()], "run-001")
        assert "Failure Analysis" in result["body"]
        assert "Service has no endpoints" in result["body"]

    def test_pr_body_contains_rubric_diff(self):
        from proposals.pr_generator import generate_pr_text
        result = generate_pr_text([self._make_diff()], "run-001")
        assert "Rubric Changes" in result["body"]
        assert "route-ready" in result["body"]

    def test_pr_body_contains_runbook_update(self):
        from proposals.pr_generator import generate_pr_text
        result = generate_pr_text([self._make_update()], "run-001")
        assert "Runbook Updates" in result["body"]
        assert "collect_diagnostics" in result["body"]

    def test_pr_has_review_labels(self):
        from proposals.pr_generator import generate_pr_text
        result = generate_pr_text([self._make_summary()], "run-001")
        assert "requires-review" in result["labels"]
        assert "ai-generated" in result["labels"]

    def test_pr_with_all_proposal_types(self):
        from proposals.pr_generator import generate_pr_text
        proposals = [self._make_summary(), self._make_diff(), self._make_update()]
        result = generate_pr_text(proposals, "run-001")
        assert result["proposal_count"] == 3
        assert "analysis" in result["title"]
        assert "rubric" in result["title"]
        assert "runbook" in result["title"]


# --- Action receipt tests ---

class TestActionReceipt:
    def test_valid_action_receipt(self):
        from engine.models import ActionReceipt, ActionResult
        receipt = ActionReceipt(
            action_id="act-000001",
            run_id="summit-demo-001",
            actor="summit-demo-factory-sa",
            action="collect_route_diagnostics",
            scope="namespace",
            namespace="summit-demo-001",
            evidence_required=["route_ready_failed", "service_exists"],
            result=ActionResult.ALLOWED,
        )
        assert receipt.action_id == "act-000001"
        assert receipt.result == ActionResult.ALLOWED

    def test_denied_action_receipt(self):
        from engine.models import ActionReceipt, ActionResult
        receipt = ActionReceipt(
            action_id="act-000002",
            run_id="summit-demo-001",
            actor="summit-demo-factory-sa",
            action="delete_namespace",
            scope="namespace",
            namespace="summit-demo-001",
            result=ActionResult.DENIED,
            denied_reason="Action is in forbidden_remediations",
        )
        assert receipt.result == ActionResult.DENIED
        assert receipt.denied_reason is not None

    def test_action_receipt_requires_fields(self):
        from engine.models import ActionReceipt
        with pytest.raises(Exception):
            ActionReceipt(
                action_id="act-001",
                run_id="run-001",
            )
