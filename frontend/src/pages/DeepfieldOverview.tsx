import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

const SEV_COLORS: Record<string, string> = { critical: '#A30000', high: '#C9190B', medium: '#F0AB00', low: '#3E8635', info: '#6A6E73' };

function MetricCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-[#1e1e1e] rounded-lg p-3 border border-[#2e2e2e]">
      <div className="text-[10px] uppercase tracking-wider text-[#6A6E73] font-semibold mb-1">{label}</div>
      <div className="text-2xl font-bold text-white">{value}</div>
      {sub && <div className="text-[10px] text-[#6A6E73] mt-0.5">{sub}</div>}
    </div>
  );
}

function FunnelBar({ stages }: { stages: { label: string; value: number }[] }) {
  const max = Math.max(...stages.map(s => s.value), 1);
  return (
    <div className="space-y-1.5">
      {stages.map(s => (
        <div key={s.label} className="flex items-center gap-2">
          <span className="text-[10px] text-[#8A8D90] w-16 text-right shrink-0">{s.label}</span>
          <div className="flex-1 bg-[#1a1a1a] rounded h-5 overflow-hidden">
            <div className="h-full rounded" style={{ width: `${(s.value / max) * 100}%`, backgroundColor: '#4394E5' }} />
          </div>
          <span className="text-xs text-[#ccc] w-20 text-right font-mono">{s.value.toLocaleString()}</span>
        </div>
      ))}
    </div>
  );
}

