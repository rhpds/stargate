import { useTrends, usePoolsDashboard } from '../api/hooks';
import { useTimeRange } from '../components/TimeRangeContext';

function SectionHeader({ children }: { children: React.ReactNode }) {
  return <h2 className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">{children}</h2>;
}

function TrendChart({ label, data, color }: { label: string; data: number[]; color: string }) {
  if (!data || data.length === 0) return null;
  const max = Math.max(...data, 1);
  return (
    <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
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
  const { cluster } = useTimeRange();
  const trends = useTrends(cluster ? { cluster } : undefined);
  const pools = usePoolsDashboard();

  const t = trends.data as any;
  const pls = pools.data as any;

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2" style={{ fontFamily: 'Red Hat Display' }}>Trends</h1>
        <p className="text-[#6A6E73]">24-hour trend analysis across clusters and labs</p>
      </div>

      {trends.isLoading ? (
        <div className="animate-pulse space-y-4">
          {[1,2,3].map(i => <div key={i} className="bg-[#212121] rounded-lg h-32" />)}
        </div>
      ) : t ? (
        <div className="space-y-4">
          {t.failures && <TrendChart label="Failures per Hour" data={t.failures} color="#C9190B" />}
          {t.evaluations && <TrendChart label="Evaluations per Hour" data={t.evaluations} color="#4394E5" />}
          {t.pass_rate && <TrendChart label="Pass Rate % per Hour" data={t.pass_rate} color="#3E8635" />}

          {/* Provisioning state distribution */}
          {pls?.provisioning?.by_state && (
            <section>
              <SectionHeader>Current Provisioning State</SectionHeader>
              <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                <div className="space-y-2">
                  {Object.entries(pls.provisioning.by_state as Record<string, number>)
                    .sort(([,a], [,b]) => (b as number) - (a as number))
                    .map(([state, count]) => {
                      const max = pls.provisioning.total || 1;
                      const isError = state.includes('failed') || state.includes('error');
                      return (
                        <div key={state} className="flex items-center gap-3">
                          <span className="text-xs w-36 truncate shrink-0" style={{ color: isError ? '#C9190B' : state === 'started' ? '#3E8635' : '#6A6E73' }}>{state}</span>
                          <div className="flex-1 bg-[#333] h-4 rounded overflow-hidden">
                            <div className="h-4 rounded" style={{ width: `${((count as number) / max) * 100}%`, backgroundColor: isError ? '#C9190B' : state === 'started' ? '#3E8635' : '#F0AB00' }} />
                          </div>
                          <span className="text-xs text-white font-medium w-12 text-right">{count as number}</span>
                        </div>
                      );
                    })}
                </div>
              </div>
            </section>
          )}

          {/* Pool status overview */}
          {pls?.pools?.length > 0 && (
            <section>
              <SectionHeader>Pool Status</SectionHeader>
              <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                <div className="grid grid-cols-3 gap-4 text-center">
                  <div>
                    <div className="text-2xl font-bold text-[#3E8635]">{pls.pools.filter((p: any) => p.status === 'healthy').length}</div>
                    <div className="text-xs text-[#6A6E73]">Healthy</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-[#F0AB00]">{pls.pools.filter((p: any) => p.status === 'low').length}</div>
                    <div className="text-xs text-[#6A6E73]">Low</div>
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-[#C9190B]">{pls.pools.filter((p: any) => p.status === 'exhausted').length}</div>
                    <div className="text-xs text-[#6A6E73]">Exhausted</div>
                  </div>
                </div>
              </div>
            </section>
          )}
        </div>
      ) : (
        <p className="text-[#6A6E73]">No trend data available.</p>
      )}
    </div>
  );
}
