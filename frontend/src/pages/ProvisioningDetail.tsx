import { Link } from 'react-router-dom';
import { useProvisioningOverview } from '../api/hooks';
import type { ProvisioningOverview, ProvisioningInstance } from '../api/types';

const STATUS_COLORS: Record<string, string> = {
  started: '#3E8635', healthy: '#3E8635',
  provisioning: '#F0AB00', starting: '#F0AB00', stopping: '#F0AB00',
  stopped: '#6A6E73',
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

function StateBar({ entries, max }: { entries: [string, number][]; max: number }) {
  return (
    <div className="space-y-2">
      {entries.map(([state, count]) => (
        <div key={state} className="flex items-center gap-3">
          <span className="text-xs w-36 truncate shrink-0" style={{ color: statusColor(state) }}>{state}</span>
          <div className="flex-1 bg-[#333] h-4 rounded overflow-hidden">
            <div className="h-4 rounded" style={{ width: `${(count / max) * 100}%`, backgroundColor: statusColor(state) }} />
          </div>
          <span className="text-xs text-white font-medium w-12 text-right">{count}</span>
        </div>
      ))}
    </div>
  );
}

export default function ProvisioningDetail() {
  const { data, isLoading, isError } = useProvisioningOverview();

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
        <p className="text-[#C9190B] mt-4">Failed to load provisioning data.</p>
      </div>
    );
  }

  const prov = data as ProvisioningOverview;
  const stateEntries = Object.entries(prov.by_state).sort(([,a], [,b]) => b - a);
  const maxCount = stateEntries.length > 0 ? stateEntries[0]![1] : 1;
  const problemStates = Object.entries(prov.subjects_by_state).filter(([s]) => s.includes('failed') || s.includes('error') || s === 'stopped');
  const labEntries = Object.entries(prov.labs_affected).sort(([,a], [,b]) => b.failed - a.failed);

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div>
        <Link to="/" className="text-[#73BCF7] text-sm hover:underline">Health</Link>
        <span className="text-[#6A6E73] text-sm mx-2">/</span>
        <span className="text-[#6A6E73] text-sm">Provisioning</span>
      </div>

      <h1 className="text-2xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>Provisioning Overview</h1>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Total Subjects" value={prov.total} />
        <MetricCard label="Started" value={prov.started} />
        <MetricCard label="Failed" value={prov.failed} />
        <MetricCard label="Failure Rate" value={`${prov.failure_rate}%`} />
      </div>

      <section>
        <SectionHeader>State Distribution</SectionHeader>
        <StateBar entries={stateEntries} max={maxCount} />
      </section>

      {problemStates.length > 0 && (
        <section>
          <SectionHeader>Problem States</SectionHeader>
          <div className="space-y-4">
            {problemStates.map(([state, subjects]) => (
              <div key={state} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                <div className="flex items-center gap-2 mb-3">
                  <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: statusColor(state), color: '#fff' }}>{state}</span>
                  <span className="text-white text-sm font-medium">{(subjects as ProvisioningInstance[]).length} subjects</span>
                </div>
                <div className="space-y-1">
                  {(subjects as ProvisioningInstance[]).slice(0, 20).map((inst) => (
                    <div key={inst.anarchy_name} className="flex items-center gap-3 text-sm">
                      <Link to={`/lab/${encodeURIComponent(inst.lab_code || '')}`} className="text-[#73BCF7] hover:underline w-20 shrink-0">{inst.lab_code || '--'}</Link>
                      <span className="text-white truncate flex-1" title={inst.anarchy_name}>{inst.anarchy_name}</span>
                      <span className="text-[#6A6E73] text-xs shrink-0">{inst.namespace}</span>
                      {inst.console_url && <a href={inst.console_url} target="_blank" rel="noopener noreferrer" className="text-[#73BCF7] text-xs hover:underline shrink-0">Console</a>}
                    </div>
                  ))}
                  {(subjects as ProvisioningInstance[]).length > 20 && (
                    <p className="text-[#6A6E73] text-xs">+ {(subjects as ProvisioningInstance[]).length - 20} more</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section>
        <SectionHeader>Affected Labs ({labEntries.length})</SectionHeader>
        <div className="space-y-0.5">
          <div className="grid grid-cols-[1fr_80px_80px_80px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
            <span>Lab</span>
            <span className="text-right">Total</span>
            <span className="text-right">Started</span>
            <span className="text-right">Failed</span>
          </div>
          {labEntries.slice(0, 50).map(([lab, summary]) => (
            <div key={lab} className="grid grid-cols-[1fr_80px_80px_80px] gap-3 items-center py-1.5">
              <Link to={`/lab/${encodeURIComponent(lab)}`} className="text-sm text-[#73BCF7] hover:underline truncate">{lab}</Link>
              <span className="text-sm text-white text-right">{summary.total}</span>
              <span className="text-sm text-white text-right">{summary.started}</span>
              <span className="text-sm text-right" style={{ color: summary.failed > 0 ? '#C9190B' : '#3E8635' }}>{summary.failed}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
