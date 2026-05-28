import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';

vi.mock('../../api/hooks', () => ({
  useHealth: () => ({ data: { status: 'ok', service: 'stargate' } }),
  useOverview: () => ({
    data: {
      timestamp: '2026-05-07T12:00:00Z',
      labs: { total: 94, with_sessions: 42, status_counts: { planning: 80, in_development: 14 } },
      clusters: { total: 9, healthy: 6, warning: 2, critical: 1, scans: [] },
      pools: { total: 164, exhausted: 12, low: 8, summit_pools: [] },
      provisioning: { total: 145, started: 81, failed: 49, failure_rate: 33.8, by_state: {} },
      errors: { total_failures: 506, top_class: 'route_missing', failure_classes: { route_missing: 200 }, systemic: 0 },
    },
    isLoading: false,
    isError: false,
  }),
  useDeploymentsDashboard: () => ({
    data: {
      timestamp: '2026-05-07T12:00:00Z',
      total_labs: 2,
      labs_with_pools: 1,
      pools_with_issues: 1,
      labagator_available: true,
      pools: {
        'zt-rhel': { pool: 'zt-rhel', health: 92.1, evaluations: 100, passed: 80, failed: 8, warned: 12, instances: 50, clusters: ['ocpv06'], top_failure_class: null, failure_classes: {} },
      },
      labs: [
        { lab_code: 'LB1088', title: 'Code Red', labagator_status: 'in_development', cloud: 'CNV', deploy_mode: 'per_attendee', ci_name: 'summit-2026.lb1088', pool: 'zt-rhel', sessions: 2, provisioned: 3, capacity: 5, pool_available: 2, pool_count: 1, demolition_status: 'pass', schedule_dates: ['Day 1'], total_attendees: 40, instances_started: 3, instances_failed: 0, instances_total: 3, instances_destroying: 0, agnosticv_tags: [], last_scanned: null },
        { lab_code: 'LB1237', title: 'RHEL 10', labagator_status: 'planning', cloud: 'CNV', deploy_mode: null, ci_name: '', pool: null, sessions: 0, provisioned: 0, capacity: 0, pool_available: 0, pool_count: 0, demolition_status: 'none', schedule_dates: [], total_attendees: 0, instances_started: 0, instances_failed: 0, instances_total: 0, instances_destroying: 0, agnosticv_tags: [], last_scanned: null },
      ],
    },
    isLoading: false,
    isError: false,
  }),
  usePoolsDashboard: () => ({ data: null, isLoading: false }),
  useLabDetail: () => ({ data: null, isLoading: false }),
  useReadiness: () => ({
    data: {
      summit_date: '2026-06-15',
      days_until_summit: 39,
      overall_readiness_pct: 62.5,
      labs_provisioned: 12,
      labs_target: 94,
      labs_with_sessions: 42,
      gates: {
        provisioning: { status: 'red', value: 12, target: 94, pct: 12.8 },
        health: { status: 'green', value: 95.2, target: 90 },
        sessions: { status: 'yellow', value: 42, target: 94, pct: 44.7 },
        infrastructure: { status: 'green', value: 0, detail: '6 healthy, 0 critical' },
      },
      escalated_events: 0,
    },
    isLoading: false,
  }),
  useEventSummary: () => ({ data: { total_events: 50, filtered: 10, delivered: 40, systemic: 2, escalated: 0, by_type: {}, filter_rate: 20 }, isLoading: false }),
  useTrends: () => ({ data: { evaluation_trend: [], cluster_health_trend: [], failure_trend: [] }, isLoading: false }),
  usePipeline: () => ({
    data: {
      stages: [
        { stage_id: 'namespace-ready', order: 3, pass: 100, fail: 1, warn: 0, total: 101, health_rate: 99.0 },
        { stage_id: 'deployment-ready', order: 4, pass: 90, fail: 5, warn: 2, total: 97, health_rate: 94.8 },
      ],
      lab_code: null,
      cluster_name: null,
    },
    isLoading: false,
  }),
  useEvents: () => ({ data: [], isLoading: false }),
  useFeedback: () => ({ mutate: vi.fn(), isPending: false, isSuccess: false, isError: false }),
  useRecommendations: () => ({ data: { recommendations: [], total: 0, critical: 0, high: 0, medium: 0, generated_at: '' }, isLoading: false }),
  useEvaluationMatrix: () => ({ data: { labs: [], stages: [], matrix: {} }, isLoading: false }),
  useSecurity: () => ({ data: null, isLoading: false }),
  useForecast: () => ({ data: null, isLoading: false }),
  useRemediation: () => ({ mutate: vi.fn(), isPending: false, isSuccess: false, isError: false, data: null }),
  useLLMFeedback: () => ({ mutate: vi.fn(), isPending: false, isSuccess: false, isError: false }),
  useExecutiveSummary: () => ({ mutate: vi.fn(), isPending: false, isSuccess: false, isError: false, data: null }),
  useNodesPods: () => ({ data: null, isLoading: false }),
  useStuckInstances: () => ({ data: null, isLoading: false }),
  useLabDeltas: () => ({ data: null, isLoading: false }),
  useSchedulerStatus: () => ({ data: null, isLoading: false }),
  useClustersDashboard: () => ({ data: null, isLoading: false }),
}));

import Dashboard from '../../pages/Dashboard';

function renderDashboard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><Dashboard /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Dashboard', () => {
  it('renders page title', () => {
    renderDashboard();
    expect(screen.getByText('Summit 2026 Readiness')).toBeInTheDocument();
  });

  it('renders toggle group with all tabs', () => {
    renderDashboard();
    expect(screen.getByText('Labs')).toBeInTheDocument();
    expect(screen.getByText('Clusters')).toBeInTheDocument();
    expect(screen.getByText('Pools')).toBeInTheDocument();
    expect(screen.getByText('Errors')).toBeInTheDocument();
    expect(screen.getByText('Pipeline')).toBeInTheDocument();
    expect(screen.getByText('Nodes & Pods')).toBeInTheDocument();
    expect(screen.getByText('Recommendations (0)')).toBeInTheDocument();
    expect(screen.getByText('Security')).toBeInTheDocument();
    expect(screen.getByText('Forecast')).toBeInTheDocument();
  });

  it('renders labs view by default with lab codes', () => {
    renderDashboard();
    expect(screen.getByText('LB1088')).toBeInTheDocument();
    expect(screen.getByText('LB1237')).toBeInTheDocument();
  });

  it('renders overview stat cards', () => {
    renderDashboard();
    expect(screen.getByText('Total Labs')).toBeInTheDocument();
    expect(screen.getByText('94')).toBeInTheDocument();
  });

  it('renders readiness banner', () => {
    renderDashboard();
    expect(screen.getByText('39')).toBeInTheDocument();
    expect(screen.getByText('days to Summit')).toBeInTheDocument();
  });

  it('renders recent activity section', () => {
    renderDashboard();
    expect(screen.getByText('Recent Activity')).toBeInTheDocument();
  });
});
