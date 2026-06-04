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
import SearchBar from '../components/SearchBar';
import type { OverviewData, DeploymentsDashboard, ClustersDashboard, PoolsDashboard, Deployment, ClusterScan, ClusterSummary } from '../api/types';

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
function statusColor(s: string): string { return STATUS_COLORS[s?.toLowerCase()] ?? '#6A6E73'; }

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
    <div className={`bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 ${onClick ? 'cursor-pointer hover:border-[#555] transition' : ''}`} onClick={onClick}>
      <div className="text-2xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>{value}</div>
      <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">{label}</div>
    </div>
  );
}

function SectionHeader({ children, onClick, right }: { children: React.ReactNode; onClick?: () => void; right?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h2
        className={`text-xs text-[#6A6E73] uppercase tracking-wider font-bold ${onClick ? 'cursor-pointer hover:text-white transition' : ''}`}
        onClick={onClick}
      >
        {children} {onClick && <span className="text-[#73BCF7]">&rarr;</span>}
      </h2>
      {right}
    </div>
  );
}

/* ---- main page ---- */

export default function EcosystemHealth() {
  const navigate = useNavigate();
  const [aiExpanded, setAiExpanded] = useState(false);
  const [labSearch, setLabSearch] = useState('');
  const overview = useOverview();
  const deployments = useDeploymentsDashboard();
  const clusters = useClustersDashboard();
  const pools = usePoolsDashboard();
  const stuck = useStuckInstances();

  const actionStrip = useQuery({ queryKey: ['action-strip'], queryFn: api.getActionStrip, refetchInterval: 30_000 });
  const aiSummary = useQuery({ queryKey: ['ai-summary'], queryFn: api.getAISummary, refetchInterval: 60_000 });
  const mttrQuery = useQuery({ queryKey: ['mttr-overview'], queryFn: () => api.getMTTR(168), refetchInterval: 120_000 });

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
  void stuck;
  const actions = (actionStrip.data as any)?.actions ?? [];
  const aiData = aiSummary.data as any;

  const clusterCount = ov!.clusters.scans?.length ?? 0;
  const labHealthy = ov!.labs.status_counts?.pass ?? ov!.labs.status_counts?.healthy ?? 0;
  const labTotal = ov!.labs.total;
  const activeFailures = ov!.errors.total_failures;
  const poolTotal = ov!.pools.total;
  const poolExhausted = ov!.pools.exhausted ?? 0;
  const poolLow = ov!.pools.low ?? 0;
  const provTotal = pls.provisioning?.total ?? 0;
  const provFailed = pls.provisioning?.failed ?? 0;
  const mttrData = mttrQuery.data as any;
  const mttrValue = mttrData?.overall_mttr_minutes != null
    ? (mttrData.overall_mttr_minutes < 60 ? `${Math.round(mttrData.overall_mttr_minutes)}m` : `${(mttrData.overall_mttr_minutes / 60).toFixed(1)}h`)
    : '--';

  // Merge cluster scans with summaries
  const mergedClusters = (ov!.clusters.scans ?? []).map((scan: ClusterScan) => {
    const summary = (cls.clusters ?? []).find((s: ClusterSummary) => s.cluster === scan.cluster);
    return { ...scan, evalHealthRate: summary?.health_rate ?? scan.health_rate };
  });

  // Filter labs
  const allLabs = deps.labs ?? [];
  const filteredLabs = labSearch
    ? allLabs.filter(l => (l.title || l.lab_code).toLowerCase().includes(labSearch.toLowerCase()) || l.lab_code.toLowerCase().includes(labSearch.toLowerCase()))
    : allLabs;

  // Top 5 failure classes
  const failureEntries = Object.entries(ov!.errors.failure_classes ?? {}).sort(([,a], [,b]) => b - a).slice(0, 8);
  const maxFailure = failureEntries.length > 0 ? failureEntries[0]![1] : 1;

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-3xl font-bold text-white mb-1" style={{ fontFamily: 'Red Hat Display' }}>Ecosystem Health</h1>
        <p className="text-[#6A6E73] text-sm">Platform overview — {clusterCount} clusters, {labTotal} labs, {poolTotal} pools</p>
      </div>

      {/* Action Strip */}
      {actions.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {actions.map((a: any, i: number) => (
            <div key={i} onClick={() => a.link_tab && navigate(`/${a.link_tab}`)}
              className={`shrink-0 border rounded-lg px-3 py-2 text-xs flex items-center gap-2 ${a.link_tab ? 'cursor-pointer hover:border-[#555]' : ''}`}
              style={{ borderColor: URGENCY_COLORS[a.urgency] ?? '#2e2e2e' }}>
              <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: URGENCY_COLORS[a.urgency] ?? '#6A6E73' }} />
              <span className="text-[#d2d2d2]">{a.message}</span>
            </div>
          ))}
        </div>
      )}

      {/* Stats bar */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
        <MetricCard label="Clusters" value={clusterCount} />
        <MetricCard label="Failures" value={activeFailures} onClick={() => navigate('/failures')} />
        <MetricCard label="Pass Rate" value={pct(labHealthy, labTotal)} onClick={() => navigate('/pipeline')} />
        <MetricCard label="Pools" value={`${poolTotal - poolExhausted - poolLow}/${poolTotal}`} onClick={() => navigate('/capacity')} />
        <MetricCard label="Provisioning" value={provTotal > 0 ? `${provFailed} failed` : '--'} onClick={() => navigate('/provisioning')} />
        <MetricCard label="Avg Recovery" value={mttrValue} onClick={() => navigate('/trends')} />
      </div>

      {/* AI Summary */}
      {aiData && (aiData.top_issues?.length > 0 || aiData.recommendation) && (
        <div onClick={() => setAiExpanded(!aiExpanded)} className="bg-[#1a1a2e] border border-[#2e2e4e] rounded-lg p-4 cursor-pointer hover:border-[#4e4e6e] transition">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-[#4394E5] text-white">AI</span>
              <span className="text-sm text-white font-medium">Platform Intelligence</span>
            </div>
            <span className="text-[#6A6E73] text-xs">{aiExpanded ? 'collapse' : 'expand'}</span>
          </div>
          {!aiExpanded && aiData.recommendation && <p className="text-xs text-[#8888aa] mt-2 truncate">{aiData.recommendation}</p>}
          {aiExpanded && (
            <div className="mt-3 space-y-2">
              {aiData.top_issues?.map((issue: any, i: number) => (
                <div key={i} className="text-xs text-[#d2d2d2] flex items-start gap-2">
                  <span className="w-1.5 h-1.5 rounded-full mt-1 shrink-0" style={{ backgroundColor: URGENCY_COLORS[issue.urgency] ?? '#6A6E73' }} />
                  <span>{issue.message}</span>
                </div>
              ))}
              {aiData.recommendation && <p className="text-xs text-[#8888aa] border-t border-[#2e2e4e] pt-2 mt-2">{aiData.recommendation}</p>}
            </div>
          )}
        </div>
      )}

      {/* Cluster Health */}
      <section>
        <SectionHeader>Cluster Health</SectionHeader>
        <div className="flex gap-3 overflow-x-auto pb-2">
          {mergedClusters.map((c) => (
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
      </section>

      {/* Top Failures (compact) */}
      <section>
        <SectionHeader onClick={() => navigate('/failures')}>Top Failures</SectionHeader>
        <div className="space-y-1.5">
          {failureEntries.map(([cls, count]) => (
            <div key={cls} onClick={() => navigate(`/failures?selected=${encodeURIComponent(cls)}`)} className="flex items-center gap-3 cursor-pointer hover:bg-[#1e1e1e] rounded px-1 -mx-1 transition">
              <span className="text-xs text-[#6A6E73] w-40 truncate shrink-0" title={cls}>{cls}</span>
              <div className="flex-1 bg-[#333] h-3 rounded overflow-hidden">
                <div className="h-3 rounded" style={{ width: `${(count / maxFailure) * 100}%`, backgroundColor: '#C9190B' }} />
              </div>
              <span className="text-xs text-white font-medium w-8 text-right">{count}</span>
            </div>
          ))}
          {Object.keys(ov!.errors.failure_classes ?? {}).length > 8 && (
            <div onClick={() => navigate('/failures')} className="text-xs text-[#73BCF7] cursor-pointer hover:underline mt-1">
              View all {Object.keys(ov!.errors.failure_classes ?? {}).length} failure classes &rarr;
            </div>
          )}
        </div>
      </section>

      {/* Labs */}
      <section>
        <SectionHeader right={<SearchBar placeholder="Search labs..." value={labSearch} onChange={setLabSearch} className="w-64" />}>
          Labs ({filteredLabs.length})
        </SectionHeader>
        {filteredLabs.length === 0 ? (
          <p className="text-[#6A6E73] text-sm">{labSearch ? 'No labs match your search.' : 'No labs evaluated yet.'}</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {filteredLabs.map((lab) => {
              const status = labStatus(lab);
              const displayName = lab.title || lab.lab_code;
              return (
                <div key={lab.lab_code} onClick={() => navigate(`/lab/${lab.lab_code}`)} className="border border-[#333] rounded-lg p-4 cursor-pointer hover:border-[#555] transition">
                  <div className="flex items-start justify-between mb-1">
                    <div className="text-white font-medium text-sm truncate mr-2">{displayName}</div>
                    <span className="text-xs font-semibold px-2 py-0.5 rounded-full shrink-0" style={{ backgroundColor: statusColor(status), color: '#fff' }}>{status}</span>
                  </div>
                  {lab.instances_failed > 0 && <div className="text-xs text-[#C9190B] mb-0.5">{lab.instances_failed} instance failures</div>}
                  <div className="text-xs text-[#6A6E73]">{relativeTime(lab.last_scanned)}</div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
