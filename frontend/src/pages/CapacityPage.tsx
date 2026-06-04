import { useForecast, useCapacityAnalysis, usePoolsDashboard } from '../api/hooks';
import { Link } from 'react-router-dom';
import FormattedAnalysis from '../components/FormattedAnalysis';

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

const RISK_COLORS: Record<string, string> = {
  low: '#3E8635', medium: '#F0AB00', high: '#EC7A08', critical: '#C9190B',
};

export default function CapacityPage() {
  const forecast = useForecast();
  const capacity = useCapacityAnalysis();
  const pools = usePoolsDashboard();

  const fc = forecast.data as any;
  const cap = capacity.data as any;
  const pls = pools.data as any;

  const forecastHours = fc?.forecast_hours ?? [];
  const totalPools = pls?.total_pools ?? 0;
  const exhausted = pls?.pools?.filter((p: any) => p.status === 'exhausted').length ?? 0;
  const low = pls?.pools?.filter((p: any) => p.status === 'low').length ?? 0;

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2" style={{ fontFamily: 'Red Hat Display' }}>Capacity</h1>
        <p className="text-[#6A6E73]">Resource demand projection and pool health</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Total Pools" value={totalPools} />
        <MetricCard label="Healthy" value={totalPools - exhausted - low} />
        <MetricCard label="Low" value={low} />
        <MetricCard label="Exhausted" value={exhausted} />
      </div>

      {/* 6-Hour Forecast */}
      {forecastHours.length > 0 && (
        <section>
          <SectionHeader>6-Hour Demand Forecast</SectionHeader>
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 overflow-x-auto">
            <div className="grid grid-cols-[100px_120px_120px_120px_120px_80px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
              <span>Hour</span><span className="text-right">Sessions</span><span className="text-right">Labs</span><span className="text-right">Attendees</span><span className="text-right">Est. Sandboxes</span><span>Risk</span>
            </div>
            {forecastHours.map((h: any, i: number) => (
              <div key={i} className="grid grid-cols-[100px_120px_120px_120px_120px_80px] gap-3 items-center py-1.5 text-sm">
                <span className="text-white">{h.timestamp ? new Date(h.timestamp).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }) : `+${h.hour}h`}</span>
                <span className="text-white text-right">{h.sessions_starting ?? 0}</span>
                <span className="text-white text-right">{h.labs ?? 0}</span>
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
              <Link key={cp.cluster} to={`/cluster/${encodeURIComponent(cp.cluster)}`} className="flex items-center gap-3 hover:bg-[#1e1e1e] rounded px-2 py-1 -mx-2 transition">
                <span className="text-sm text-[#73BCF7] w-40 shrink-0">{cp.cluster}</span>
                <span className="text-xs text-[#6A6E73]">Current: {cp.current_load ?? '--'}%</span>
                <span className="text-xs text-[#6A6E73]">Projected: {cp.projected_load ?? '--'}%</span>
                {cp.warning && <span className="text-xs text-[#F0AB00]">{cp.warning}</span>}
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
