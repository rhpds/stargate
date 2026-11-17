"""API request/response schemas — formal contracts for all endpoints."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# --- Health ---

class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "stargate"


# --- Runs ---

class CreateRunRequest(BaseModel):
    run_id: Optional[str] = None
    demo_id: str
    namespace: str
    requested_by: str
    rubric_version: str = "v0.1.0"
    git_sha: Optional[str] = None
    lab_code: Optional[str] = None
    cluster_name: Optional[str] = None


class RunResponse(BaseModel):
    run_id: str
    demo_id: str
    namespace: str
    requested_by: str
    status: str
    rubric_version: str
    git_sha: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# --- Stages ---

class StageResponse(BaseModel):
    run_id: str
    stage_id: str
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None


# --- Evidence ---

class SubmitEvidenceRequest(BaseModel):
    evidence_id: Optional[str] = None
    type: str
    source: str
    resource: Optional[Dict] = None
    observed: Dict
    result: str
    timestamp: Optional[str] = None
    raw_ref: Optional[str] = None


class EvidenceResponse(BaseModel):
    evidence_id: str
    run_id: str
    stage_id: str
    type: str
    source: str
    observed: Dict
    result: str
    timestamp: datetime


# --- Evaluate ---

class EvaluateRequest(BaseModel):
    evidence: Optional[Dict] = None


class CriterionResult(BaseModel):
    name: str
    required: bool
    passed: Optional[bool]


class EvaluateResponse(BaseModel):
    stage_id: str
    outcome: str
    failure_class: Optional[str] = None
    message: Optional[str] = None
    criteria: List[CriterionResult] = []


# --- Report ---

class StageReport(BaseModel):
    stage_id: str
    status: str
    outcome: Optional[str] = None
    failure_class: Optional[str] = None
    message: Optional[str] = None
    duration_seconds: Optional[float] = None
    evidence_count: int = 0


class RunReport(BaseModel):
    run_id: str
    demo_id: str
    namespace: str
    status: str
    rubric_version: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    stages: List[StageReport] = []
    passed: int = 0
    failed: int = 0
    warned: int = 0
    pending: int = 0


# --- Bundle ---

class EvaluationHistory(BaseModel):
    run_id: str
    stage_id: str
    outcome: str
    failure_class: Optional[str] = None
    message: Optional[str] = None
    evaluated_at: Optional[str] = None
    cluster_name: Optional[str] = None


class LastPassingRun(BaseModel):
    run_id: str
    stage_id: str
    evaluated_at: Optional[str] = None
    cluster_name: Optional[str] = None


class ClusterSummary(BaseModel):
    cluster: str
    total_evaluations: int
    passed: int
    failed: int
    warned: int
    health_rate: float
    failure_classes: Dict[str, int] = {}
    labs_seen: int = 0
    labs_failing: int = 0


class BundleStage(BaseModel):
    stage_id: str
    outcome: Optional[str] = None
    failure_class: Optional[str] = None
    message: Optional[str] = None


class BundleResponse(BaseModel):
    run_id: str
    lab_code: Optional[str] = None
    cluster_name: Optional[str] = None
    current: Dict[str, List[BundleStage]] = {}
    history: List[EvaluationHistory] = []
    failure_frequency: Dict[str, int] = {}
    last_passing_run: Optional[LastPassingRun] = None
    cluster_summary: Optional[ClusterSummary] = None
    constraints: Optional[Dict] = None


# --- Events ---

class EventResponse(BaseModel):
    event_id: str
    event_type: str
    timestamp: str
    run_id: str = ""
    stage_id: Optional[str] = None
    lab_code: Optional[str] = None
    cluster_name: Optional[str] = None
    outcome: Optional[str] = None
    failure_class: Optional[str] = None
    message: Optional[str] = None
    priority: float = 0.0
    metadata: Dict[str, Any] = {}
    filtered: bool = False
    correlated: bool = False
    systemic: bool = False
    deduplicated: bool = False
    blast_radius: Optional[Dict] = None


class EventSummary(BaseModel):
    total_events: int
    filtered: int
    delivered: int
    systemic: int
    escalated: int
    by_type: Dict[str, int] = {}
    filter_rate: float


# --- Consumers ---

class RegisterConsumerRequest(BaseModel):
    url: str
    event_types: Optional[List[str]] = None


class RegisterConsumerResponse(BaseModel):
    registered: bool
    url: str
    event_types: Optional[List[str]] = None


# --- Constraints ---

class ConstraintResponse(BaseModel):
    workloads: Optional[List[str]] = None
    workload_count: Optional[int] = None
    collections: Optional[List[Dict]] = None
    ocp_version: Optional[str] = None
    cloud_provider: Optional[str] = None
    config: Optional[str] = None
    operator_channels: Optional[Dict[str, str]] = None
    components: Optional[List[Dict]] = None
    display_name: Optional[str] = None
    asset_uuid: Optional[str] = None
    timeout_seconds: Optional[int] = None
    showroom_repo: Optional[str] = None
    showroom_ref: Optional[str] = None
    deployer_scm_url: Optional[str] = None
    deployer_scm_ref: Optional[str] = None
    execution_environment_image: Optional[str] = None


# --- Integration (Stage 5) ---

class ValidationResult(BaseModel):
    """What StarGate would POST to Labagator."""
    lab_code: str
    cluster_name: str
    outcome: str
    failure_class: Optional[str] = None
    message: Optional[str] = None
    priority: float = 0.0
    stages: List[EvaluateResponse] = []
    bundle_url: Optional[str] = None


class ExternalEvidenceRequest(BaseModel):
    """What Demolition would POST to StarGate."""
    source: str = "demolition"
    session_id: Optional[int] = None
    session_name: Optional[str] = None
    workshop_url: Optional[str] = None
    lab_code: Optional[str] = None
    cluster_name: Optional[str] = None
    outcome: str
    modules: Optional[List[Dict]] = None
    steps_passed: int = 0
    steps_failed: int = 0
    error_summary: Optional[str] = None


class FeedbackRequest(BaseModel):
    """HITL feedback on an evaluation."""
    action_taken: Optional[str] = None
    worked: Optional[bool] = None
    correct_classification: Optional[bool] = None
    corrected_class: Optional[str] = None
    notes: Optional[str] = None
    reviewed_by: Optional[str] = None


# --- Remediation ---

class RemediationPreviewRequest(BaseModel):
    namespace: str = Field(..., min_length=1)
    failure_class: str = ""
    cluster: str = ""
    lab_code: Optional[str] = None
    action_type: Optional[str] = None


class RemediationExecuteRequest(BaseModel):
    namespace: str = Field(..., min_length=1)
    failure_class: str = ""
    cluster: str = ""
    lab_code: Optional[str] = None
    action_type: Optional[str] = None


class RemediationConfigRequest(BaseModel):
    execution_mode: str = "recommend_only"
    max_actions_per_hour: int = Field(default=5, ge=1, le=100)
    enabled_by: str = "admin"
    notes: Optional[str] = None


class PlaybookRunRequest(BaseModel):
    namespace: str = Field(default="stargate-test", min_length=1)
    failure_class: str = "pods_crashlooping"
    pod: str = ""
    lab_code: Optional[str] = None
    cluster_name: Optional[str] = None
    mock_context: Dict[str, Any] = Field(default_factory=dict)


class GeoluxProposalRequest(BaseModel):
    proposal: Dict[str, Any] = Field(default_factory=dict)
    event_id: str = ""



class DemandCitation(BaseModel):
    """One session's contribution to an hour's demand (EDD in the UI)."""
    lab: str
    attendees: int
    vm_slots: Optional[int] = None
    ai_cores: Optional[float] = None
    ai_memory_gib: Optional[float] = None


class ForecastHour(BaseModel):
    hour: str
    sessions: int
    vm_slots: Optional[int] = None
    ai_cores: Optional[float] = None
    ai_memory_gib: Optional[float] = None
    sessions_without_profiles: int = 0
    demand_citations: List[DemandCitation] = []
    deficit_state: str
    supply_vm_slots: Optional[float] = None


class ForecastCoverage(BaseModel):
    sessions_total: int
    sessions_with_profiles: int
    sessions_fallback: int
    lower_bound: bool


class FleetSupplyCluster(BaseModel):
    cluster: str
    compute_nodes: int
    peak_vms_per_node: float
    vm_slots: float


class FleetSupply(BaseModel):
    vm_slots: float
    clusters: List[FleetSupplyCluster]
    basis: str
    window_hours: int


class ResourceForecastResponse(BaseModel):
    """The capacity-forecast/v1 contract as an OpenAPI response model —
    the frontend renders the contract, not a shaped dict."""
    contract: str
    generated_at: str
    window_hours: int
    authority: str
    risk: str
    hourly: List[ForecastHour]
    coverage: ForecastCoverage
    peak_hour: Optional[ForecastHour] = None
    supply: Optional[FleetSupply] = None


class FailureConcentrationEntry(BaseModel):
    lab_code: str
    kind: str
    failures: int
    share_pct: float
    cumulative_pct: float


class FailureConcentration(BaseModel):
    window_days: int
    total_failures: int
    distinct_lab_codes: int
    entries: List[FailureConcentrationEntry]
    labs_only: List[FailureConcentrationEntry]
    split: Dict[str, float]


class ProvisionConcentrationEntry(BaseModel):
    catalog_item: str
    jobs: int
    share_pct: float
    cumulative_pct: float


class ProvisionConcentration(BaseModel):
    window_days: int
    total_provisions: int
    distinct_items: int
    entries: List[ProvisionConcentrationEntry]


class ConcentrationResponse(BaseModel):
    failures: FailureConcentration
    provisions: ProvisionConcentration


class EventDayDemand(BaseModel):
    sessions: int
    cohort_bound: int
    summed_bound: int
    peak_concurrent: int


class EventDemand(BaseModel):
    event_id: Optional[int] = None
    days: Dict[str, EventDayDemand]


class EventForecastResponse(BaseModel):
    window: Dict[str, object] = {}
    events: Dict[str, EventDemand]


# --- Rotation page ---

class RotationProviderCount(BaseModel):
    """Verified-live counts for one provider, as produced by the audit run."""

    provider: str
    verified_live: int = 0
    live_locations: int = 0
    untracked_live: int = 0


class RotationSnapshotIngest(BaseModel):
    """One day of verified-live evidence. Counts and hashes only — never values."""

    date: date_type
    providers: List[RotationProviderCount] = Field(default_factory=list)


class RotationCredentialRow(BaseModel):
    """One live credential, identified by hash — never by value."""

    id: str
    credential: str
    provider: str = ""
    live_copies: int = 0
    clusters: str = ""
    example_location: str = ""
    coverage: str = ""
    jira_keys: str = ""


class RotationCredentialsIngest(BaseModel):
    date: date_type
    credentials: List[RotationCredentialRow] = Field(default_factory=list)
