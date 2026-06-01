export interface HealthStatus {
  status: string;
  service: string;
}

// --- Deployments ---

export interface Deployment {
  lab_code: string;
  title: string;
  labagator_status: string;
  cloud: string;
  deploy_mode: string | null;
  ci_name: string;
  pool: string | null;
  sessions: number;
  provisioned: number;
  capacity: number;
  pool_available: number;
  pool_count: number;
  total_instances: number;
  demolition_status: 'pass' | 'fail' | 'none';
  demolition_completed: number;
  demolition_failed: number;
  demolition_total: number;
  instances_started: number;
  instances_total: number;
  instances_failed: number;
  instances_destroying: number;
  schedule_dates: string[];
  session_dates: string[];
  schedule_status: 'active' | 'completed' | 'upcoming' | 'no_sessions';
  next_action: { action: string | null; urgency: string | null; detail: string };
  agnosticv_tags: string[];
  agnosticv_timeout: number | null;
  agnosticv_config: string | null;
  last_scanned: string | null;
}

export interface PoolEvalSummary {
  pool: string;
  health: number | null;
  evaluations: number;
  passed: number;
  failed: number;
  warned: number;
  instances: number;
  clusters: string[];
  top_failure_class: string | null;
  failure_classes: Record<string, number>;
}

export interface DeploymentsDashboard {
  timestamp: string;
  total_labs: number;
  provisioned_count: number;
  with_sessions: number;
  labagator_available: boolean;
  pools: Record<string, PoolEvalSummary>;
  labs: Deployment[];
}

// --- Overview ---

export interface ClusterScan {
  cluster: string;
  avg_cpu_pct: number;
  hot_nodes: number;
  sandbox_active: number;
  sandbox_failing: number;
  sandbox_crashloop: number;
  total_vms: number;
  vms_per_node: number;
  health_rate: number;
  status: string;
  dns_warnings: number;
  issues: string[];
}

export interface OverviewData {
  timestamp: string;
  labs: { total: number; with_sessions: number; status_counts: Record<string, number> };
  clusters: { total: number; healthy: number; warning: number; critical: number; scans: ClusterScan[] };
  pools: { total: number; exhausted: number; low: number; all_pools: PoolEntry[] };
  provisioning: { total: number; started: number; failed: number; failure_rate: number; by_state: Record<string, number> };
  errors: { total_failures: number; top_class: string | null; failure_classes: Record<string, number>; systemic: number };
}

// --- Pools ---

export interface PoolEntry {
  name: string;
  available: number;
  ready: number;
  min: number;
  status: string;
}

export interface PoolsDashboard {
  timestamp: string;
  total_pools: number;
  pools: PoolEntry[];
  summit_pools: PoolEntry[];
  provisioning: {
    total: number;
    started: number;
    failed: number;
    failure_rate: number;
    by_state: Record<string, number>;
  };
}

// --- Clusters Dashboard ---

export interface ClusterSummary {
  cluster: string;
  total_evaluations: number;
  passed: number;
  failed: number;
  warned: number;
  health_rate: number;
  failure_classes: Record<string, number>;
  labs_seen: number;
  labs_failing: number;
  recent_failure_events: number;
  systemic_events: number;
}

export interface ClustersDashboard {
  timestamp: string;
  clusters: ClusterSummary[];
}

// --- Cluster Nodes ---

export interface ClusterNodes {
  cluster: string;
  timestamp: string;
  nodes: number;
  compute_nodes: number;
  avg_cpu_pct: number;
  hot_nodes: number;
  total_vms: number;
  vms_per_node: number;
  sandbox_active: number;
  sandbox_failing: number;
  sandbox_crashloop: number;
  ocp4_cluster_labs: number;
  health_rate: number;
  dns_warnings: number;
  status: string;
  issues: string[];
}

// --- Lab Detail ---

export interface LabagatorInfo {
  title: string;
  status: string;
  cloud: string;
  deploy_mode: string | null;
  ci_name: string | null;
  lead_developer: string | null;
  rhdp_developer: string | null;
  ops_assigned: string | null;
}

export interface LabSession {
  session_date: string;
  start_time: string;
  end_time: string;
  room: string;
  attendees: number;
  status: string;
}

export interface EvaluationHistory {
  run_id: string;
  stage_id: string;
  outcome: string;
  failure_class: string | null;
  message: string | null;
  evaluated_at: string | null;
  cluster_name: string | null;
}

export interface DemolitionJob {
  id: number | string;
  name: string;
  status: string;
  workers: number;
  completed: number;
  failed: number;
  total: number;
}

