"""AI proposal data models with immutable safety constraints.

Every AI-generated output MUST carry:
  status: proposed
  approved: false
  requires_human_review: true

These fields are enforced at the model level and cannot be overridden.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class ProposalType(str, Enum):
    FAILURE_SUMMARY = "failure_summary"
    RUBRIC_DIFF = "rubric_diff"
    RUNBOOK_UPDATE = "runbook_update"
    REMEDIATION_SUGGESTION = "remediation_suggestion"


class ProposalStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class AIProposal(BaseModel):
    """Base model for all AI-generated proposals. Safety fields are immutable at creation."""
    proposal_id: str = Field(..., min_length=1)
    proposal_type: ProposalType
    source_run_id: str = Field(..., min_length=1)
    source_stage_id: Optional[str] = None
    status: ProposalStatus = ProposalStatus.PROPOSED
    approved: bool = False
    requires_human_review: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None

    @field_validator("status", mode="before")
    @classmethod
    def enforce_proposed_status(cls, v):
        if v != ProposalStatus.PROPOSED and v != "proposed":
            raise ValueError("AI proposals must be created with status='proposed'")
        return ProposalStatus.PROPOSED

    @field_validator("approved", mode="before")
    @classmethod
    def enforce_not_approved(cls, v):
        if v is True:
            raise ValueError("AI proposals cannot be created as approved")
        return False

    @field_validator("requires_human_review", mode="before")
    @classmethod
    def enforce_human_review(cls, v):
        if v is False:
            raise ValueError("AI proposals must require human review")
        return True


class FailureSummary(AIProposal):
    """Structured summary of why a stage or run failed."""
    proposal_type: ProposalType = ProposalType.FAILURE_SUMMARY
    failed_stages: List[str] = Field(default_factory=list)
    summary: str = ""
    root_cause_hypothesis: str = ""
    supporting_evidence: List[Dict[str, Any]] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    confidence: str = "low"


class RubricDiff(AIProposal):
    """Proposed change to a rubric definition."""
    proposal_type: ProposalType = ProposalType.RUBRIC_DIFF
    rubric_id: str = Field(..., min_length=1)
    rubric_version: str = Field(..., min_length=1)
    change_type: str = ""
    description: str = ""
    current_yaml: str = ""
    proposed_yaml: str = ""
    rationale: str = ""
    supporting_evidence: List[Dict[str, Any]] = Field(default_factory=list)


class RunbookUpdate(AIProposal):
    """Proposed update to a runbook or remediation catalog."""
    proposal_type: ProposalType = ProposalType.RUNBOOK_UPDATE
    target_id: str = Field(..., min_length=1)
    change_type: str = ""
    description: str = ""
    current_content: str = ""
    proposed_content: str = ""
    rationale: str = ""
    applicable_failure_classes: List[str] = Field(default_factory=list)
