import { useNavigate } from 'react-router-dom';
import {
  useOverview,
  useDeploymentsDashboard,
  useClustersDashboard,
  usePoolsDashboard,
} from '../api/hooks';
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
  pass: '#3E8635',
  healthy: '#3E8635',
  green: '#3E8635',
  active: '#3E8635',
  fail: '#C9190B',
  critical: '#C9190B',
  red: '#C9190B',
  exhausted: '#C9190B',
  warn: '#F0AB00',
  warning: '#F0AB00',
  yellow: '#F0AB00',
  low: '#F0AB00',
  degraded: '#F0AB00',
};

function statusColor(status: string): string {
  return STATUS_COLORS[status?.toLowerCase()] ?? '#6A6E73';
}

function labStatus(lab: Deployment): 'pass' | 'fail' | 'warn' {
  const s = lab.labagator_status?.toLowerCase() ?? '';
  if (s === 'active' || s === 'pass' || s === 'healthy' || s === 'green') return 'pass';
  if (s === 'fail' || s === 'critical' || s === 'red' || s === 'error') return 'fail';
  if (s === 'warn' || s === 'warning' || s === 'yellow' || s === 'degraded') return 'warn';
  // fallback: check instance failures
  if (lab.instances_failed > 0) return 'fail';
  return 'pass';
}

function cpuColor(cpu: number): string {
  if (cpu >= 80) return '#C9190B';
  if (cpu >= 60) return '#F0AB00';
  return '#3E8635';
}

/* ---- sub-components ---- */

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
      <div className="text-2xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>
        {value}
      </div>
      <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">{label}</div>
    </div>
  );
}

function StatsBar({ overview }: { overview: OverviewData }) {
  const clusterCount = overview.clusters.scans?.length ?? 0;
  const labHealthy = overview.labs.status_counts?.pass ?? overview.labs.status_counts?.healthy ?? 0;
  const labTotal = overview.labs.total;
  const passRate = pct(labHealthy, labTotal);
  const activeFailures = overview.errors.total_failures;
  const poolTotal = overview.pools.total;
  const poolHealthy = poolTotal - (overview.pools.exhausted ?? 0) - (overview.pools.low ?? 0);
  const poolHealth = pct(poolHealthy, poolTotal);

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <MetricCard label="Clusters" value={clusterCount} />
      <MetricCard label="Active Failures" value={activeFailures} />
      <MetricCard label="Pass Rate" value={passRate} />
      <MetricCard label="Pool Health" value={poolHealth} />
    </div>
  );
}

function LabGrid({ labs, navigate }: { labs: Deployment[]; navigate: (path: string) => void }) {
  if (labs.length === 0) {
    return <p className="text-[#6A6E73] text-sm">No labs evaluated yet — scanner will discover labs from cluster namespaces</p>;
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {labs.map((lab) => {
        const status = labStatus(lab);
        const displayName = lab.title || lab.lab_code;
        const failureInfo = lab.instances_failed > 0 ? `${lab.instances_failed} instance failures` : null;
        return (
          <div
            key={lab.lab_code}
            onClick={() => navigate(`/lab/${lab.lab_code}`)}
            className="border border-[#333] rounded-xl p-5 cursor-pointer hover:border-[#555] transition"
          >
            <div className="flex items-start justify-between mb-2">
              <div className="text-white font-medium text-sm truncate mr-2">{displayName}</div>
              <span
                className="text-xs font-semibold px-2 py-0.5 rounded-full shrink-0"
                style={{ backgroundColor: statusColor(status), color: '#fff' }}
              >
                {status}
              </span>
            </div>
            {status === 'fail' && failureInfo && (
              <div className="text-xs text-[#C9190B] mb-1">{failureInfo}</div>
            )}
            <div className="text-xs text-[#6A6E73]">{relativeTime(lab.last_scanned)}</div>
          </div>
        );
      })}
    </div>
  );
}