export interface LabDetail {
  lab_code: string;
  labagator: LabagatorInfo | null;
  labagator_sessions: LabSession[];
  stargate: {
    evaluation_count: number;
    history: EvaluationHistory[];
    failure_classes: Record<string, number>;
    last_passing_run: Record<string, unknown> | null;
  };
  demolition: DemolitionJob[];
  constraints: Record<string, unknown> | null;
  recent_events: EventRecord[];
}

// --- Events ---

export interface EventRecord {
  event_id: string;
  event_type: string;
  timestamp: string;
  run_id: string;
  stage_id: string | null;
  lab_code: string | null;
  cluster_name: string | null;
  outcome: string | null;
  failure_class: string | null;
  message: string | null;
  priority: number;
  metadata: Record<string, unknown>;
  filtered: boolean;
  correlated: boolean;
  systemic: boolean;
  deduplicated: boolean;
  blast_radius: Record<string, unknown> | null;
}

export interface EventSummary {
  total_events: number;
  filtered: number;
  delivered: number;
  systemic: number;
  escalated: number;
  by_type: Record<string, number>;
  filter_rate: number;
}

// --- Remediation ---

// --- Security + Forecast ---

export interface SecurityData {
  clusters: Array<{ cluster: string; status: string }>;
  known_cves: Array<{ cve_id: string; name: string; severity: string; cvss: number; affected: string; status: string; mitigation: string; applied: boolean }>;
  ocp_versions_behind: Record<string, string>;
  recommendations: Array<{ priority: string; action: string; time: string }>;
}

export interface ForecastData {
  generated_at: string;
  forecast_hours: Array<{ hour: string; timestamp: string; deployments_starting: number; labs: string[]; total_instances: number; estimated_new_workloads: number; pools_available_now: number; risk: string }>;
  cluster_projections: Array<{ cluster: string; current_cpu: number; current_vms: number; current_sandboxes: number; capacity_warning: boolean }>;
  summary: { peak_hour: string | null; peak_instances: number; high_risk_hours: number };
}

// --- Approval Queue ---

export interface PendingActionItem {
  id: number;
  action_type: string;
  target: string;
  confidence: number;
  proposed_at: string | null;
  parameters: Record<string, unknown>;
}

export interface ApprovalQueueData {
  pending: PendingActionItem[];
}

export interface LLMFeedbackRequest {
  llm_metric_id?: number;
  endpoint: string;
  helpful: boolean;
  notes?: string;
}

export interface RemediationResponse {
  failure_class: string;
  lab_code: string;
  cluster: string;
  context_type: string;
  found: boolean;
  message: string;
  recommended_actions: string[];
  runbook_steps: string[];
  confidence: string;
  confidence_score?: number;
  llm_analysis: string | null;
  llm_model: string | null;
  llm_metric_id?: number;
  llm_latency_ms?: number;
  llm_tokens?: number;
  evidence_summary: string;
}

// --- Cluster Detail ---

export interface ClusterFailures {
  [failureClass: string]: number;
}

// --- Trends ---

export interface TrendBucket {
  timestamp: string;
  pass: number;
  fail: number;
  warn: number;
  health_rate: number;
}

export interface ClusterHealthTrend {
  timestamp: string;
  cluster: string;
  health_rate: number;
  avg_cpu_pct: number;
}

export interface FailureTrendBucket {
  timestamp: string;
  failure_class: string;
  count: number;
}

export interface TrendsData {
  evaluation_trend: TrendBucket[];
  cluster_health_trend: ClusterHealthTrend[];
  failure_trend: FailureTrendBucket[];
}

// --- Pipeline ---

export interface PipelineStage {
  stage_id: string;
  order: number;
  pass: number;
  fail: number;
  warn: number;
  total: number;
  health_rate: number | null;
}

export interface PipelineData {
  stages: PipelineStage[];
  lab_code: string | null;
  cluster_name: string | null;
}

// --- Readiness ---

export interface ReadinessGate {
  status: 'red' | 'yellow' | 'green';
  value: number;
  target?: number;
  pct?: number;
  detail?: string;
}

export interface ReadinessData {
  summit_date: string;
  event_date?: string;
  event_name?: string;
  days_until_summit: number;
  days_until_event?: number | null;
  overall_readiness_pct: number;
  labs_provisioned: number;
  labs_target: number;
  labs_with_sessions: number;
  gates: {
    provisioning: ReadinessGate;
    health: ReadinessGate;
    sessions: ReadinessGate;
    infrastructure: ReadinessGate;
    capacity?: ReadinessGate;
    sandbox_api?: ReadinessGate;
  };
  escalated_events: number;
}

