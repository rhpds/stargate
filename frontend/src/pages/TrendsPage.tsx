import { useNavigate, Link } from 'react-router-dom';
import { useTrends, usePoolsDashboard, useProvisioningOverview, useAAPTrends, useProvisioningTrends, useMTTR } from '../api/hooks';
import { useTimeRange } from '../components/TimeRangeContext';

const STATUS_COLORS: Record<string, string> = {
  healthy: '#3E8635', low: '#F0AB00', exhausted: '#C9190B',
  started: '#3E8635', provisioning: '#F0AB00', stopped: '#6A6E73',
};

function statusColor(s: string): string {
  if (s.includes('failed') || s.includes('error')) return '#C9190B';
  return STATUS_COLORS[s?.toLowerCase()] ?? '#6A6E73';
}

function SectionHeader({ children, onClick }: { children: React.ReactNode; onClick?: () => void }) {
  return (
    <h2 className={`text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3 ${onClick ? 'cursor-pointer hover:text-white transition' : ''}`} onClick={onClick}>
      {children} {onClick && <span className="text-[#73BCF7]">&rarr;</span>}
    </h2>
  );
}

function TrendChart({ label, data, color, onClick }: { label: string; data: number[]; color: string; onClick?: () => void }) {
  if (!data || data.length === 0) return null;
  const max = Math.max(...data, 1);
  return (
    <div className={`bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 ${onClick ? 'cursor-pointer hover:border-[#555] transition' : ''}`} onClick={onClick}>
      <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-2">{label}</div>
      <div className="flex items-end gap-[2px] h-20">
        {data.map((v, i) => {
          const height = (v / max) * 100;
          return (
            <div key={i} className="flex-1 flex flex-col justify-end" title={`${v}`}>
              <div className="rounded-t" style={{ height: `${Math.max(height, 2)}%`, backgroundColor: color, minHeight: '2px' }} />
            </div>
          );
        })}
      </div>
      <div className="flex justify-between text-[10px] text-[#6A6E73] mt-1">
        <span>24h ago</span>
        <span>Current: {data[data.length - 1]}</span>
        <span>now</span>
      </div>
    </div>
  );
}

