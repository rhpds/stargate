import { useParams, Link } from 'react-router-dom';
import { useCatalogItemDetail } from '../api/hooks';
import type { CatalogItemDetail as CatalogItemDetailType } from '../api/types';

const STATUS_COLORS: Record<string, string> = {
  healthy: '#3E8635', started: '#3E8635', active: '#3E8635',
  low: '#F0AB00', provisioning: '#F0AB00',
  exhausted: '#C9190B',
};

function statusColor(status: string): string {
  if (status.includes('failed') || status.includes('error')) return '#C9190B';
  return STATUS_COLORS[status?.toLowerCase()] ?? '#6A6E73';
}

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
      <div className="text-2xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>{value}</div>
      <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">{label}</div>
    </div>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return <h2 className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">{children}</h2>;
}

export default function CatalogItemDetail() {
  const { name } = useParams<{ name: string }>();
  const { data, isLoading, isError } = useCatalogItemDetail(name || '');

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 animate-pulse space-y-6">
        <div className="h-8 bg-[#212121] rounded w-64" />
        <div className="grid grid-cols-4 gap-4">{[1,2,3,4].map(i => <div key={i} className="bg-[#212121] rounded-lg h-20" />)}</div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8">
        <Link to="/" className="text-[#73BCF7] text-sm hover:underline">Back to Health</Link>
        <p className="text-[#C9190B] mt-4">Failed to load catalog item.</p>
      </div>
    );
  }

  const item = data as CatalogItemDetailType;
  const stateEntries = Object.entries(item.instance_summary.by_state).sort(([,a], [,b]) => b - a);
  const complexity = (item as any).complexity;

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div>
        <Link to="/" className="text-[#73BCF7] text-sm hover:underline">Health</Link>
        <span className="text-[#6A6E73] text-sm mx-2">/</span>
        <span className="text-[#6A6E73] text-sm">Catalog</span>
      </div>

      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>{item.display_name || item.name}</h1>
        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-[#4394E5] text-white">{item.source}</span>
        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-[#2e2e2e] text-[#6A6E73]">{item.category}</span>
        {item.disabled && <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-[#C9190B] text-white">Disabled</span>}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Sessions" value={item.sessions || 0} />
        <MetricCard label="Complexity" value={complexity?.score ?? '--'} />
        <MetricCard label="Est. Provision" value={complexity?.estimated_provision_minutes ? `${complexity.estimated_provision_minutes}m` : '--'} />
        <MetricCard label="Instances" value={item.instance_summary.total} />
      </div>

      {item.description && (
        <section>
          <SectionHeader>Description</SectionHeader>
          <p className="text-sm text-[#d2d2d2]">{item.description}</p>
        </section>
      )}

      <section>
        <SectionHeader>Details</SectionHeader>
        <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
          <div><span className="text-[#6A6E73]">Provider: </span><span className="text-white">{item.provider || '--'}</span></div>
          <div><span className="text-[#6A6E73]">Created: </span><span className="text-white">{item.created ? new Date(item.created).toLocaleDateString() : '--'}</span></div>
          {item.lab_code && (
            <div><span className="text-[#6A6E73]">Lab: </span><Link to={`/lab/${encodeURIComponent(item.lab_code)}`} className="text-[#73BCF7] hover:underline">{item.lab_code}</Link></div>
          )}
          {item.labagator_status && (
            <div><span className="text-[#6A6E73]">Status: </span><span className="text-white">{item.labagator_status}</span></div>
          )}
        </div>
      </section>

      {item.linked_pools.length > 0 && (
        <section>
          <SectionHeader>Linked Pools ({item.linked_pools.length})</SectionHeader>
          <div className="flex flex-wrap gap-3">
            {item.linked_pools.map((pool) => (
              <Link key={pool.name} to={`/pool/${encodeURIComponent(pool.name)}`} className="bg-[#212121] border border-[#2e2e2e] rounded-lg px-4 py-3 flex items-center gap-3 cursor-pointer hover:border-[#555] transition">
                <span className="text-white text-sm font-medium">{pool.name}</span>
                <span className="text-xs text-[#6A6E73]">{pool.available} avail / {pool.min} min</span>
              </Link>
            ))}
          </div>
        </section>
      )}

      {stateEntries.length > 0 && (
        <section>
          <SectionHeader>Instance States</SectionHeader>
          <div className="flex flex-wrap gap-3">
            {stateEntries.map(([state, count]) => (
              <div key={state} className="bg-[#212121] border border-[#2e2e2e] rounded-lg px-4 py-2 flex items-center gap-2">
                <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: statusColor(state), color: '#fff' }}>{state}</span>
                <span className="text-white text-sm font-medium">{count}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {item.instances.length > 0 && (
        <section>
          <SectionHeader>Instances ({item.instances.length})</SectionHeader>
          <div className="space-y-1">
            {item.instances.map((inst) => (
              <div key={inst.anarchy_name} className="flex items-center gap-3 text-sm py-1">
                <span className="text-white truncate flex-1" title={inst.anarchy_name}>{inst.anarchy_name}</span>
                <span className="text-xs font-semibold px-2 py-0.5 rounded-full shrink-0" style={{ backgroundColor: statusColor(inst.state), color: '#fff' }}>{inst.state}</span>
                <span className="text-[#6A6E73] text-xs shrink-0">{inst.namespace}</span>
                {inst.console_url && <a href={inst.console_url} target="_blank" rel="noopener noreferrer" className="text-[#73BCF7] text-xs hover:underline shrink-0">Console</a>}
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
