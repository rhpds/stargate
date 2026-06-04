import { useNavigate } from 'react-router-dom';
import { useState } from 'react';
import {
  useOverview,
  useDeploymentsDashboard,
  useClustersDashboard,
  usePoolsDashboard,
  useStuckInstances,
} from '../api/hooks';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { OverviewData, DeploymentsDashboard, ClustersDashboard, PoolsDashboard, Deployment, ClusterScan, ClusterSummary, PoolEntry } from '../api/types';

/* ---- helpers ---- */

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '--';
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 0) return 'just now';
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function pct(n: number, d: number): string {
  if (d === 0) return '--';
  return `${Math.round((n / d) * 100)}%`;
}

const STATUS_COLORS: Record<string, string> = {
  pass: '#3E8635', healthy: '#3E8635', green: '#3E8635', active: '#3E8635',
  fail: '#C9190B', critical: '#C9190B', red: '#C9190B', exhausted: '#C9190B',
  warn: '#F0AB00', warning: '#F0AB00', yellow: '#F0AB00', low: '#F0AB00', degraded: '#F0AB00',
};

function statusColor(status: string): string {
  return STATUS_COLORS[status?.toLowerCase()] ?? '#6A6E73';
}

function labStatus(lab: Deployment): 'pass' | 'fail' | 'warn' {
  const s = lab.labagator_status?.toLowerCase() ?? '';
  if (s === 'active' || s === 'pass' || s === 'healthy' || s === 'green') return 'pass';
  if (s === 'fail' || s === 'critical' || s === 'red' || s === 'error') return 'fail';
  if (s === 'warn' || s === 'warning' || s === 'yellow' || s === 'degraded') return 'warn';
  if (lab.instances_failed > 0) return 'fail';
  return 'pass';
}

function cpuColor(cpu: number): string {
  if (cpu >= 80) return '#C9190B';
  if (cpu >= 60) return '#F0AB00';
  return '#3E8635';
}

const URGENCY_COLORS: Record<string, string> = {
  critical: '#C9190B', high: '#EC7A08', medium: '#F0AB00', low: '#6A6E73',
};

/* ---- sub-components ---- */

function MetricCard({ label, value, onClick }: { label: string; value: string | number; onClick?: () => void }) {
  return (
    <div
      className={`bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 ${onClick ? 'cursor-pointer hover:border-[#555] transition' : ''}`}
      onClick={onClick}
    >
      <div className="text-2xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>{value}</div>
      <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">{label}</div>
    </div>
  );
}

function SectionHeader({ children, onClick }: { children: React.ReactNode; onClick?: () => void }) {
  return (
    <h2
      className={`text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3 ${onClick ? 'cursor-pointer hover:text-white transition' : ''}`}
      onClick={onClick}
    >
      {children} {onClick && <span className="text-[#73BCF7]">&rarr;</span>}
    </h2>
  );
}

function ActionStrip({ actions }: { actions: Array<{ message: string; urgency: string; count?: number; link_tab?: string }> }) {
  const navigate = useNavigate();
  if (!actions || actions.length === 0) return null;
  return (
    <div className="flex gap-2 overflow-x-auto pb-1">
      {actions.map((a, i) => (
        <div
          key={i}
          onClick={() => a.link_tab && navigate(`/${a.link_tab}`)}
          className={`shrink-0 border rounded-lg px-3 py-2 text-xs flex items-center gap-2 ${a.link_tab ? 'cursor-pointer hover:border-[#555]' : ''}`}
          style={{ borderColor: URGENCY_COLORS[a.urgency] ?? '#2e2e2e' }}
        >
          <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: URGENCY_COLORS[a.urgency] ?? '#6A6E73' }} />
          <span className="text-[#d2d2d2]">{a.message}</span>
          {a.count && a.count > 1 && <span className="text-[#6A6E73]">({a.count})</span>}
        </div>
      ))}
    </div>
  );
}