// --- Nodes & Pods ---

export interface NodesPodCluster {
  cluster: string;
  status: string;
  nodes: number;
  compute_nodes: number;
  avg_cpu: number;
  hot_nodes: number;
  total_vms: number;
  vms_per_node: number;
  sandbox_active: number;
  sandbox_failing: number;
  crashloops: number;
  ocp4_labs: number;
  new_failures: number;
  recovered: number;
  recent_failures: { pod: string; status: string }[];
  sandbox_by_type: Record<string, number>;
  evaluations: {
    total: number;
    passed: number;
    failed: number;
    health_rate: number;
    labs_seen: number;
    labs_failing: number;
    top_failures: Record<string, number>;
  };
}

export interface NodesPodsData {
  clusters: NodesPodCluster[];
  totals: {
    nodes: number;
    compute_nodes: number;
    total_vms: number;
    sandboxes: number;
    failing: number;
    crashloops: number;
  };
}

// --- Stuck Instances ---

export interface StuckInstance {
  name: string;
  state: string;
  console_url: string;
  api_url: string;
}

export interface StuckInstances {
  by_lab: Record<string, StuckInstance[]>;
  total_stuck: number;
  platform_stuck: {
    destroy_failed: number;
    provision_failed: number;
    provision_error: number;
    start_error: number;
    stop_failed: number;
    stopped: number;
  };
}

// --- Pipeline Stage Detail ---

export interface PipelineStageDetail {
  stage_id: string;
  total: number;
  passed: number;
  warned: number;
  failed: number;
  health_rate: number;
  failure_classes: Record<string, number>;
  clusters_affected: Record<string, number>;
  recent_evaluations: {
    run_id: string;
    outcome: string;
    failure_class: string | null;
    message: string | null;
    cluster_name: string | null;
    lab_code: string | null;
    evaluated_at: string | null;
  }[];
}

// --- Lab Deltas ---

export interface LabDeltas {
  deltas: Record<string, {
    instances?: 'up' | 'down';
    capacity?: 'up' | 'down';
    smoke?: 'up' | 'down';
    status?: 'up';
  }>;
  previous_time: string | null;
  current_time: string;
  labs_changed: number;
}

// --- Executive Summary ---

export interface ExecutiveSummary {
  evidence: string;
  analysis: string;
  model: string;
  readiness: ReadinessData;
  timestamp: string;
  lab_counts?: {
    ready: number;
    at_risk: number;
    blocked: number;
    no_sessions: number;
  };
}

// --- Feedback ---

export interface FeedbackRequest {
  action_taken?: string;
  worked?: boolean;
  correct_classification?: boolean;
  corrected_class?: string;
  notes?: string;
  reviewed_by?: string;
}

export interface FeedbackResponse {
  run_id: string;
  evaluations_updated: number;
  feedback: FeedbackRequest;
}

// --- Admin / Scheduler ---

export interface SchedulerWorker {
  cluster: string;
  running: boolean;
  ticks: number;
  errors: number;
  offset: number;
  tier1_interval: number;
  tier2_interval: number;
  tier3_interval: number;
  last_node_scan: number | null;
  last_pod_scan: number | null;
  last_ns_scan: number | null;
  active_sandboxes: number;
  failing_sandboxes: number;
  avg_cpu?: number;
  hot_nodes?: number;
  node_status?: string;
  total_vms?: number;
  vms_per_node?: number;
  crashloops?: number;
  new_failures?: number;
  recovered?: number;
  ns_scanned?: number;
  ns_available?: number;
  recent_failures?: { pod: string; status: string }[];
}

export interface SchedulerStatus {
  running: boolean;
  workers: SchedulerWorker[];
  babylon?: {
    total_pools: number;
    exhausted: number;
    low: number;
    total_subjects: number;
    started: number;
    failed: number;
  } | null;
  worker_count?: number;
  last_scan?: string | null;
  scan_files?: number;
  available_clusters?: string[];
  unavailable_clusters?: string[];
  latest_scans?: Record<string, {
    scan_time: string;
    status: string;
    avg_cpu_pct: number | null;
    total_vms: number;
    vms_per_node: number;
    health_rate: number;
    sandbox_active: number;
    sandbox_failing: number;
    sandbox_crashloop: number;
    hot_nodes: number | null;
    issues: string[];
    source?: 'live' | string;
  }>;
}

