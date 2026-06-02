import { useParams, Link } from 'react-router-dom';
import { useClusterNodes, useClusterFailures, useClusterNamespaces } from '../api/hooks';
import type { ClusterNodes, ClusterNamespace } from '../api/types';

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

function MetricCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
      <div className="text-2xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>{value}</div>
      <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">{label}</div>
      {sub && <div className="text-xs text-[#6A6E73] mt-0.5">{sub}</div>}
    </div>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return <h2 className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">{children}</h2>;
}

function NamespaceTable({ namespaces }: { namespaces: ClusterNamespace[] }) {
  if (namespaces.length === 0) {
    return <p className="text-[#6A6E73] text-sm">No namespaces found.</p>;
  }

  return (
    <div className="space-y-0.5">
      <div className="grid grid-cols-[1fr_80px_80px_80px_80px_150px_100px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
        <span>Namespace</span>
        <span className="text-right">Evals</span>
        <span className="text-right">Passed</span>
        <span className="text-right">Failed</span>
        <span className="text-right">Health</span>
        <span>Top Failure</span>
        <span>Last Seen</span>
      </div>
      {namespaces.map((ns) => (
        <div
          key={ns.namespace}
          className={`grid grid-cols-[1fr_80px_80px_80px_80px_150px_100px] gap-3 items-center py-1.5 rounded ${
            ns.is_ecosystem ? 'border-l-2 border-l-[#EE0000]' : 'opacity-50'
          }`}
        >
          <span className="text-sm text-white font-medium truncate">
            {ns.namespace}
            {ns.is_ecosystem && <span className="ml-1 text-[10px] text-[#EE0000] font-bold uppercase">eco</span>}
          </span>
          <span className="text-sm text-white text-right">{ns.total}</span>
          <span className="text-sm text-[#3E8635] text-right">{ns.passed}</span>
          <span className={`text-sm text-right font-bold ${ns.failed > 0 ? 'text-[#C9190B]' : 'text-[#6A6E73]'}`}>{ns.failed}</span>
          <span className="text-right">
            <span
              className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
              style={{
                backgroundColor: ns.health_rate >= 80 ? '#3E8635' : ns.health_rate >= 50 ? '#F0AB00' : '#C9190B',
                color: '#fff',
              }}
            >
              {Math.round(ns.health_rate)}%
            </span>
          </span>
          <span className="text-xs text-[#8A8D90] truncate" title={ns.top_failure || ''}>{ns.top_failure || '--'}</span>
          <span className="text-xs text-[#6A6E73]">{relativeTime(ns.last_evaluated)}</span>
        </div>
      ))}
    </div>
  );
}

function FailureDistribution({ failures }: { failures: Record<string, number> }) {
  const entries = Object.entries(failures).sort(([, a], [, b]) => b - a);
  if (entries.length === 0) {
    return <p className="text-[#6A6E73] text-sm">No failures recorded.</p>;
  }

  const maxCount = entries[0]![1];

  return (
    <div className="space-y-1.5">
      {entries.map(([cls, count]) => (
        <div key={cls} className="flex items-center gap-3">
          <span className="text-xs text-white w-[180px] truncate shrink-0" title={cls}>{cls}</span>
          <div className="flex-1 bg-[#333] h-4 rounded overflow-hidden">
            <div
              className="h-4 rounded"
              style={{ width: `${(count / maxCount) * 100}%`, backgroundColor: '#C9190B' }}
            />
          </div>
          <span className="text-xs text-white font-bold w-10 text-right shrink-0">{count}</span>
        </div>
      ))}
    </div>
  );
}

export default function ClusterDetail() {
  const { name } = useParams<{ name: string }>();
  const nodes = useClusterNodes(name || '');
  const failures = useClusterFailures(name || '');
  const nsData = useClusterNamespaces(name || '');

  const n = nodes.data as ClusterNodes | undefined;
  const failureMap = (failures.data || {}) as Record<string, number>;
  const namespaces = (nsData.data?.namespaces || []) as ClusterNamespace[];

  const ecoCount = namespaces.filter((ns) => ns.is_ecosystem).length;
  const failingCount = namespaces.filter((ns) => ns.failed > 0).length;
  const totalFailures = Object.values(failureMap).reduce((s, c) => s + c, 0);

  const isLoading = nodes.isLoading || nsData.isLoading;

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div>
        <Link to="/" className="text-xs text-[#6A6E73] hover:text-white transition">Health</Link>
        <span className="text-xs text-[#6A6E73] mx-2">/</span>
        <span className="text-xs text-white">{name}</span>
        <h1 className="text-3xl font-bold text-white mt-2" style={{ fontFamily: 'Red Hat Display' }}>
          {name}
        </h1>
        <p className="text-[#6A6E73]">Cluster overview and namespace breakdown</p>
      </div>

      {isLoading ? (
        <p className="text-[#6A6E73]">Loading...</p>
      ) : (
        <>
          {/* Metric cards */}
          {n && (
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
              <MetricCard label="Nodes" value={n.nodes} sub={`${n.compute_nodes} compute`} />
              <MetricCard label="CPU" value={`${Math.round(n.avg_cpu_pct)}%`} sub={`${n.hot_nodes} hot nodes`} />
              <MetricCard label="VMs" value={n.total_vms} sub={`${n.vms_per_node} per node`} />
              <MetricCard label="Health Rate" value={`${Math.round(n.health_rate)}%`} />
              <MetricCard label="Namespaces" value={namespaces.length} sub={`${ecoCount} ecosystem`} />
              <MetricCard label="Failing" value={failingCount} sub={`${totalFailures} total failures`} />
            </div>
          )}

          {/* Issues */}
          {n && n.issues && n.issues.length > 0 && (
            <section>
              <SectionHeader>Cluster Issues</SectionHeader>
              <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 space-y-1">
                {n.issues.map((issue, i) => (
                  <div key={i} className="text-sm text-[#F0AB00] flex items-start gap-2">
                    <span className="text-[#F0AB00] shrink-0">!</span>
                    <span>{issue}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Namespace table */}
          <section>
            <SectionHeader>Namespaces ({namespaces.length})</SectionHeader>
            <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 overflow-x-auto">
              <NamespaceTable namespaces={namespaces} />
            </div>
          </section>

          {/* Failure classes */}
          <section>
            <SectionHeader>Failure Classes ({Object.keys(failureMap).length})</SectionHeader>
            <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
              <FailureDistribution failures={failureMap} />
            </div>
          </section>
        </>
      )}
    </div>
  );
}