function StatsBar({ overview, stuckCount, navigate }: { overview: OverviewData; stuckCount: number; navigate: (path: string) => void }) {
  const clusterCount = overview.clusters.scans?.length ?? 0;
  const labHealthy = overview.labs.status_counts?.pass ?? overview.labs.status_counts?.healthy ?? 0;
  const labTotal = overview.labs.total;
  const passRate = pct(labHealthy, labTotal);
  const activeFailures = overview.errors.total_failures;
  const poolTotal = overview.pools.total;
  const poolHealthy = poolTotal - (overview.pools.exhausted ?? 0) - (overview.pools.low ?? 0);
  const poolHealth = pct(poolHealthy, poolTotal);

  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
      <MetricCard label="Clusters" value={clusterCount} />
      <MetricCard label="Active Failures" value={activeFailures} onClick={() => navigate('/failures')} />
      <MetricCard label="Pass Rate" value={passRate} onClick={() => navigate('/pipeline')} />
      <MetricCard label="Pool Health" value={poolHealth} />
      {stuckCount > 0 && (
        <MetricCard label="Stuck Instances" value={stuckCount} onClick={() => navigate('/provisioning')} />
      )}
    </div>
  );
}

function LabGrid({ labs, navigate }: { labs: Deployment[]; navigate: (path: string) => void }) {
  if (labs.length === 0) {
    return <p className="text-[#6A6E73] text-sm">No labs evaluated yet</p>;
  }
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {labs.map((lab) => {
        const status = labStatus(lab);
        const displayName = lab.title || lab.lab_code;
        const failureInfo = lab.instances_failed > 0 ? `${lab.instances_failed} instance failures` : null;
        return (
          <div key={lab.lab_code} onClick={() => navigate(`/lab/${lab.lab_code}`)} className="border border-[#333] rounded-xl p-5 cursor-pointer hover:border-[#555] transition">
            <div className="flex items-start justify-between mb-2">
              <div className="text-white font-medium text-sm truncate mr-2">{displayName}</div>
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full shrink-0" style={{ backgroundColor: statusColor(status), color: '#fff' }}>{status}</span>
            </div>
            {status === 'fail' && failureInfo && <div className="text-xs text-[#C9190B] mb-1">{failureInfo}</div>}
            <div className="text-xs text-[#6A6E73]">{relativeTime(lab.last_scanned)}</div>
          </div>
        );
      })}
    </div>
  );
}

