"""SQLAlchemy ORM models for StarGate persistence.

Future-proof columns for evidence bundles (Stage 3), event bus (Stage 4),
HITL feedback (Stage 5), and remediation tracking (Stage 5) are included
as nullable columns from the start to avoid schema migrations later.
"""

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    Boolean,
)
from sqlalchemy.dialects.postgresql import JSON

from db.database import Base


class RunRecord(Base):
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(255), unique=True, nullable=False, index=True)
    demo_id = Column(String(255), nullable=False)
    namespace = Column(String(255), nullable=False)
    requested_by = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="pending")
    rubric_version = Column(String(50), nullable=False)
    git_sha = Column(String(64), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Stage 3: bundle context
    lab_code = Column(String(255), nullable=True, index=True)
    cluster_name = Column(String(255), nullable=True, index=True)

    # Stage 4: event tracking
    trigger_source = Column(String(255), nullable=True)


class StageRecord(Base):
    __tablename__ = "stages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(255), nullable=False, index=True)
    stage_id = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False, default="pending")
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Float, nullable=True)
    result_outcome = Column(String(50), nullable=True)
    result_failure_class = Column(String(255), nullable=True, index=True)
    result_message = Column(Text, nullable=True)


class EvidenceRecord(Base):
    __tablename__ = "evidence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    evidence_id = Column(String(255), unique=True, nullable=False, index=True)
    run_id = Column(String(255), nullable=False, index=True)
    stage_id = Column(String(255), nullable=False, index=True)
    type = Column(String(255), nullable=False)
    source = Column(String(255), nullable=False)
    resource = Column(JSON, nullable=True)
    observed = Column(JSON, nullable=False, default=dict)
    result = Column(String(50), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    raw_ref = Column(Text, nullable=True)


class EvaluationRecord(Base):
    """Persisted evaluation results — one per stage per run."""
    __tablename__ = "evaluations"
    __table_args__ = (
        Index('idx_eval_lab_stage', 'lab_code', 'stage_id'),
        Index('idx_eval_lab_cluster', 'lab_code', 'cluster_name'),
        Index('idx_eval_cluster_outcome', 'cluster_name', 'outcome'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(255), nullable=False, index=True)
    stage_id = Column(String(255), nullable=False, index=True)
    outcome = Column(String(50), nullable=False)
    failure_class = Column(String(255), nullable=True, index=True)
    message = Column(Text, nullable=True)
    criteria_results = Column(JSON, nullable=True)
    evaluated_at = Column(DateTime(timezone=True), nullable=False)

    # Stage 3: bundle context
    lab_code = Column(String(255), nullable=True, index=True)
    cluster_name = Column(String(255), nullable=True, index=True)

    # Stage 5: HITL feedback
    human_confirmed = Column(Boolean, nullable=True)
    human_corrected_class = Column(String(255), nullable=True)
    human_notes = Column(Text, nullable=True)


class EventLog(Base):
    """Persistent event log — survives API restarts."""
    __tablename__ = "event_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(255), unique=True, nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    run_id = Column(String(255), nullable=True)
    stage_id = Column(String(255), nullable=True, index=True)
    lab_code = Column(String(255), nullable=True, index=True)
    cluster_name = Column(String(255), nullable=True, index=True)
    outcome = Column(String(50), nullable=True)
    failure_class = Column(String(255), nullable=True, index=True)
    message = Column(Text, nullable=True)
    priority = Column(Float, nullable=False, default=0.0)
    systemic = Column(Boolean, nullable=False, default=False)
    filtered = Column(Boolean, nullable=False, default=False)
    blast_radius = Column(JSON, nullable=True)
    metadata_json = Column(JSON, nullable=True)


class ProposedClassification(Base):
    """LLM-proposed failure classifications awaiting human review."""
    __tablename__ = "proposed_classifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(255), nullable=False)
    stage_id = Column(String(255), nullable=False)
    original_message = Column(Text, nullable=True)
    proposed_class = Column(String(255), nullable=False)
    proposed_conditions = Column(JSON, nullable=True)
    confidence = Column(Float, nullable=True)
    llm_model = Column(String(255), nullable=True)
    proposed_at = Column(DateTime(timezone=True), nullable=False)
    reviewed = Column(Boolean, nullable=False, default=False)
    approved = Column(Boolean, nullable=True)
    reviewed_by = Column(String(255), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    llm_metric_id = Column(Integer, nullable=True)


class AuditLog(Base):
    """Audit trail for all actions — ready for future write operations."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action_type = Column(String(100), nullable=False, index=True)
    target = Column(String(255), nullable=False)
    parameters = Column(JSON, nullable=True)
    proposed_by = Column(String(255), nullable=True)
    approved_by = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False, default="proposed")
    executed_at = Column(DateTime(timezone=True), nullable=True)
    result = Column(Text, nullable=True)
    rollback_available = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class Receipt(Base):
    """Persisted test/phase gate receipts — proof of validation."""
    __tablename__ = "receipts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    receipt_type = Column(String(100), nullable=False, index=True)
    phase = Column(String(10), nullable=True, index=True)
    data = Column(JSON, nullable=False)
    passed = Column(Boolean, nullable=False)
    generated_at = Column(DateTime(timezone=True), nullable=False)


class PendingAction(Base):
    __tablename__ = "pending_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action_type = Column(String(100), nullable=False, index=True)
    target = Column(String(255), nullable=False)
    parameters = Column(JSON, nullable=True)
    confidence = Column(Float, nullable=False)
    proposed_by = Column(String(100), nullable=True, default="stargate")
    source_event_id = Column(String(255), nullable=True)
    status = Column(String(50), nullable=False, default="pending")
    proposed_at = Column(DateTime(timezone=True), nullable=False)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(String(255), nullable=True)


class ScanSnapshot(Base):
    """Persisted scan data — survives pod restarts."""
    __tablename__ = "scan_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_type = Column(String(50), nullable=False, index=True)
    data = Column(JSON, nullable=False)
    scanned_at = Column(DateTime(timezone=True), nullable=False, index=True)


class ConstraintViolationRecord(Base):
    __tablename__ = "constraint_violations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lab_code = Column(String(255), nullable=False, index=True)
    violation_type = Column(String(255), nullable=False, index=True)
    expected = Column(Text, nullable=True)
    actual = Column(Text, nullable=True)
    severity = Column(String(50), nullable=False)
    detail = Column(Text, nullable=True)
    correlated_stage = Column(String(255), nullable=True)
    correlated_failure_class = Column(String(255), nullable=True)
    detected_at = Column(DateTime(timezone=True), nullable=False)


class LLMFeedback(Base):
    __tablename__ = "llm_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    llm_metric_id = Column(Integer, nullable=True, index=True)
    endpoint = Column(String(100), nullable=False)
    helpful = Column(Boolean, nullable=False)
    notes = Column(Text, nullable=True)
    submitted_by = Column(String(255), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=False)


class LLMMetric(Base):
    __tablename__ = "llm_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    endpoint = Column(String(100), nullable=False, index=True)
    model = Column(String(255), nullable=False)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    cost_estimate = Column(Float, nullable=True)
    latency_ms = Column(Integer, nullable=False)
    success = Column(Boolean, nullable=False)
    finish_reason = Column(String(50), nullable=True)
    error_type = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    prompt_hash = Column(String(64), nullable=True, index=True)
    response_preview = Column(Text, nullable=True)
    lab_code = Column(String(255), nullable=True, index=True)
    cluster_name = Column(String(255), nullable=True)
    failure_class = Column(String(255), nullable=True)
    confidence = Column(Float, nullable=True)
    adjusted_confidence = Column(Float, nullable=True)
    prompt_version = Column(String(50), nullable=True)
    called_at = Column(DateTime(timezone=True), nullable=False, index=True)


class MVClusterSummary(Base):
    __tablename__ = "mv_cluster_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cluster_name = Column(String(255), unique=True, nullable=False, index=True)
    total_evaluations = Column(Integer, nullable=False, default=0)
    passed = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    warned = Column(Integer, nullable=False, default=0)
    health_rate = Column(Float, nullable=False, default=0.0)
    failure_classes = Column(JSON, nullable=True)
    labs_seen = Column(Integer, nullable=False, default=0)
    labs_failing = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MVPipelineStage(Base):
    __tablename__ = "mv_pipeline_stages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    stage_id = Column(String(255), unique=True, nullable=False, index=True)
    pass_count = Column(Integer, nullable=False, default=0)
    fail_count = Column(Integer, nullable=False, default=0)
    warn_count = Column(Integer, nullable=False, default=0)
    total = Column(Integer, nullable=False, default=0)
    health_rate = Column(Float, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MVLabEvalSummary(Base):
    __tablename__ = "mv_lab_eval_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lab_code = Column(String(255), nullable=False, index=True)
    cluster_name = Column(String(255), nullable=True, index=True)
    total_evals = Column(Integer, nullable=False, default=0)
    passed = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    warned = Column(Integer, nullable=False, default=0)
    top_failure_class = Column(String(255), nullable=True)
    health_rate = Column(Float, nullable=False, default=0.0)
    last_evaluated_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class RemediationRecord(Base):
    """Tracks remediation applications and outcomes for effectiveness measurement."""
    __tablename__ = "remediations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(255), nullable=False, index=True)
    stage_id = Column(String(255), nullable=False)
    failure_class = Column(String(255), nullable=False, index=True)
    remediation_id = Column(String(255), nullable=False, index=True)
    action_taken = Column(Text, nullable=True)
    resolved = Column(Boolean, nullable=True)
    applied_at = Column(DateTime(timezone=True), nullable=True)
    applied_by = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)


class LabMapping(Base):
    """Canonical lab identity mapping across all data sources."""
    __tablename__ = "lab_mappings"

    lab_code = Column(String(50), primary_key=True)
    ci_name = Column(String(255), nullable=True)
    ci_base = Column(String(100), nullable=True, index=True)
    ci_slug = Column(String(255), nullable=True)
    namespace_pattern = Column(String(100), nullable=True)
    pool_pattern = Column(String(100), nullable=True)
    agnosticv_path = Column(String(255), nullable=True)
    cloud = Column(String(50), nullable=True)
    clusters = Column(JSON, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=True)


class PoolSnapshot(Base):
    """Time-series pool handle snapshots for velocity tracking."""
    __tablename__ = "pool_snapshots"
    __table_args__ = (
        Index('idx_pool_snap_name_time', 'pool_name', 'captured_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    pool_name = Column(String(255), nullable=False, index=True)
    available = Column(Integer, nullable=False)
    ready = Column(Integer, nullable=False)
    min_required = Column(Integer, nullable=False)
    total_handles = Column(Integer, nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=False, index=True)


class AAPJobMetric(Base):
    """Time-series AAP provisioning SLI tracking."""
    __tablename__ = "aap_job_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    captured_at = Column(DateTime(timezone=True), nullable=False, index=True)
    total_jobs = Column(Integer, nullable=False, default=0)
    successful = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    running = Column(Integer, nullable=False, default=0)
    success_rate = Column(Float, nullable=True)
    provision_sli = Column(Float, nullable=True)
    sli_met = Column(Boolean, nullable=True)
    top_error = Column(String(500), nullable=True)
    by_cluster = Column(JSON, nullable=True)
    by_lab = Column(JSON, nullable=True)


class ProvisioningSnapshot(Base):
    """Time-series provisioning state (AnarchySubject totals)."""
    __tablename__ = "provisioning_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    captured_at = Column(DateTime(timezone=True), nullable=False, index=True)
    total = Column(Integer, nullable=False, default=0)
    started = Column(Integer, nullable=False, default=0)
    failed = Column(Integer, nullable=False, default=0)
    failure_rate = Column(Float, nullable=True)
    by_state = Column(JSON, nullable=True)
    summit_total = Column(Integer, nullable=True)
    summit_started = Column(Integer, nullable=True)
    summit_failed = Column(Integer, nullable=True)


class SandboxAPIMetric(Base):
    """Time-series sandbox API health and queue metrics."""
    __tablename__ = "sandbox_api_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    captured_at = Column(DateTime(timezone=True), nullable=False, index=True)
    api_healthy = Column(Boolean, nullable=True)
    replicas_desired = Column(Integer, nullable=True)
    replicas_ready = Column(Integer, nullable=True)
    queue_depth = Column(Integer, nullable=True)
    total_sandboxes = Column(Integer, nullable=True)
    active = Column(Integer, nullable=True)
    failing = Column(Integer, nullable=True)
    crashloop = Column(Integer, nullable=True)
    by_cluster = Column(JSON, nullable=True)


class LabRemediationConfig(Base):
    """Per-lab auto-remediation settings for gradual rollout."""
    __tablename__ = "lab_remediation_config"

    lab_code = Column(String(50), primary_key=True)
    execution_mode = Column(String(30), nullable=False, default="recommend_only")
    max_actions_per_hour = Column(Integer, nullable=False, default=5)
    enabled_by = Column(String(255), nullable=True)
    enabled_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