export interface ScanHistoryEntry {
  timestamp: string;
  clusters: Record<string, {
    status: string;
    avg_cpu_pct: number | null;
    total_vms: number;
    vms_per_node: number;
    health_rate: number;
    sandbox_active: number;
    sandbox_failing: number;
  }>;
}

export interface ScanHistory {
  timeline: ScanHistoryEntry[];
  total_files: number;
}

// --- Recommendations ---

export interface Recommendation {
  type: string;
  urgency: 'critical' | 'high' | 'medium' | 'low';
  recommendation: string;
  generated_at?: string;
  confidence_score?: number;
  confidence_reason?: string;
  evidence?: Record<string, unknown>;
  decision_logic?: string;
  rubric_context?: {
    stages_evaluated: number;
    stages_passing: number;
    stages_failing: number;
    failures: Array<{
      stage_id: string;
      outcome: string;
      failure_class: string | null;
      criteria_failed: string[];
      criteria_passed: string[];
      evaluated_at: string | null;
    }>;
  };
  constraint_violations?: Array<{
    type: string;
    expected: string;
    actual: string;
    severity: string;
    detail: string;
    correlated_rubric_stage: string | null;
    correlated_failure_class: string | null;
  }>;
  action?: string;
  lab_code?: string;
  title?: string;
  cluster?: string;
  pool_name?: string;
  sessions?: number;
  schedule_dates?: string[];
  attendees?: number;
  stuck_count?: number;
  cpu?: number;
  vms_per_node?: number;
  available?: number;
  min_required?: number;
}

export interface RecommendationsData {
  recommendations: Recommendation[];
  total: number;
  critical: number;
  high: number;
  medium: number;
  generated_at: string;
}

export interface EvaluationMatrix {
  labs: string[];
  stages: string[];
  matrix: Record<string, Record<string, string>>;
}

// --- LLM Admin ---

export interface LLMMetrics {
  total_calls: number;
  total_tokens: number;
  total_cost_estimate: number;
  calls_by_endpoint: Record<string, number>;
  avg_latency_ms: Record<string, number>;
  p95_latency_ms: Record<string, number>;
  error_rate: number;
  errors_by_type: Record<string, number>;
  tokens_by_endpoint: Record<string, number>;
  calls_last_hour: number;
  calls_last_24h: number;
  avg_confidence: number | null;
  period: string;
}

export interface LLMTimeline {
  hours: string[];
  calls: number[];
  latency_avg: number[];
  tokens: number[];
  errors: number[];
}

export interface LLMCallRecord {
  id: number;
  endpoint: string;
  model: string;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  cost_estimate: number | null;
  latency_ms: number;
  success: boolean;
  finish_reason: string | null;
  error_type: string | null;
  confidence: number | null;
  lab_code: string | null;
  cluster_name: string | null;
  failure_class: string | null;
  response_preview: string | null;
  called_at: string;
}

export interface LLMEvaluation {
  total_proposals: number;
  reviewed: number;
  approved: number;
  rejected: number;
  pending_review: number;
  approval_rate: number;
  avg_confidence_approved: number;
  avg_confidence_rejected: number;
  confidence_calibration: Array<{ bucket: string; total: number; approved: number; rate: number }>;
  top_corrections: Array<{ class: string; count: number }>;
}

export interface LLMDrift {
  status: 'stable' | 'drifting' | 'degraded';
  alerts: Array<{ type: string; severity: string; message: string }>;
  recent: { calls: number; avg_latency: number; p95_latency: number; error_rate: number; avg_tokens: number; total_cost: number; period: string; approval_rate: number | null };
  prior: { calls: number; avg_latency: number; p95_latency: number; error_rate: number; avg_tokens: number; total_cost: number; period: string; approval_rate: number | null };
}

export interface LLMConfig {
  model: string;
  api_endpoint: string;
  prompts: Record<string, { max_tokens: number; temperature: number; version: string | null; timeout: number }>;
}

export interface LLMABTest {
  versions: Record<string, { calls: number; success_rate: number; avg_latency_ms: number; p95_latency_ms: number; avg_tokens: number; total_cost: number }>;
}

export interface LLMGroundTruth {
  total: number;
  entries: Array<{ stage_id: string; expected_class: string; confidence: number | null; source: string; confirmed_at: string | null; run_id: string }>;
}

export interface DataMappingSource {
  connected: boolean;
  key: string;
  [key: string]: unknown;
}