function ClusterStrip({ scans, summaries, navigate }: { scans: ClusterScan[]; summaries: ClusterSummary[]; navigate: (path: string) => void }) {
  const merged = scans.map((scan) => {
    const summary = summaries.find((s) => s.cluster === scan.cluster);
    return { ...scan, evalHealthRate: summary?.health_rate ?? scan.health_rate };
  });
  if (merged.length === 0) return <p className="text-[#6A6E73] text-sm">No clusters found.</p>;
  return (
    <div className="flex gap-3 overflow-x-auto pb-2">
      {merged.map((c) => (
        <div key={c.cluster} onClick={() => navigate(`/cluster/${c.cluster}`)} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 min-w-[180px] cursor-pointer hover:border-[#555] transition shrink-0">
          <div className="text-white text-sm font-medium truncate mb-2">{c.cluster}</div>
          <div className="mb-2">
            <div className="flex items-center justify-between text-xs text-[#6A6E73] mb-1"><span>CPU</span><span>{Math.round(c.avg_cpu_pct)}%</span></div>
            <div className="w-full bg-[#333] h-1.5 rounded-full overflow-hidden">
              <div className="h-1.5 rounded-full" style={{ width: `${Math.min(c.avg_cpu_pct, 100)}%`, backgroundColor: cpuColor(c.avg_cpu_pct) }} />
            </div>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-[#6A6E73]">{c.total_vms} VMs</span>
            <span className="font-semibold px-1.5 py-0.5 rounded text-[10px]" style={{ backgroundColor: c.evalHealthRate >= 80 ? '#3E8635' : c.evalHealthRate >= 50 ? '#F0AB00' : '#C9190B', color: '#fff' }}>{Math.round(c.evalHealthRate)}%</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function PoolBadges({ pools, navigate }: { pools: PoolEntry[]; navigate: (path: string) => void }) {
  if (pools.length === 0) return <p className="text-[#6A6E73] text-sm">No pools configured</p>;
  return (
    <div className="flex flex-wrap gap-3">
      {pools.map((pool) => (
        <div key={pool.name} onClick={() => navigate(`/pool/${encodeURIComponent(pool.name)}`)} className="bg-[#212121] border border-[#2e2e2e] rounded-lg px-4 py-3 flex items-center gap-3 cursor-pointer hover:border-[#555] transition">
          <span className="text-white text-sm font-medium">{pool.name}</span>
          <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: statusColor(pool.status), color: '#fff' }}>{pool.status}</span>
          <span className="text-xs text-[#6A6E73]">{pool.available} avail</span>
        </div>
      ))}
    </div>
  );
}

function FailureClassChart({ failures, navigate }: { failures: Record<string, number>; navigate: (path: string) => void }) {
  const entries = Object.entries(failures).sort(([, a], [, b]) => b - a);
  if (entries.length === 0) return <p className="text-[#6A6E73] text-sm">No failure classes recorded.</p>;
  const maxCount = entries[0]![1];
  return (
    <div className="space-y-2">
      {entries.map(([cls, count]) => (
        <div
          key={cls}
          onClick={() => navigate(`/failures?selected=${encodeURIComponent(cls)}`)}
          className="flex items-center gap-3 cursor-pointer hover:bg-[#1e1e1e] rounded px-1 -mx-1 transition"
        >
          <span className="text-xs text-[#6A6E73] w-40 truncate shrink-0" title={cls}>{cls}</span>
          <div className="flex-1 bg-[#333] h-4 rounded overflow-hidden">
            <div className="h-4 rounded" style={{ width: `${(count / maxCount) * 100}%`, backgroundColor: '#C9190B' }} />
          </div>
          <span className="text-xs text-white font-medium w-8 text-right">{count}</span>
        </div>
      ))}
    </div>
  );
}

/* ---- main page ---- */

export default function EcosystemHealth() {
  const navigate = useNavigate();
  const [aiExpanded, setAiExpanded] = useState(false);
  const overview = useOverview();
  const deployments = useDeploymentsDashboard();
  const clusters = useClustersDashboard();
  const pools = usePoolsDashboard();
  const stuck = useStuckInstances();

  const actionStrip = useQuery({ queryKey: ['action-strip'], queryFn: api.getActionStrip, refetchInterval: 30_000 });
  const aiSummary = useQuery({ queryKey: ['ai-summary'], queryFn: api.getAISummary, refetchInterval: 60_000 });

  const ov = overview.data as OverviewData | undefined;
  const isLoading = overview.isLoading || deployments.isLoading || clusters.isLoading || pools.isLoading;
  const hasError = overview.isError || deployments.isError || clusters.isError || pools.isError;

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 animate-pulse space-y-6">
        <div className="h-10 bg-[#212121] rounded w-64" />
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {[1,2,3,4,5].map(i => <div key={i} className="bg-[#212121] rounded-lg h-20" />)}
        </div>
        <div className="bg-[#212121] rounded-xl h-48" />
        <div className="bg-[#212121] rounded-xl h-32" />
      </div>
    );
  }

  if (hasError) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8">
        <p className="text-[#C9190B]">Failed to load ecosystem health data.</p>
      </div>
    );
  }

  const deps = deployments.data as DeploymentsDashboard;
  const cls = clusters.data as ClustersDashboard;
  const pls = pools.data as PoolsDashboard;
  const stuckCount = (stuck.data as any)?.total_stuck ?? 0;
  const actions = (actionStrip.data as any)?.actions ?? [];
  const aiData = aiSummary.data as any;

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-3xl font-bold text-white mb-2" style={{ fontFamily: 'Red Hat Display' }}>Ecosystem Health</h1>
        <p className="text-[#6A6E73]">Validation control plane — labs, clusters, pools, provisioning</p>
      </div>

      {/* Action Strip — urgent items */}
      {actions.length > 0 && <ActionStrip actions={actions} />}

      {/* Stats bar */}
      {ov && <StatsBar overview={ov} stuckCount={stuckCount} navigate={navigate} />}

      {/* AI Platform Intelligence */}
      {aiData && (aiData.top_issues?.length > 0 || aiData.recommendation) && (
        <section>
          <div
            onClick={() => setAiExpanded(!aiExpanded)}
            className="bg-[#1a1a2e] border border-[#2e2e4e] rounded-lg p-4 cursor-pointer hover:border-[#4e4e6e] transition"
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-[#4394E5] text-white">AI</span>
                <span className="text-sm text-white font-medium">Platform Intelligence</span>
              </div>
              <span className="text-[#6A6E73] text-xs">{aiExpanded ? 'collapse' : 'expand'}</span>
            </div>
            {!aiExpanded && aiData.recommendation && (
              <p className="text-xs text-[#8888aa] mt-2 truncate">{aiData.recommendation}</p>
            )}
            {aiExpanded && (
              <div className="mt-3 space-y-2">
                {aiData.top_issues?.map((issue: any, i: number) => (
                  <div key={i} className="text-xs text-[#d2d2d2] flex items-start gap-2">
                    <span className="w-1.5 h-1.5 rounded-full mt-1 shrink-0" style={{ backgroundColor: URGENCY_COLORS[issue.urgency] ?? '#6A6E73' }} />
                    <span>{issue.message}</span>
                  </div>
                ))}
                {aiData.recommendation && <p className="text-xs text-[#8888aa] mt-2 border-t border-[#2e2e4e] pt-2">{aiData.recommendation}</p>}
              </div>
            )}
          </div>
        </section>
      )}

      {/* Cluster Health Strip */}
      <section>
        <SectionHeader>Cluster Health</SectionHeader>
        <ClusterStrip scans={ov!.clusters.scans ?? []} summaries={cls.clusters ?? []} navigate={navigate} />
      </section>

      {/* Top Failure Classes */}
      <section>
        <SectionHeader onClick={() => navigate('/failures')}>Top Failure Classes</SectionHeader>
        {ov!.labs.total === 0 && Object.keys(ov!.errors.failure_classes ?? {}).length > 0 && (
          <p className="text-xs text-[#F0AB00] mb-3">Failures detected across cluster — lab mappings will connect these to specific demos</p>
        )}
        <FailureClassChart failures={ov!.errors.failure_classes ?? {}} navigate={navigate} />
      </section>

      {/* Pool Availability */}
      <section>
        <SectionHeader>Pool Availability</SectionHeader>
        <PoolBadges pools={pls.pools ?? []} navigate={navigate} />
      </section>

      {/* Provisioning */}
      {pls.provisioning && pls.provisioning.total > 0 && (
        <section>
          <SectionHeader onClick={() => navigate('/provisioning')}>Provisioning</SectionHeader>
          <div onClick={() => navigate('/provisioning')} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 cursor-pointer hover:border-[#555] transition">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <MetricCard label="Total Subjects" value={pls.provisioning.total} />
              <MetricCard label="Started" value={pls.provisioning.started} />
              <MetricCard label="Failed" value={pls.provisioning.failed} />
              <MetricCard label="Failure Rate" value={`${pls.provisioning.failure_rate}%`} />
            </div>
          </div>
        </section>
      )}

      {/* Labs */}
      <section>
        <SectionHeader>Labs ({(deps.labs ?? []).length})</SectionHeader>
        <LabGrid labs={deps.labs ?? []} navigate={navigate} />
      </section>
    </div>
  );
}
