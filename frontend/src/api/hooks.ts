import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import type { FeedbackRequest, ExecutionMode } from './types';
import { useTimeRange } from '../components/TimeRangeContext';

export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: api.getHealth, refetchInterval: 30_000 });
}

export function useOverview() {
  const { range } = useTimeRange();
  const sinceMinutes = Math.round(range.ms / 60000);
  return useQuery({ queryKey: ['overview', sinceMinutes], queryFn: () => api.getOverview(sinceMinutes), refetchInterval: 30_000 });
}

export function useDeploymentsDashboard() {
  return useQuery({ queryKey: ['deployments'], queryFn: api.getDeploymentsDashboard, refetchInterval: 30_000 });
}

export function useClustersDashboard() {
  return useQuery({ queryKey: ['dashboard-clusters'], queryFn: api.getClustersDashboard, refetchInterval: 30_000 });
}

export function usePoolsDashboard() {
  return useQuery({ queryKey: ['dashboard-pools'], queryFn: api.getPoolsDashboard, refetchInterval: 30_000 });
}

export function useClusterNodes(name: string) {
  return useQuery({
    queryKey: ['cluster-nodes', name],
    queryFn: () => api.getClusterNodes(name),
    enabled: !!name,
  });
}

export function useLabDetail(labCode: string) {
  return useQuery({
    queryKey: ['lab-detail', labCode],
    queryFn: () => api.getLabDetail(labCode),
    enabled: !!labCode,
  });
}

export function useClusterSummary(name: string) {
  return useQuery({
    queryKey: ['cluster-summary', name],
    queryFn: () => api.getClusterSummary(name),
    enabled: !!name,
  });
}

export function useClusterFailures(name: string) {
  return useQuery({
    queryKey: ['cluster-failures', name],
    queryFn: () => api.getClusterFailures(name),
    enabled: !!name,
  });
}

export function useEvents(params?: Record<string, string>) {
  return useQuery({
    queryKey: ['events', params],
    queryFn: () => api.getEvents(params),
    refetchInterval: 15_000,
  });
}

export function useEventSummary() {
  return useQuery({ queryKey: ['event-summary'], queryFn: api.getEventSummary, refetchInterval: 15_000 });
}

export function useNodesPods() {
  return useQuery({
    queryKey: ['nodes-pods'],
    queryFn: api.getNodesPods,
    refetchInterval: 15_000,
  });
}

export function useStuckInstances() {
  return useQuery({
    queryKey: ['stuck-instances'],
    queryFn: api.getStuckInstances,
    refetchInterval: 30_000,
  });
}

export function usePipelineStage(stageId: string) {
  return useQuery({
    queryKey: ['pipeline-stage', stageId],
    queryFn: () => api.getPipelineStage(stageId),
    enabled: !!stageId,
  });
}

export function useLabDeltas() {
  return useQuery({
    queryKey: ['lab-deltas'],
    queryFn: api.getLabDeltas,
    refetchInterval: 30_000,
  });
}

export function useExecutiveSummary() {
  return useMutation({
    mutationFn: () => api.getExecutiveSummary(),
  });
}

export function useRemediation() {
  return useMutation({
    mutationFn: (body: Record<string, string | undefined>) =>
      api.getRemediation(body),
  });
}

export function useTrends(params?: Record<string, string>) {
  return useQuery({
    queryKey: ['trends', params],
    queryFn: () => api.getTrends(params),
    refetchInterval: 60_000,
  });
}

export function usePipeline(params?: Record<string, string>) {
  return useQuery({
    queryKey: ['pipeline', params],
    queryFn: () => api.getPipeline(params),
    refetchInterval: 30_000,
  });
}

export function useReadiness() {
  return useQuery({
    queryKey: ['readiness'],
    queryFn: api.getReadiness,
    refetchInterval: 30_000,
  });
}

export function useFeedback() {
  return useMutation({
    mutationFn: ({ runId, body }: { runId: string; body: FeedbackRequest }) =>
      api.submitFeedback(runId, body),
  });
}

export function useScanHistory() {
  return useQuery({
    queryKey: ['scan-history'],
    queryFn: api.getScanHistory,
    refetchInterval: 30_000,
  });
}

export function useApprovalQueue() {
  return useQuery({ queryKey: ['approval-queue'], queryFn: api.getApprovalQueue, refetchInterval: 10_000 });
}

export function useApproveAction() {
  return useMutation({ mutationFn: (id: number) => api.approveAction(id) });
}

export function useRejectAction() {
  return useMutation({ mutationFn: (id: number) => api.rejectAction(id) });
}

export function useSecurity() {
  return useQuery({ queryKey: ['security'], queryFn: api.getSecurity, refetchInterval: 60_000 });
}

