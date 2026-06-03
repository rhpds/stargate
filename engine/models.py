from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class StageOutcome(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    RETRY = "retry"
    ESCALATE = "escalate"
    INDETERMINATE = "indeterminate"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    WARNED = "warned"
    FAILED = "failed"


class RemediationMode(str, Enum):
    RECOMMEND_ONLY = "recommend_only"
    MANUAL_APPROVAL = "manual_approval"
    AUTO_EXECUTE = "auto_execute"


class RemediationRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExecutionMethod(str, Enum):
    KUBERNETES = "kubernetes"
    RHDP_ANARCHY = "rhdp_anarchy"
    RHDP_SANDBOX_API = "rhdp_sandbox_api"
    RHDP_POOLBOY = "rhdp_poolboy"


# --- Run ---

class Run(BaseModel):
    run_id: str = Field(..., min_length=1)
    demo_id: str = Field(..., min_length=1)
    namespace: str = Field(..., min_length=1)
    requested_by: str = Field(..., min_length=1)
    status: RunStatus = RunStatus.PENDING
    rubric_version: str = Field(..., min_length=1)
    git_sha: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# --- Stage ---

class StageResult(BaseModel):
    outcome: StageOutcome
    failure_class: Optional[str] = None
    message: Optional[str] = None


class Stage(BaseModel):
    run_id: str = Field(..., min_length=1)
    stage_id: str = Field(..., min_length=1)
    status: StageStatus = StageStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    result: Optional[StageResult] = None


# --- Evidence ---

class EvidenceResource(BaseModel):
    kind: str
    namespace: str
    name: str


class Evidence(BaseModel):
    evidence_id: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    stage_id: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    resource: Optional[EvidenceResource] = None
    observed: Dict[str, Any] = Field(default_factory=dict)
    result: StageOutcome
    timestamp: datetime
    raw_ref: Optional[str] = None


# --- Rubric ---

class RubricCriterion(BaseModel):
    name: str = Field(..., min_length=1)
    required: bool = True


class RubricOutcomeRule(BaseModel):
    when: str = Field(..., min_length=1)


class FailureClassCondition(BaseModel):
    when: List[str]
    recommended_action: str


class Rubric(BaseModel):
    id: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    stage: str = Field(..., min_length=1)
    timeout_seconds: Optional[int] = None
    entry_criteria: List[RubricCriterion] = Field(default_factory=list)
    exit_criteria: List[RubricCriterion] = Field(default_factory=list)
    outcomes: Dict[str, RubricOutcomeRule] = Field(default_factory=dict)
    failure_classes: Dict[str, FailureClassCondition] = Field(default_factory=dict)
    allowed_remediations: List[str] = Field(default_factory=list)
    forbidden_remediations: List[str] = Field(default_factory=list)


# --- Investigation ---

class InvestigationStep(BaseModel):
    """A single step in a multi-step investigation chain."""
    command: str
    condition: Optional[str] = None   # e.g. "failed_pods" (truthy) or "pod_description contains CrashLoopBackOff"
    extract: Optional[str] = None     # JSONPath-like extraction from JSON output
    store_as: Optional[str] = None    # variable name to store result


# --- Remediation ---

class Remediation(BaseModel):
    id: str = Field(..., min_length=1)
    risk: RemediationRisk
    mode: RemediationMode = RemediationMode.RECOMMEND_ONLY
    type: str = "remediation"
    execution_method: ExecutionMethod = ExecutionMethod.KUBERNETES
    scope: str = Field(..., min_length=1)
    requires_approval: bool = True
    allowed_when: List[str] = Field(default_factory=list)
    commands: List[str] = Field(default_factory=list)
    steps: List[InvestigationStep] = Field(default_factory=list)
    output_template: str = ""
    forbidden_when: List[str] = Field(default_factory=list)


# --- Demo Definition ---

class DemoStageDefinition(BaseModel):
    stage_id: str = Field(..., min_length=1)
    rubric_id: Optional[str] = None


class DemoDefinition(BaseModel):
    demo_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    namespace_prefix: str = Field(..., min_length=1)
    stages: List[DemoStageDefinition] = Field(..., min_length=1)
    rubric_version: str = Field(..., min_length=1)


# --- Action Receipt ---

class ActionResult(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    ESCALATED = "escalated"


class ActionReceipt(BaseModel):
    action_id: str = Field(..., min_length=1)
    run_id: str = Field(..., min_length=1)
    actor: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)
    scope: str = Field(..., min_length=1)
    namespace: str = Field(..., min_length=1)
    evidence_required: List[str] = Field(default_factory=list)
    result: ActionResult = ActionResult.ALLOWED
    executed_at: Optional[datetime] = None
    denied_reason: Optional[str] = None


# --- Build Report ---

class BuildStageResult(str, Enum):
    RED = "red"
    GREEN = "green"


class BuildStageReport(BaseModel):
    name: str
    result: BuildStageResult
    tests: int = 0
    failures: int = 0


class BuildReport(BaseModel):
    build_run_id: str
    git_sha: Optional[str] = None
    status: BuildStageResult = BuildStageResult.RED
    stages: List[BuildStageReport] = Field(default_factory=list)
    blocking: List[str] = Field(default_factory=list)
