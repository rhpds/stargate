import { useParams, Link } from 'react-router-dom';
import { usePoolDetail } from '../api/hooks';
import type { PoolDetailData, ProvisioningInstance } from '../api/types';

const STATUS_COLORS: Record<string, string> = {
  healthy: '#3E8635', pass: '#3E8635', started: '#3E8635', active: '#3E8635',
  low: '#F0AB00', warning: '#F0AB00', provisioning: '#F0AB00', starting: '#F0AB00',
  exhausted: '#C9190B', fail: '#C9190B',
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

function InstanceTable({ instances }: { instances: ProvisioningInstance[] }) {
  if (instances.length === 0) return <p className="text-[#6A6E73] text-sm">No instances</p>;
  return (
    <div className="space-y-0.5">
      <div className="grid grid-cols-[1fr_100px_80px_200px_120px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
        <span>Subject</span>
        <span>Lab</span>
        <span>State</span>
        <span>Namespace</span>
        <span>Links</span>
      </div>
      {instances.map((inst) => (
        <div key={inst.anarchy_name} className="grid grid-cols-[1fr_100px_80px_200px_120px] gap-3 items-center py-1.5">
          <span className="text-sm text-white truncate" title={inst.anarchy_name}>{inst.anarchy_name.split('.').pop()}</span>
          <Link to={`/lab/${encodeURIComponent(inst.lab_code || '')}`} className="text-sm text-[#73BCF7] hover:underline truncate">{inst.lab_code || '--'}</Link>
          <span className="text-xs font-semibold px-2 py-0.5 rounded-full text-center" style={{ backgroundColor: statusColor(inst.state), color: '#fff' }}>{inst.state}</span>
          <span className="text-xs text-[#6A6E73] truncate">{inst.namespace}</span>
          <div className="flex gap-2">
            {inst.console_url && <a href={inst.console_url} target="_blank" rel="noopener noreferrer" className="text-xs text-[#73BCF7] hover:underline">Console</a>}
            {inst.api_url && <a href={inst.api_url} target="_blank" rel="noopener noreferrer" className="text-xs text-[#73BCF7] hover:underline">API</a>}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function PoolDetail() {
  const { name } = useParams<{ name: string }>();
  const { data, isLoading, isError } = usePoolDetail(name || '');

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
        <p className="text-[#C9190B] mt-4">Failed to load pool data.</p>
      </div>
    );
  }

  const pool = data as PoolDetailData;
  const stateEntries = Object.entries(pool.instance_summary.by_state).sort(([,a], [,b]) => b - a);

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div>
        <Link to="/" className="text-[#73BCF7] text-sm hover:underline">Health</Link>
        <span className="text-[#6A6E73] text-sm mx-2">/</span>
        <span className="text-[#6A6E73] text-sm">Pool</span>
      </div>

      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>{pool.name}</h1>
        <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: statusColor(pool.status), color: '#fff' }}>{pool.status}</span>
        {pool.is_summit && <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-[#EE0000] text-white">Summit</span>}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Available" value={pool.available} />
        <MetricCard label="Ready" value={pool.ready} />
        <MetricCard label="Min Required" value={pool.min} />
        <MetricCard label="Instances" value={pool.instance_summary.total} />
      </div>

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

      {pool.consuming_labs.length > 0 && (
        <section>
          <SectionHeader>Consuming Labs ({pool.consuming_labs.length})</SectionHeader>
          <div className="flex flex-wrap gap-2">
            {pool.consuming_labs.map((lab) => (
              <Link key={lab} to={`/lab/${encodeURIComponent(lab)}`} className="bg-[#212121] border border-[#2e2e2e] rounded-lg px-4 py-2 text-sm text-[#73BCF7] hover:border-[#555] transition cursor-pointer">{lab}</Link>
            ))}
          </div>
        </section>
      )}

      <section>
        <SectionHeader>Instances ({pool.instances.length})</SectionHeader>
        <InstanceTable instances={pool.instances} />
      </section>
    </div>
  );
}
