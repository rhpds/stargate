import type {
  HealthStatus,
  DeploymentsDashboard,
  OverviewData,
  PoolsDashboard,
  ClustersDashboard,
  ClusterSummary,
  ClusterFailures,
  ClusterNodes,
  ClusterNamespacesData,
  LabDetail,
  EvaluationHistory,
  EventRecord,
  EventSummary,
  RemediationResponse,
  TrendsData,
  PipelineData,
  ReadinessData,
  ExecutiveSummary,
  PipelineStageDetail,
  StuckInstances,
  NodesPodsData,
  LabDeltas,
  FeedbackRequest,
  FeedbackResponse,
  SchedulerStatus,
  ScanHistory,
  RecommendationsData,
  EvaluationMatrix,
  LLMMetrics,
  LLMTimeline,
  LLMCallRecord,
  LLMEvaluation,
  LLMDrift,
  LLMConfig,
  LLMABTest,
  LLMGroundTruth,
  LLMAccuracy,
  LLMFeedbackRequest,
  RecommendationFeedbackRequest,
  DataMapping,
  LabsPipelineData,
  SecurityData,
  ForecastData,
  ApprovalQueueData,
  SandboxAPIData,
  ZeroTouchData,
  CapacityAnalysisData,
  FailureInterpretation,
  CatalogData,
  LabRemediationConfig,
  ExecutionMode,
  RemediationActivity,
  PoolDetailData,
  ProvisioningOverview,
  CatalogItemDetail,
} from './types';

const API_BASE = import.meta.env.VITE_API_URL || '';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    ...(options?.body ? { 'Content-Type': 'application/json' } : {}),
    ...(options?.headers as Record<string, string> || {}),
  };
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!response.ok) {
    if (response.status === 429) {
      const retryAfter = response.headers.get('Retry-After') || '60';
      throw new Error(`Rate limited — retry after ${retryAfter}s`);
    }
    if (response.status === 403) {
      if (response.url.includes('/admin/')) {
        throw new Error('Session expired — please refresh the page to re-authenticate');
      }
      throw new Error('Unauthorized — check API key');
    }
    if (response.status === 401) {
      window.location.reload();
      throw new Error('Session expired — redirecting to login');
    }
    if (response.status === 503) {
      throw new Error('Service temporarily unavailable — try again shortly');
    }
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (body.detail) detail = body.detail;
    } catch { /* ignore parse errors */ }
    throw new Error(`API error: ${response.status} ${detail}`);
  }
  return response.json();
}