export default function TrendsPage() {
  const navigate = useNavigate();
  const { cluster } = useTimeRange();
  const trends = useTrends(cluster ? { cluster } : undefined);
  const pools = usePoolsDashboard();
  const provisioning = useProvisioningOverview();
  const aapTrends = useAAPTrends(24);
  const provTrends = useProvisioningTrends(24);
  const mttr = useMTTR(168);

  const t = trends.data as any;
  const pls = pools.data as any;
  const prov = provisioning.data as any;

  const allPools = (pls?.pools ?? []) as Array<{ name: string; status: string; available: number }>;

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-white mb-1" style={{ fontFamily: 'Red Hat Display' }}>Trends</h1>
        <p className="text-[#6A6E73] text-sm">24-hour trend analysis across clusters and labs</p>
      </div>

      {trends.isLoading ? (
        <div className="animate-pulse space-y-4">
          {[1,2,3].map(i => <div key={i} className="bg-[#212121] rounded-lg h-32" />)}
        </div>
      ) : t ? (
        <div className="space-y-4">
          {t.failures && <TrendChart label="Failures per Hour" data={t.failures} color="#C9190B" onClick={() => navigate('/failures')} />}
          {t.evaluations && <TrendChart label="Evaluations per Hour" data={t.evaluations} color="#4394E5" onClick={() => navigate('/pipeline')} />}
          {t.pass_rate && <TrendChart label="Pass Rate % per Hour" data={t.pass_rate} color="#3E8635" onClick={() => navigate('/pipeline')} />}
        </div>
      ) : (
        <p className="text-[#6A6E73]">No trend data available.</p>
      )}

      {/* AAP SLI Trend */}
      {(aapTrends.data as any)?.timeline?.length > 0 && (
        <section>
          <SectionHeader>AAP Provisioning SLI (24h)</SectionHeader>
          <TrendChart
            label="AAP Success Rate %"
            data={((aapTrends.data as any).timeline as any[]).map((p: any) => p.success_rate ?? 0)}
            color="#4394E5"
          />
        </section>
      )}

      {/* Provisioning Trend */}
      {(provTrends.data as any)?.timeline?.length > 0 && (
        <section>
          <SectionHeader onClick={() => navigate('/provisioning')}>Provisioning History (24h)</SectionHeader>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <TrendChart
              label="Total Subjects"
              data={((provTrends.data as any).timeline as any[]).map((p: any) => p.total ?? 0)}
              color="#4394E5"
            />
            <TrendChart
              label="Failed Subjects"
              data={((provTrends.data as any).timeline as any[]).map((p: any) => p.failed ?? 0)}
              color="#C9190B"
            />
          </div>
        </section>
      )}

      {/* MTTR */}
      {mttr.data?.by_class?.length > 0 && (
        <section>
          <SectionHeader>Mean Time to Recovery (7 days)</SectionHeader>
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
            {mttr.data.overall_mttr_minutes != null && (
              <div className="text-center mb-4">
                <div className="text-3xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>
                  {mttr.data.overall_mttr_minutes < 60
                    ? `${Math.round(mttr.data.overall_mttr_minutes)}m`
                    : `${(mttr.data.overall_mttr_minutes / 60).toFixed(1)}h`}
                </div>
                <div className="text-xs text-[#6A6E73] uppercase">Overall MTTR ({mttr.data.total_recoveries} recoveries)</div>
              </div>
            )}
            <div className="space-y-2">
              {(mttr.data.by_class as any[]).slice(0, 10).map((c: any) => (
                <div key={c.failure_class} onClick={() => navigate(`/failures?selected=${encodeURIComponent(c.failure_class)}`)}
                  className="flex items-center gap-3 cursor-pointer hover:bg-[#1e1e1e] rounded px-1 -mx-1 transition">
                  <span className="text-xs text-[#6A6E73] w-40 truncate shrink-0">{c.failure_class}</span>
                  <span className="text-xs text-white w-16 text-right">{c.avg_minutes < 60 ? `${Math.round(c.avg_minutes)}m` : `${(c.avg_minutes / 60).toFixed(1)}h`}</span>
                  <span className="text-xs text-[#6A6E73] w-12 text-right">{c.count}x</span>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* Provisioning State */}
      {prov && prov.total > 0 && (
        <section>
          <SectionHeader onClick={() => navigate('/provisioning')}>Provisioning State ({prov.total} subjects)</SectionHeader>
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
            <div className="space-y-2">
              {Object.entries(prov.by_state as Record<string, number>)
                .sort(([,a], [,b]) => (b as number) - (a as number))
                .map(([state, count]) => {
                  const max = prov.total || 1;
                  return (
                    <div key={state}
                      onClick={() => navigate('/provisioning')}
                      className="flex items-center gap-3 cursor-pointer hover:bg-[#1e1e1e] rounded px-1 -mx-1 transition">
                      <span className="text-xs w-36 truncate shrink-0" style={{ color: statusColor(state) }}>{state}</span>
                      <div className="flex-1 bg-[#333] h-4 rounded overflow-hidden">
                        <div className="h-4 rounded" style={{ width: `${((count as number) / max) * 100}%`, backgroundColor: statusColor(state) }} />
                      </div>
                      <span className="text-xs text-white font-medium w-12 text-right">{count as number}</span>
                    </div>
                  );
                })}
            </div>
          </div>

          {/* Affected labs */}
          {prov.labs_affected && Object.keys(prov.labs_affected).length > 0 && (
            <div className="mt-3">
              <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-2">Labs with Failed Instances</div>
              <div className="flex flex-wrap gap-2">
                {Object.entries(prov.labs_affected)
                  .filter(([, summary]: [string, any]) => summary.failed > 0)
                  .sort(([, a]: [string, any], [, b]: [string, any]) => b.failed - a.failed)
                  .slice(0, 15)
                  .map(([lab, summary]: [string, any]) => (
                    <Link key={lab} to={`/lab/${encodeURIComponent(lab)}`}
                      className="bg-[#212121] border border-[#2e2e2e] rounded px-3 py-1.5 text-xs hover:border-[#555] transition flex items-center gap-2">
                      <span className="text-[#73BCF7]">{lab}</span>
                      <span className="text-[#C9190B] font-bold">{summary.failed} failed</span>
                    </Link>
                  ))}
              </div>
            </div>
          )}
        </section>
      )}

      {/* Pool Status */}
      {allPools.length > 0 && (
        <section>
          <SectionHeader onClick={() => navigate('/capacity')}>Pool Health</SectionHeader>
          <div className="grid grid-cols-3 gap-4 mb-4">
            <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 text-center cursor-pointer hover:border-[#555] transition" onClick={() => navigate('/capacity')}>
              <div className="text-2xl font-bold text-[#3E8635]">{allPools.filter(p => p.status === 'healthy').length}</div>
              <div className="text-xs text-[#6A6E73]">Healthy</div>
            </div>
            <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 text-center cursor-pointer hover:border-[#555] transition" onClick={() => navigate('/capacity')}>
              <div className="text-2xl font-bold text-[#F0AB00]">{allPools.filter(p => p.status === 'low').length}</div>
              <div className="text-xs text-[#6A6E73]">Low</div>
            </div>
            <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 text-center cursor-pointer hover:border-[#555] transition" onClick={() => navigate('/capacity')}>
              <div className="text-2xl font-bold text-[#C9190B]">{allPools.filter(p => p.status === 'exhausted').length}</div>
              <div className="text-xs text-[#6A6E73]">Exhausted</div>
            </div>
          </div>
          {allPools.filter(p => p.status !== 'healthy').length > 0 && (
            <div className="space-y-1">
              {allPools.filter(p => p.status !== 'healthy').slice(0, 10).map(pool => (
                <Link key={pool.name} to={`/pool/${encodeURIComponent(pool.name)}`}
                  className="flex items-center gap-3 text-sm hover:bg-[#1e1e1e] rounded px-2 py-1 -mx-2 transition">
                  <span className="text-[#73BCF7] truncate flex-1">{pool.name}</span>
                  <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: STATUS_COLORS[pool.status] ?? '#6A6E73', color: '#fff' }}>{pool.status}</span>
                  <span className="text-xs text-[#6A6E73]">{pool.available} avail</span>
                </Link>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