export function useForecast() {
  return useQuery({ queryKey: ['forecast'], queryFn: api.getForecast, refetchInterval: 60_000 });
}

export function useRecommendations() {
  return useQuery({
    queryKey: ['recommendations'],
    queryFn: api.getRecommendations,
    refetchInterval: 30_000,
  });
}

export function useEvaluationMatrix() {
  return useQuery({
    queryKey: ['evaluation-matrix'],
    queryFn: api.getEvaluationMatrix,
    refetchInterval: 30_000,
  });
}

export function useLLMMetrics() {
  return useQuery({ queryKey: ['llm-metrics'], queryFn: api.getLLMMetrics, refetchInterval: 30_000 });
}

export function useLLMTimeline(hours?: number) {
  return useQuery({ queryKey: ['llm-timeline', hours], queryFn: () => api.getLLMTimeline(hours), refetchInterval: 60_000 });
}

export function useLLMRecent(limit?: number) {
  return useQuery({ queryKey: ['llm-recent', limit], queryFn: () => api.getLLMRecent(limit), refetchInterval: 15_000 });
}

export function useLLMEvaluation() {
  return useQuery({ queryKey: ['llm-evaluation'], queryFn: api.getLLMEvaluation, refetchInterval: 30_000 });
}

export function useLLMFeedback() {
  return useMutation({
    mutationFn: (body: import('./types').LLMFeedbackRequest) => api.submitLLMFeedback(body),
  });
}

export function useLLMDrift() {
  return useQuery({ queryKey: ['llm-drift'], queryFn: api.getLLMDrift, refetchInterval: 60_000 });
}

export function useDataMapping() {
  return useQuery({ queryKey: ['data-mapping'], queryFn: api.getDataMapping, refetchInterval: 60_000 });
}

export function useLabsPipeline() {
  return useQuery({ queryKey: ['labs-pipeline'], queryFn: api.getLabsPipeline, refetchInterval: 30_000 });
}

export function useLLMConfig() {
  return useQuery({ queryKey: ['llm-config'], queryFn: api.getLLMConfig });
}

export function useLLMABTest() {
  return useQuery({ queryKey: ['llm-ab-test'], queryFn: api.getLLMABTest, refetchInterval: 30_000 });
}

export function useLLMGroundTruth() {
  return useQuery({ queryKey: ['llm-ground-truth'], queryFn: api.getLLMGroundTruth, refetchInterval: 60_000 });
}

export function useLLMAccuracy() {
  return useQuery({ queryKey: ['llm-accuracy'], queryFn: api.getLLMAccuracy, refetchInterval: 60_000 });
}

export function useSchedulerStatus() {
  return useQuery({
    queryKey: ['scheduler-status'],
    queryFn: api.getSchedulerStatus,
    refetchInterval: 5_000,
  });
}

export function useSchedulerAction() {
  return useMutation({
    mutationFn: (action: 'start' | 'stop') =>
      action === 'start' ? api.startScheduler() : api.stopScheduler(),
  });
}

export function useRecommendationReasoning() {
  return useMutation({ mutationFn: api.getRecommendationReasoning });
}

export function useCatalog() {
  return useQuery({ queryKey: ['catalog'], queryFn: api.getCatalog, refetchInterval: 60_000 });
}

export function useSandboxAPI() {
  return useQuery({ queryKey: ['sandbox-api'], queryFn: api.getSandboxAPI, refetchInterval: 30_000 });
}

export function useZeroTouch() {
  return useQuery({ queryKey: ['zerotouch'], queryFn: api.getZeroTouch, refetchInterval: 60_000 });
}

export function useCapacityAnalysis() {
  return useMutation({ mutationFn: api.getCapacityAnalysis });
}

export function useFailureInterpretation() {
  return useMutation({ mutationFn: (body: { run_id: string; stage_id: string }) => api.getFailureInterpretation(body) });
}

export function useTrendAnalysis() {
  return useMutation({ mutationFn: api.getTrendAnalysis });
}

export function useRemediationConfigs() {
  return useQuery({ queryKey: ['remediation-configs'], queryFn: api.getRemediationConfigs, refetchInterval: 30_000 });
}

export function useRemediationActivity() {
  return useQuery({ queryKey: ['remediation-activity'], queryFn: () => api.getRemediationActivity(), refetchInterval: 15_000 });
}

export function useRemediationConfigMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ labCode, mode, maxActionsPerHour, notes }: { labCode: string; mode: ExecutionMode; maxActionsPerHour?: number; notes?: string }) =>
      api.updateRemediationConfig(labCode, { execution_mode: mode, max_actions_per_hour: maxActionsPerHour, notes }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['remediation-configs'] }),
  });
}

export function useRemediationConfigDelete() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (labCode: string) => api.deleteRemediationConfig(labCode),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['remediation-configs'] }),
  });
}