function ClusterStrip({
  scans,
  summaries,
  navigate,
}: {
  scans: ClusterScan[];
  summaries: ClusterSummary[];
  navigate: (path: string) => void;
}) {
  // Merge scan data (has CPU/VMs) with summary data (has evaluation stats)
  const merged = scans.map((scan) => {
    const summary = summaries.find((s) => s.cluster === scan.cluster);
    return { ...scan, evalHealthRate: summary?.health_rate ?? scan.health_rate };
  });

  if (merged.length === 0) {
    return <p className="text-[#6A6E73] text-sm">No clusters found.</p>;
  }

  return (
    <div className="flex gap-3 overflow-x-auto pb-2">
      {merged.map((c) => (
        <div
          key={c.cluster}
          onClick={() => navigate(`/cluster/${c.cluster}`)}
          className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 min-w-[180px] cursor-pointer hover:border-[#555] transition shrink-0"
        >
          <div className="text-white text-sm font-medium truncate mb-2">{c.cluster}</div>
          <div className="mb-2">
            <div className="flex items-center justify-between text-xs text-[#6A6E73] mb-1">
              <span>CPU</span>
              <span>{Math.round(c.avg_cpu_pct)}%</span>
            </div>
            <div className="w-full bg-[#333] h-1.5 rounded-full overflow-hidden">
              <div
                className="h-1.5 rounded-full"
                style={{
                  width: `${Math.min(c.avg_cpu_pct, 100)}%`,
                  backgroundColor: cpuColor(c.avg_cpu_pct),
                }}
              />
            </div>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-[#6A6E73]">{c.total_vms} VMs</span>
            <span
              className="font-semibold px-1.5 py-0.5 rounded text-[10px]"
              style={{
                backgroundColor: c.evalHealthRate >= 80 ? '#3E8635' : c.evalHealthRate >= 50 ? '#F0AB00' : '#C9190B',
                color: '#fff',
              }}
            >
              {Math.round(c.evalHealthRate)}%
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function PoolBadges({ pools }: { pools: PoolEntry[] }) {
  if (pools.length === 0) {
    return <p className="text-[#6A6E73] text-sm">No pools configured</p>;
  }

  return (
    <div className="flex flex-wrap gap-3">
      {pools.map((pool) => (
        <div
          key={pool.name}
          className="bg-[#212121] border border-[#2e2e2e] rounded-lg px-4 py-3 flex items-center gap-3"
        >
          <span className="text-white text-sm font-medium">{pool.name}</span>
          <span
            className="text-xs font-semibold px-2 py-0.5 rounded-full"
            style={{ backgroundColor: statusColor(pool.status), color: '#fff' }}
          >
            {pool.status}
          </span>
          <span className="text-xs text-[#6A6E73]">{pool.available} avail</span>
        </div>
      ))}
    </div>
  );
}

function FailureClassChart({ failures }: { failures: Record<string, number> }) {
  const entries = Object.entries(failures).sort(([, a], [, b]) => b - a);
  if (entries.length === 0) {
    return <p className="text-[#6A6E73] text-sm">No failure classes recorded.</p>;
  }
  const maxCount = entries[0]![1];

  return (
    <div className="space-y-2">
      {entries.map(([cls, count]) => (
        <div key={cls} className="flex items-center gap-3">
          <span className="text-xs text-[#6A6E73] w-40 truncate shrink-0" title={cls}>
            {cls}
          </span>
          <div className="flex-1 bg-[#333] h-4 rounded overflow-hidden">
            <div
              className="h-4 rounded"
              style={{
                width: `${(count / maxCount) * 100}%`,
                backgroundColor: '#C9190B',
              }}
            />
          </div>
          <span className="text-xs text-white font-medium w-8 text-right">{count}</span>
        </div>
      ))}
    </div>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">{children}</h2>
  );
}

/* ---- main page ---- */

export default function EcosystemHealth() {
  const navigate = useNavigate();
  const overview = useOverview();
  const deployments = useDeploymentsDashboard();
  const clusters = useClustersDashboard();
  const pools = usePoolsDashboard();

  const ov = overview.data as OverviewData | undefined;

  const isLoading = overview.isLoading || deployments.isLoading || clusters.isLoading || pools.isLoading;
  const hasError = overview.isError || deployments.isError || clusters.isError || pools.isError;

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 animate-pulse space-y-6">
        <div className="h-10 bg-[#212121] rounded w-64" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1,2,3,4].map(i => <div key={i} className="bg-[#212121] rounded-lg h-20" />)}
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

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-3xl font-bold text-white mb-2" style={{ fontFamily: 'Red Hat Display' }}>
          Ecosystem Health
        </h1>
        <p className="text-[#6A6E73]">Validation control plane -- labs, clusters, pools</p>
      </div>

      {/* 1. Stats bar */}
      {ov && <StatsBar overview={ov} />}

      {/* 2. Cluster Health Strip */}
      <section>
        <SectionHeader>Cluster Health</SectionHeader>
        <ClusterStrip
          scans={ov!.clusters.scans ?? []}
          summaries={cls.clusters ?? []}
          navigate={navigate}
        />
      </section>

      {/* 3. Top Failure Classes */}
      <section>
        <SectionHeader>Top Failure Classes</SectionHeader>
        {ov!.labs.total === 0 && Object.keys(ov!.errors.failure_classes ?? {}).length > 0 && (
          <p className="text-xs text-[#F0AB00] mb-3">Failures detected across cluster — lab mappings will connect these to specific demos</p>
        )}
        <FailureClassChart failures={ov!.errors.failure_classes ?? {}} />
      </section>

      {/* 4. Pool Availability */}
      <section>
        <SectionHeader>Pool Availability</SectionHeader>
        <PoolBadges pools={pls.pools ?? []} />
      </section>

      {/* 5. Labs */}
      <section>
        <SectionHeader>Labs ({(deps.labs ?? []).length})</SectionHeader>
        <LabGrid labs={deps.labs ?? []} navigate={navigate} />
      </section>
    </div>
  );
}