export interface DataMappingLab {
  lab_code: string;
  title: string;
  sources: Record<string, DataMappingSource>;
  join_health: string;
  connected_count: number;
  issues: string[];
}

export interface DataMappingJoinKey {
  from_source: string;
  to_source: string;
  key: string;
  reliability: 'high' | 'medium' | 'low';
}

export interface DataMapping {
  labs: DataMappingLab[];
  summary: { total_labs: number; fully_connected: number; partially_connected: number; disconnected: number };
  join_keys: DataMappingJoinKey[];
}

export interface LLMAccuracy {
  total: number;
  correct: number;
  accuracy: number;
  by_class: Record<string, { correct: number; total: number }>;
}

export interface LabPipelineStageStatus {
  outcome: 'pass' | 'fail' | 'warn' | null;
  failure_class: string | null;
  evaluated_at: string | null;
}

export interface LabPipelineEntry {
  lab_code: string;
  title: string;
  cluster: string | null;
  sessions: number;
  stages: Record<string, LabPipelineStageStatus | null>;
  pass_count: number;
  warn_count: number;
  fail_count: number;
  health_pct: number;
  furthest_stage: string | null;
}

export interface LabsPipelineData {
  labs: LabPipelineEntry[];
  stage_order: string[];
  total_labs: number;
}

// --- Sandbox-API ---

export interface SandboxAPIData {
  api_healthy: boolean;
  replicas_desired: number;
  replicas_ready: number;
  pod_statuses: Array<{ name: string; phase: string; restarts: number }>;
  api_version: string | null;
  total_sandboxes: number;
  active: number;
  failing: number;
  crashloop: number;
  by_cluster: Record<string, { active: number; failing: number; crashloop: number }>;
  timestamp: string;
}

// --- ZeroTouch ---

export interface ZeroTouchData {
  available: boolean;
  catalog_total: number;
  catalog_active: number;
  catalog_items: Array<{ name: string; display_name: string; category: string; provider: string; disabled: boolean }>;
  workshops: Record<string, { seats_total: number; seats_available: number; seats_claimed: number }>;
  workshop_count: number;
  timestamp: string;
}

// --- Pool Velocity ---

export interface PoolVelocityEntry {
  handles_per_hour: number;
  trend: 'depleting' | 'stable' | 'recovering';
  data_points: number;
  available: number;
  exhaustion_hours: number | null;
}

// --- Workload Complexity ---

export interface WorkloadComplexityEntry {
  score: number;
  estimated_minutes: number;
}

// --- Capacity Analysis ---

export interface CapacityAnalysisData {
  pool_velocities: Record<string, PoolVelocityEntry>;
  workload_complexities: Record<string, WorkloadComplexityEntry>;
  llm_analysis: {
    pool_risks: Array<{ pool: string; available: number; velocity: number; exhaustion_hours: number; severity: string }>;
    capacity_conflicts: Array<{ lab: string; complexity: number; cluster_cpu: number; issue: string }>;
    scheduling_risks: Array<{ hour: string; labs: string[]; combined_complexity: number; risk: string }>;
    actions: Array<{ priority: number; action: string; target: string; urgency: string }>;
    summary: string;
  } | null;
  llm_error: string | null;
  evidence_summary: string;
}

// --- Platform Catalog ---

export interface CatalogItem {
  name: string;
  display_name: string;
  source: 'babylon' | 'zerotouch' | 'agnosticv';
  category: string;
  description: string;
  disabled: boolean;
  provider: string;
  created: string;
  lab_code: string | null;
  sessions?: number;
  labagator_status?: string;
  complexity?: { score: number; estimated_provision_minutes: number };
}

export interface CatalogData {
  total: number;
  active: number;
  disabled: number;
  by_category: Record<string, number>;
  sources: string[];
  items: CatalogItem[];
}

// --- Failure Interpretation ---

export interface FailureInterpretation {
  interpretation: string;
  failure_class: string;
  stage_id: string;
  llm_model?: string;
}

export type ExecutionMode = 'recommend_only' | 'low_risk_auto' | 'full_auto';

export interface LabRemediationConfig {
  lab_code: string;
  display_name?: string;
  execution_mode: ExecutionMode;
  max_actions_per_hour: number;
  enabled_by?: string;
  enabled_at?: string;
  notes?: string;
  configured?: boolean;
}

export interface RemediationActivity {
  id: number;
  action_type: string;
  target: string;
  status: string;
  proposed_by?: string;
  approved_by?: string;
  executed_at?: string;
  created_at?: string;
  result?: string;
}
