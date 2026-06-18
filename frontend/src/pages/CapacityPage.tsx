import { useEffect, useState } from 'react';
import { useForecast, useCapacityAnalysis, usePoolsDashboard } from '../api/hooks';
import { Link } from 'react-router-dom';
import FormattedAnalysis from '../components/FormattedAnalysis';
import SearchBar from '../components/SearchBar';

const STATUS_COLORS: Record<string, string> = {
  healthy: '#3E8635', low: '#F0AB00', exhausted: '#C9190B',
};

function MetricCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
      <div className="text-2xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>{value}</div>
      <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">{label}</div>
      {sub && <div className="text-xs text-[#6A6E73] mt-0.5">{sub}</div>}
    </div>
  );
}

function SectionHeader({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h2 className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold">{children}</h2>
      {right}
    </div>
  );
}

const RISK_COLORS: Record<string, string> = {
  low: '#3E8635', medium: '#F0AB00', high: '#EC7A08', critical: '#C9190B',
};

export default function CapacityPage() {
  const [poolSearch, setPoolSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const forecast = useForecast();
  const capacity = useCapacityAnalysis();
  const pools = usePoolsDashboard();

  const fc = forecast.data as any;
  const cap = capacity.data as any;

  useEffect(() => { capacity.mutate(); }, []);
  const pls = pools.data as any;

  const forecastHours = fc?.forecast_hours ?? [];
  const allPools = (pls?.pools ?? []) as Array<{ name: string; available: number; ready: number; min: number; status: string }>;
  const exhausted = allPools.filter(p => p.status === 'exhausted').length;
  const low = allPools.filter(p => p.status === 'low').length;
  const healthy = allPools.filter(p => p.status === 'healthy').length;

  const filteredPools = allPools.filter(p => {
    if (poolSearch && !p.name.toLowerCase().includes(poolSearch.toLowerCase())) return false;
    if (statusFilter && p.status !== statusFilter) return false;
    return true;
  });

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-white mb-1" style={{ fontFamily: 'Red Hat Display' }}>Capacity & Pools</h1>
        <p className="text-[#6A6E73] text-sm">Resource demand, pool availability, and forecasting</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Total Pools" value={allPools.length} />
        <MetricCard label="Healthy" value={healthy} />
        <MetricCard label="Low" value={low} />
        <MetricCard label="Exhausted" value={exhausted} />
      </div>

      {/* Pool Availability with search and filter */}
      <section>
        <SectionHeader right={
          <div className="flex items-center gap-2">
            <div className="flex gap-1">
              {['', 'healthy', 'low', 'exhausted'].map(s => (
                <button key={s} onClick={() => setStatusFilter(statusFilter === s ? '' : s)}
                  className={`text-xs px-2 py-1 rounded ${statusFilter === s ? 'bg-[#EE0000] text-white' : 'bg-[#2e2e2e] text-[#8A8D90] hover:bg-[#333]'}`}>
                  {s || 'All'}
                </button>
              ))}
            </div>
            <SearchBar placeholder="Search pools..." value={poolSearch} onChange={setPoolSearch} className="w-56" />
          </div>
        }>
          Pools ({filteredPools.length})
        </SectionHeader>
        {filteredPools.length === 0 ? (
          <p className="text-[#6A6E73] text-sm">No pools match your filter.</p>
        ) : (
          <div className="space-y-1">
            <div className="grid grid-cols-[1fr_80px_80px_80px_80px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
              <span>Pool</span><span className="text-right">Available</span><span className="text-right">Ready</span><span className="text-right">Min</span><span>Status</span>
            </div>
            {filteredPools.map(pool => (
              <Link key={pool.name} to={`/pool/${encodeURIComponent(pool.name)}`}
                className="grid grid-cols-[1fr_80px_80px_80px_80px] gap-3 items-center py-1.5 hover:bg-[#1e1e1e] rounded transition">
                <span className="text-sm text-[#73BCF7] truncate">{pool.name}</span>
                <span className="text-sm text-white text-right">{pool.available}</span>
                <span className="text-sm text-white text-right">{pool.ready}</span>
                <span className="text-sm text-white text-right">{pool.min}</span>
                <span className="text-xs font-semibold px-2 py-0.5 rounded-full w-fit" style={{ backgroundColor: STATUS_COLORS[pool.status] ?? '#6A6E73', color: '#fff' }}>{pool.status}</span>
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* 6-Hour Forecast */}
      {forecastHours.length > 0 && (
        <section>
          <SectionHeader>6-Hour Demand Forecast</SectionHeader>
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 overflow-x-auto">
            <div className="grid grid-cols-[100px_100px_100px_120px_120px_80px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
              <span>Hour</span><span className="text-right">Sessions</span><span className="text-right">Labs</span><span className="text-right">Attendees</span><span className="text-right">Est. Sandboxes</span><span>Risk</span>
            </div>
            {forecastHours.map((h: any, i: number) => (
              <div key={i} className="grid grid-cols-[100px_100px_100px_120px_120px_80px] gap-3 items-center py-1.5 text-sm">
                <span className="text-white">{h.timestamp ? new Date(h.timestamp).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }) : `+${h.hour}h`}</span>
                <span className="text-white text-right">{h.sessions_starting ?? 0}</span>
                <span className="text-white text-right">{Array.isArray(h.labs) ? h.labs.length : (h.labs ?? 0)}</span>
                <span className="text-white text-right">{h.total_attendees ?? 0}</span>
                <span className="text-white text-right">{h.estimated_new_sandboxes ?? 0}</span>
                <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: RISK_COLORS[h.risk] ?? '#6A6E73', color: '#fff' }}>{h.risk ?? 'low'}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Pool Velocity */}
      {cap?.pool_velocities && Object.keys(cap.pool_velocities).length > 0 && (
        <section>
          <SectionHeader>Pool Velocity</SectionHeader>
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 space-y-2">
            {Object.entries(cap.pool_velocities).map(([pool, vel]: [string, any]) => (
              <div key={pool} className="flex items-center gap-3">
                <Link to={`/pool/${encodeURIComponent(pool)}`} className="text-sm text-[#73BCF7] hover:underline w-60 truncate shrink-0">{pool}</Link>
                <span className="text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: vel.trend === 'depleting' ? '#C9190B' : vel.trend === 'recovering' ? '#3E8635' : '#6A6E73', color: '#fff' }}>{vel.trend}</span>
                <span className="text-xs text-[#6A6E73]">{vel.handles_per_hour?.toFixed(1)} handles/hr</span>
                {vel.exhaustion_hours != null && vel.exhaustion_hours < 24 && (
                  <span className="text-xs text-[#C9190B]">exhausts in {vel.exhaustion_hours.toFixed(0)}h</span>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* AI Capacity Analysis */}
      {cap?.llm_analysis && (
        <section>
          <SectionHeader>AI Capacity Analysis</SectionHeader>
          <div className="bg-[#1a1a2e] border border-[#2e2e4e] rounded-lg p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-[#4394E5] text-white">AI</span>
              <span className="text-sm text-white font-medium">Capacity Forecast</span>
            </div>
            <FormattedAnalysis text={typeof cap.llm_analysis === 'string' ? cap.llm_analysis : cap.llm_analysis?.content ?? ''} />
          </div>
        </section>
      )}

      {/* Cluster Projections */}
      {fc?.cluster_projections?.length > 0 && (
        <section>
          <SectionHeader>Cluster Projections</SectionHeader>
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 space-y-2">
            {fc.cluster_projections.map((cp: any) => (
              <Link key={cp.cluster} to={`/cluster/${encodeURIComponent(cp.cluster)}`} className="flex items-center gap-3 hover:bg-[#1e1e1e] rounded px-2 py-1.5 -mx-2 transition">
                <span className="text-sm text-[#73BCF7] w-32 shrink-0">{cp.cluster}</span>
                <span className="text-xs text-[#6A6E73]">CPU: {cp.current_cpu != null ? `${Math.round(cp.current_cpu)}%` : '--'}</span>
                <span className="text-xs text-[#6A6E73]">VMs: {cp.current_vms ?? '--'}</span>
                <span className="text-xs text-[#6A6E73]">Sandboxes: {cp.current_sandboxes ?? '--'}</span>
                {cp.capacity_warning && <span className="text-xs text-[#F0AB00]">capacity warning</span>}
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