export default function DeepfieldOverview() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['deepfield-overview'],
    queryFn: () => api.getDeepfieldOverview(),
    refetchInterval: 15000,
  });

  const m = data?.metrics || {};
  const funnel = m.funnel || {};
  const signals = m.signals || {};
  const sevs = signals.by_severity || {};
  const agents = m.agents || {};
  const models = m.models || {};
  const incidents = data?.incidents || [];
  const clusters = data?.clusters || {};

  const clusterCount = typeof clusters === 'object' ? (Array.isArray(clusters) ? clusters.length : Object.keys(clusters).length) : 0;

  const microModels = Object.entries(models).filter(([name]) => /cpu|xeon|granite_2b|phi3_mini|qwen25/i.test(name));
  const macroModels = Object.entries(models).filter(([name]) => !/cpu|xeon|granite_2b|phi3_mini|qwen25/i.test(name));

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-4">
      <div className="mb-4">
        <h1 className="text-xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>Deepfield</h1>
        <p className="text-[#6A6E73] text-xs">Real-time signal processing — K8s watch streams, nanoagent pipeline, correlation engine</p>
      </div>

      {isLoading && <div className="text-[#6A6E73] py-12 text-center">Loading...</div>}
      {error && <div className="text-[#C9190B] py-12 text-center">Error: {(error as Error).message}</div>}
      {m.error && <div className="text-[#F0AB00] py-4 text-center text-sm">Deepfield unavailable: {m.error}</div>}

      {data && !m.error && (
        <>
          {/* Stats Bar */}
          <div className="grid grid-cols-4 gap-3 mb-4">
            <MetricCard label="Clusters Monitored" value={clusterCount} />
            <MetricCard label="Signals / sec" value={Math.round(m.signals_per_second || 0)} sub={`${(signals.total || 0).toLocaleString()} total (1h)`} />
            <MetricCard label="Compression" value={`${m.compression_ratio || 0}:1`} sub="raw → reasoning task" />
            <MetricCard label="Active Inferences" value={m.inference_in_flight || 0} sub={`${funnel.inferences || 0} in last hour`} />
          </div>

          {/* Signal Funnel + Severity */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] p-4">
              <h3 className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider mb-3">Signal Funnel (1h)</h3>
              <FunnelBar stages={[
                { label: 'Raw', value: funnel.raw || 0 },
                { label: 'Retained', value: funnel.retained || 0 },
                { label: 'Findings', value: funnel.findings || 0 },
                { label: 'Tasks', value: funnel.tasks || 0 },
                { label: 'Inferences', value: funnel.inferences || 0 },
              ]} />
            </div>
            <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] p-4">
              <h3 className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider mb-3">Signal Severity</h3>
              <div className="space-y-2">
                {Object.entries(sevs).sort(([,a],[,b]) => (b as number) - (a as number)).map(([sev, count]) => (
                  <div key={sev} className="flex items-center gap-2">
                    <span className="text-[10px] px-1.5 py-0.5 rounded font-medium" style={{ backgroundColor: `${SEV_COLORS[sev] || '#555'}30`, color: SEV_COLORS[sev] || '#8A8D90' }}>{sev}</span>
                    <div className="flex-1 bg-[#1a1a1a] rounded h-4 overflow-hidden">
                      <div className="h-full rounded" style={{ width: `${((count as number) / Math.max(signals.total || 1, 1)) * 100}%`, backgroundColor: SEV_COLORS[sev] || '#555' }} />
                    </div>
                    <span className="text-xs text-[#ccc] font-mono w-16 text-right">{(count as number).toLocaleString()}</span>
                  </div>
                ))}
              </div>
              <div className="mt-3 text-right text-[10px] text-[#6A6E73]">
                raw→incident: <span className="text-white font-medium">{incidents.length > 0 ? `${Math.round((funnel.raw || 0) / incidents.length).toLocaleString()}:1` : '--'}</span>
              </div>
            </div>
          </div>

          {/* Nanoagent Pipeline */}
          <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] p-4 mb-4">
            <h3 className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider mb-3">Nanoagent Pipeline</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {Object.entries(agents).sort(([,a],[,b]) => (b as any).total_evaluated - (a as any).total_evaluated).map(([name, stats]: [string, any]) => {
                const rate = stats.total_evaluated > 0 ? ((stats.escalated || 0) / stats.total_evaluated) * 100 : 0;
                const dot = rate > 20 ? '#C9190B' : rate > 5 ? '#F0AB00' : '#3E8635';
                return (
                  <div key={name} className="bg-[#1a1a1a] rounded p-2 border border-[#2a2a2a]">
                    <div className="flex items-center gap-1.5 mb-1">
                      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: dot }} />
                      <span className="text-[10px] text-[#ccc] truncate">{name.replace('Agent', '')}</span>
                    </div>
                    <div className="text-sm font-bold text-white">{stats.total_evaluated?.toLocaleString()}</div>
                    <div className="text-[9px] text-[#6A6E73]">{rate.toFixed(1)}% escalation</div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* LLM Models */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            {[{ title: 'Micro-Agents (Xeon 6 CPU)', items: microModels }, { title: 'Macro-Agents (Gaudi 3 GPU)', items: macroModels }].map(({ title, items }) => (
              <div key={title} className="bg-[#151515] rounded-lg border border-[#2e2e2e] p-4">
                <h3 className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider mb-3">{title}</h3>
                {items.length === 0 ? (
                  <div className="text-[#555] text-xs text-center py-2">No models active</div>
                ) : (
                  <div className="space-y-1.5">
                    {items.map(([name, stats]: [string, any]) => (
                      <div key={name} className="flex items-center justify-between bg-[#1a1a1a] rounded px-2.5 py-1.5 border border-[#2a2a2a]">
                        <span className="text-[11px] text-[#ccc] font-mono truncate flex-1">{name}</span>
                        <div className="flex items-center gap-3 text-[10px] text-[#8A8D90] shrink-0">
                          <span>{stats.total_calls} calls</span>
                          <span className="text-[#4EC9B0]">{stats.avg_tps?.toFixed(1)} t/s</span>
                          <span>{(stats.avg_latency / 1000)?.toFixed(1)}s</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Recent Incidents */}
          <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] p-4">
            <h3 className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider mb-3">
              Recent Incidents ({data?.incident_count || 0})
            </h3>
            {incidents.length === 0 ? (
              <div className="text-[#555] text-xs text-center py-4">No incidents</div>
            ) : (
              <div className="space-y-1">
                {incidents.slice(0, 20).map((inc: any) => (
                  <div key={inc.id} className="flex items-center gap-3 bg-[#1a1a1a] rounded px-3 py-2 border border-[#2a2a2a]">
                    <span className="text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0" style={{
                      backgroundColor: `${SEV_COLORS[inc.severity] || '#555'}30`,
                      color: SEV_COLORS[inc.severity] || '#8A8D90',
                    }}>{inc.severity}</span>
                    <span className="text-xs text-[#4394E5] font-mono truncate">{inc.namespace}</span>
                    <span className="text-[10px] text-[#8A8D90]">{inc.cluster_id}</span>
                    <span className="text-xs text-[#C9190B] truncate flex-1 text-right">{inc.failure_class}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${inc.status === 'open' ? 'bg-[#F0AB00]/20 text-[#F0AB00]' : 'bg-[#3E8635]/20 text-[#3E8635]'}`}>{inc.status}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