export const api = {
  getHealth: () => request<HealthStatus>('/health'),

  // Dashboard v2
  getOverview: (sinceMinutes?: number, cluster?: string) => {
    const params = new URLSearchParams();
    if (sinceMinutes) params.set('since_minutes', String(sinceMinutes));
    if (cluster) params.set('cluster', cluster);
    const qs = params.toString();
    return request<OverviewData>(`/dashboard/overview${qs ? `?${qs}` : ''}`);
  },
  getDeploymentsDashboard: () => request<DeploymentsDashboard>('/dashboard/deployments'),
  getClustersDashboard: () => request<ClustersDashboard>('/dashboard/clusters'),
  getPoolsDashboard: () => request<PoolsDashboard>('/dashboard/pools'),
  getClusterNodes: (name: string) => request<ClusterNodes>(`/dashboard/nodes/${encodeURIComponent(name)}`),
  getLabDetail: (labCode: string) => request<LabDetail>(`/dashboard/lab/${encodeURIComponent(labCode)}`),

  getPipelineStage: (stageId: string) => request<PipelineStageDetail>(`/dashboard/pipeline/${encodeURIComponent(stageId)}`),
  getStuckInstances: () => request<StuckInstances>('/dashboard/stuck-instances'),
  getNodesPods: () => request<NodesPodsData>('/dashboard/nodes-pods'),
  getLabDeltas: () => request<LabDeltas>('/dashboard/lab-deltas'),

  getExecutiveSummary: () =>
    request<ExecutiveSummary>('/dashboard/executive-summary', { method: 'POST' }),

  getRemediation: (body: Record<string, string | undefined>) =>
    request<RemediationResponse>('/dashboard/remediation', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getFailureDetail: (failureClass: string, sinceMinutes?: number, cluster?: string) => {
    const params = new URLSearchParams();
    if (sinceMinutes) params.set('since_minutes', String(sinceMinutes));
    if (cluster) params.set('cluster', cluster);
    const qs = params.toString();
    return request<any>(`/dashboard/failure-detail/${encodeURIComponent(failureClass)}${qs ? `?${qs}` : ''}`);
  },

  // Core
  getLabHistory: (labCode: string, params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request<EvaluationHistory[]>(`/labs/${encodeURIComponent(labCode)}/history${qs}`);
  },
  getLabFailures: (labCode: string) => request<Record<string, number>>(`/labs/${encodeURIComponent(labCode)}/failures`),
  getClusterSummary: (name: string) => request<ClusterSummary>(`/clusters/${encodeURIComponent(name)}/summary`),
  getClusterFailures: (name: string) => request<ClusterFailures>(`/clusters/${encodeURIComponent(name)}/failures`),
  getClusterNamespaces: (name: string) => request<ClusterNamespacesData>(`/clusters/${encodeURIComponent(name)}/namespaces`),
  getEvents: (params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request<EventRecord[]>(`/events${qs}`);
  },
  getEventSummary: () => request<EventSummary>('/events/summary'),
  getConstraints: () => request<Record<string, Record<string, unknown>>>('/constraints'),
  getLabConstraints: (labId: string) => request<Record<string, unknown>>(`/constraints/${encodeURIComponent(labId)}`),
  getLabStatus: (labCode: string) => request<Record<string, unknown>>(`/integration/lab-status/${encodeURIComponent(labCode)}`),

  // Trends, pipeline, readiness
  getTrends: (params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request<TrendsData>(`/dashboard/trends${qs}`);
  },
  getPipeline: (params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request<PipelineData>(`/dashboard/pipeline${qs}`);
  },
  getReadiness: () => request<ReadinessData>('/dashboard/readiness'),

  // HITL feedback
  submitFeedback: (runId: string, body: FeedbackRequest) =>
    request<FeedbackResponse>(`/integration/feedback/${runId}`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // Security + Forecast
  getSecurity: () => request<SecurityData>('/dashboard/security'),
  getForecast: () => request<ForecastData>('/dashboard/forecast'),

  // Visual storytelling
  getActionStrip: () => request<any>('/dashboard/action-strip'),
  getAISummary: () => request<any>('/dashboard/ai-summary'),

  // AAP Provisioning
  getAAP: () => request<any>('/dashboard/aap'),

  // Platform Catalog
  getCatalog: () => request<CatalogData>('/dashboard/catalog'),

  // LLM Reasoning
  getRecommendationReasoning: () => request<any>('/dashboard/recommendation-reasoning', { method: 'POST' }),

  // Sandbox-API + ZeroTouch + Capacity
  getSandboxAPI: () => request<SandboxAPIData>('/dashboard/sandbox-api'),
  getZeroTouch: () => request<ZeroTouchData>('/dashboard/zerotouch'),
  getCapacityAnalysis: () => request<CapacityAnalysisData>('/dashboard/capacity-analysis', { method: 'POST' }),
  getFailureInterpretation: (body: { run_id: string; stage_id: string }) =>
    request<FailureInterpretation>('/dashboard/failure-interpretation', { method: 'POST', body: JSON.stringify(body) }),
  getTrendAnalysis: () => request<any>('/dashboard/trend-analysis', { method: 'POST' }),

  // Data Mapping
  getDataMapping: () => request<DataMapping>('/dashboard/data-mapping'),

  // Labs Pipeline
  getLabsPipeline: () => request<LabsPipelineData>('/dashboard/labs-pipeline'),

  // Recommendations
  getRecommendations: () => request<RecommendationsData>('/dashboard/provisioning-recommendations'),
  getEvaluationMatrix: (cluster?: string) => request<EvaluationMatrix>(`/dashboard/evaluation-matrix${cluster ? `?cluster=${cluster}` : ''}`),

  // LLM Admin
  getLLMMetrics: (cluster?: string) => request<LLMMetrics>(`/admin/llm/metrics${cluster ? `?cluster=${cluster}` : ''}`),
  getLLMTimeline: (hours?: number) => request<LLMTimeline>(`/admin/llm/metrics/timeline${hours ? `?hours=${hours}` : ''}`),
  getLLMRecent: (limit?: number, endpoint?: string, cluster?: string) => {
    const params = new URLSearchParams();
    if (limit) params.set('limit', String(limit));
    if (endpoint) params.set('endpoint', endpoint);
    if (cluster) params.set('cluster', cluster);
    const qs = params.toString();
    return request<LLMCallRecord[]>(`/admin/llm/recent${qs ? `?${qs}` : ''}`);
  },
  getLLMEvaluation: () => request<LLMEvaluation>('/admin/llm/evaluation'),
  getLLMDrift: () => request<LLMDrift>('/admin/llm/drift'),
  getLLMConfig: () => request<LLMConfig>('/admin/llm/config'),
  getLLMABTest: () => request<LLMABTest>('/admin/llm/ab-test'),
  getLLMGroundTruth: () => request<LLMGroundTruth>('/admin/llm/ground-truth'),
  getLLMAccuracy: () => request<LLMAccuracy>('/admin/llm/accuracy'),
  getProposedClassifications: () => request<{ proposals: Array<{ id: number; run_id: string; stage_id: string; proposed_class: string; confidence: number | null; reviewed: boolean; approved: boolean | null; original_message: string | null; proposed_at: string | null }> }>('/dashboard/proposed-classifications'),
  reviewClassification: (id: number, approved: boolean) =>
    request<{ id: number; status: string }>(`/dashboard/propose-classification/${id}/review`, {
      method: 'POST',
      body: JSON.stringify({ approved }),
    }),
  submitLLMFeedback: (body: LLMFeedbackRequest) =>
    request<{ id: number; status: string }>('/admin/llm/feedback', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  submitRecommendationFeedback: (body: RecommendationFeedbackRequest) =>
    request<{ status: string }>('/admin/remediation/feedback', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // Approval Queue
  getApprovalQueue: () => request<ApprovalQueueData>('/admin/approval-queue'),
  approveAction: (id: number) => request<{ id: number; status: string }>(`/admin/approval-queue/${id}/approve`, { method: 'POST' }),
  rejectAction: (id: number) => request<{ id: number; status: string }>(`/admin/approval-queue/${id}/reject`, { method: 'POST' }),

  // Remediation execution
  previewRemediation: (body: { namespace: string; failure_class: string; cluster: string; action_type?: string }) =>
    request<any>('/admin/remediation/preview', { method: 'POST', body: JSON.stringify(body) }),
  executeRemediation: (body: { namespace: string; failure_class: string; cluster: string; action_type?: string }) =>
    request<any>('/admin/remediation/execute', { method: 'POST', body: JSON.stringify(body) }),
  getRemediationRecommendations: (limit?: number, cluster?: string) => {
    const params = new URLSearchParams();
    if (limit) params.set('limit', String(limit));
    if (cluster) params.set('cluster', cluster);
    const qs = params.toString();
    return request<any>(`/admin/remediation/recommendations${qs ? `?${qs}` : ''}`);
  },

  // Admin
  getSchedulerStatus: () => request<SchedulerStatus>('/admin/scheduler/status'),
  getScanHistory: () => request<ScanHistory>('/admin/scan-history'),
  startScheduler: () => request<Record<string, unknown>>('/admin/scheduler/start', { method: 'POST' }),
  stopScheduler: () => request<Record<string, unknown>>('/admin/scheduler/stop', { method: 'POST' }),

  // Remediation Config
  getRemediationConfigs: () => request<{ configs: LabRemediationConfig[] }>('/admin/remediation/config'),
  getRemediationConfig: (labCode: string) => request<LabRemediationConfig>(`/admin/remediation/config/${encodeURIComponent(labCode)}`),
  updateRemediationConfig: (labCode: string, body: { execution_mode: ExecutionMode; max_actions_per_hour?: number; notes?: string }) =>
    request<LabRemediationConfig>(`/admin/remediation/config/${encodeURIComponent(labCode)}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  deleteRemediationConfig: (labCode: string) =>
    request<{ lab_code: string; deleted: boolean }>(`/admin/remediation/config/${encodeURIComponent(labCode)}`, {
      method: 'DELETE',
    }),
  getRemediationActivity: (limit = 50) => request<{ activity: RemediationActivity[] }>(`/admin/remediation/activity?limit=${limit}`),

  // Provisioning drill-down
  getPoolDetail: (poolName: string) => request<PoolDetailData>(`/dashboard/pool/${encodeURIComponent(poolName)}`),
  getProvisioningOverview: () => request<ProvisioningOverview>('/dashboard/provisioning'),
  getCatalogItemDetail: (itemName: string) => request<CatalogItemDetail>(`/dashboard/catalog/${encodeURIComponent(itemName)}`),

  // Historical trends
  getAAPTrends: (hours = 24) => request<{ timeline: any[] }>(`/dashboard/aap-trends?hours=${hours}`),
  getProvisioningTrends: (hours = 24) => request<{ timeline: any[] }>(`/dashboard/provisioning-trends?hours=${hours}`),
  getSandboxTrends: (hours = 24) => request<{ timeline: any[] }>(`/dashboard/sandbox-trends?hours=${hours}`),
  getMTTR: (hours = 168) => request<any>(`/dashboard/mttr?hours=${hours}`),
  getSummitReport: () => request<any>('/dashboard/summit-report'),
};
