import { describe, it, expect } from 'vitest';
import type {
  Deployment,
  DeploymentsDashboard,
  PoolEntry,
  PoolEvalSummary,
  ClusterScan,
  OverviewData,
  HealthStatus,
  ExecutionMode,
  LabRemediationConfig,
} from '../../api/types';

describe('Type definitions', () => {
  it('Deployment has control-plane fields', () => {
    const d: Deployment = {
      lab_code: 'test',
      title: 'Test Lab',
      labagator_status: 'ready',
      cloud: 'CNV',
      deploy_mode: null,
      ci_name: 'test.ci',
      pool: null,
      sessions: 0,
      provisioned: 0,
      capacity: 0,
      pool_available: 0,
      pool_count: 0,
      total_instances: 0,
      demolition_status: 'none',
      demolition_completed: 0,
      demolition_failed: 0,
      demolition_total: 0,
      instances_started: 1,
      instances_total: 1,
      instances_failed: 0,
      instances_destroying: 0,
      schedule_dates: [],
      session_dates: [],
      schedule_status: 'no_sessions',
      next_action: { action: null, urgency: null, detail: '' },
      agnosticv_tags: [],
      agnosticv_timeout: null,
      agnosticv_config: null,
      last_scanned: null,
    };
    expect(d.lab_code).toBe('test');
    expect(d.instances_started).toBe(1);
  });

  it('PoolEntry and PoolEvalSummary are distinct types', () => {
    const pool: PoolEntry = { name: 'p1', available: 5, ready: 3, min: 10, status: 'healthy' };
    const evalSummary: PoolEvalSummary = {
      pool: 'p1', health: 95, evaluations: 100, passed: 90, failed: 5, warned: 5,
      instances: 10, clusters: ['c1'], top_failure_class: null, failure_classes: {},
    };
    expect(pool.name).toBe('p1');
    expect(evalSummary.pool).toBe('p1');
  });

  it('ExecutionMode has three valid values', () => {
    const modes: ExecutionMode[] = ['recommend_only', 'low_risk_auto', 'full_auto'];
    expect(modes).toHaveLength(3);
  });

  it('OverviewData pools has all_pools field', () => {
    const overview: OverviewData = {
      timestamp: '', labs: { total: 0, with_sessions: 0, status_counts: {} },
      clusters: { total: 0, healthy: 0, warning: 0, critical: 0, scans: [] },
      pools: { total: 0, exhausted: 0, low: 0, all_pools: [] },
      provisioning: { total: 0, started: 0, failed: 0, failure_rate: 0, by_state: {} },
      errors: { total_failures: 0, top_class: null, failure_classes: {}, systemic: 0 },
    };
    expect(overview.pools.all_pools).toEqual([]);
  });
});
