import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import FormattedAnalysis from '../components/FormattedAnalysis';
import { IssueFeedbackPanel, AiAnalysisFeedback } from '../components/RecommendationFeedback';

/* ---- KPI Dashboard ---- */

function KpiDashboard() {
  const { data } = useQuery({ queryKey: ['platform-kpis'], queryFn: () => api.getPlatformKpis(), refetchInterval: 60000 });
  if (!data) return null;

  const kpis = data.kpis || {};
  const slos = data.slos || [];

  const SLO_COLORS: Record<string, string> = { met: '#3E8635', at_risk: '#F0AB00', breached: '#C9190B' };

  return (
    <div className="mb-4">
      {/* KPI Tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2 mb-3">
        {[
          { label: 'Lab Readiness', value: `${kpis.lab_readiness_rate?.toFixed(1) || '--'}%`, color: (kpis.lab_readiness_rate || 0) >= 90 ? '#3E8635' : '#F0AB00' },
          { label: 'Provisioning', value: `${kpis.provisioning_success_rate?.toFixed(1) || '--'}%`, color: (kpis.provisioning_success_rate || 0) >= 99 ? '#3E8635' : '#F0AB00' },
          { label: 'Time to Ready', value: kpis.mean_time_to_ready_minutes ? `${kpis.mean_time_to_ready_minutes.toFixed(0)}m` : '--', color: (kpis.mean_time_to_ready_minutes || 99) <= 20 ? '#3E8635' : '#F0AB00' },
          { label: 'Active Sandboxes', value: kpis.active_sandboxes?.toLocaleString() || '--', color: '#4394E5' },
          { label: 'Utilization', value: `${kpis.platform_utilization_pct?.toFixed(0) || '--'}%`, color: '#4394E5' },
          { label: 'MTTR', value: kpis.mttr_minutes ? `${kpis.mttr_minutes.toFixed(0)}m` : '--', color: (kpis.mttr_minutes || 99) <= 15 ? '#3E8635' : '#F0AB00' },
          { label: 'Impacted Owners', value: kpis.developer_impact?.toString() || '0', color: (kpis.developer_impact || 0) === 0 ? '#3E8635' : '#C9190B' },
        ].map(k => (
          <div key={k.label} className="bg-[#1a1a1a] rounded-lg border border-[#2e2e2e] p-2.5 text-center">
            <div className="text-[10px] text-[#8A8D90] uppercase tracking-wider mb-1">{k.label}</div>
            <div className="text-lg font-bold" style={{ color: k.color }}>{k.value}</div>
          </div>
        ))}
      </div>
      {/* SLO Status */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {slos.map((slo: any) => (
          <div key={slo.name} className="bg-[#1a1a1a] rounded-lg border border-[#2e2e2e] px-3 py-2 flex items-center justify-between">
            <div>
              <div className="text-[10px] text-[#8A8D90]">{slo.name}</div>
              <div className="text-xs text-white font-medium">{slo.current?.toFixed(1)}{slo.unit} <span className="text-[10px] text-[#555]">/ {slo.target}{slo.unit}</span></div>
            </div>
            <span className="text-[9px] px-1.5 py-0.5 rounded font-medium"
              style={{ backgroundColor: `${SLO_COLORS[slo.status] || '#555'}20`, color: SLO_COLORS[slo.status] || '#555' }}>
              {slo.status?.replace(/_/g, ' ')}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}


/* ---- Cost Analysis ---- */

function CostAnalysis({ alwaysOpen = false }: { alwaysOpen?: boolean }) {
  const { data } = useQuery({ queryKey: ['cost-analysis'], queryFn: () => api.getCostAnalysis(), refetchInterval: 120000 });
  const [open, setOpen] = useState(alwaysOpen);
  if (!data?.summary) return null;

  const s = data.summary;
  const fc = data.failure_costs || {};

  return (
    <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] mb-4 overflow-hidden">
      {alwaysOpen ? (
        <div className="flex items-center gap-3 px-4 py-2.5">
          <span className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider">Cost Analysis</span>
          <span className="text-xs text-white font-medium">${s.estimated_monthly_cost?.toLocaleString(undefined, {maximumFractionDigits: 0}) || '--'}/mo</span>
          {s.waste_pct > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ backgroundColor: '#C9190B20', color: '#C9190B' }}>
              {s.waste_pct.toFixed(1)}% waste
            </span>
          )}
        </div>
      ) : (
        <button onClick={() => setOpen(!open)}
          className="w-full flex items-center justify-between px-4 py-2.5 text-left hover:bg-[#1e1e1e] transition">
          <div className="flex items-center gap-3">
            <span className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider">Cost Analysis</span>
            <span className="text-xs text-white font-medium">${s.estimated_monthly_cost?.toLocaleString(undefined, {maximumFractionDigits: 0}) || '--'}/mo</span>
            {s.waste_pct > 0 && (
              <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ backgroundColor: '#C9190B20', color: '#C9190B' }}>
                {s.waste_pct.toFixed(1)}% waste
              </span>
            )}
          </div>
          <span className="text-[#555] text-xs">{open ? '▲' : '▼'}</span>
        </button>
      )}
      {(alwaysOpen || open) && (
        <div className="px-4 pb-4 border-t border-[#2e2e2e] pt-3">
          {/* Summary tiles */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3">
            {[
              { label: 'Active Sandboxes', value: s.total_sandboxes_active, color: '#4394E5' },
              { label: 'Hourly Cost', value: `$${s.estimated_hourly_cost?.toFixed(0) || '--'}`, color: '#ccc' },
              { label: 'Failure Cost/mo', value: `$${fc.total_waste_monthly?.toLocaleString(undefined, {maximumFractionDigits: 0}) || '--'}`, color: '#C9190B' },
              { label: 'Waste', value: `${s.waste_pct?.toFixed(1) || '0'}%`, color: s.waste_pct > 10 ? '#C9190B' : '#3E8635' },
            ].map(t => (
              <div key={t.label} className="bg-[#1a1a1a] rounded p-2.5 text-center border border-[#2a2a2a]">
                <div className="text-[10px] text-[#8A8D90] uppercase mb-0.5">{t.label}</div>
                <div className="text-sm font-bold" style={{ color: t.color }}>{t.value}</div>
              </div>
            ))}
          </div>
          {/* Top cost by catalog item */}
          {data.by_catalog_item?.length > 0 && (
            <div className="mb-3">
              <div className="text-[10px] text-[#8A8D90] uppercase mb-1.5">Cost by Lab Type</div>
              <div className="space-y-1">
                {data.by_catalog_item.slice(0, 6).map((ci: any) => (
                  <div key={ci.catalog_item} className="flex items-center justify-between bg-[#1a1a1a] rounded px-2.5 py-1.5 border border-[#2a2a2a]">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-[9px] px-1.5 py-0.5 rounded shrink-0"
                        style={{ backgroundColor: ci.resource_type === 'dedicated' ? '#4394E520' : '#3E863520', color: ci.resource_type === 'dedicated' ? '#4394E5' : '#3E8635' }}>
                        {ci.resource_type}
                      </span>
                      <span className="text-xs text-[#ccc] truncate">{ci.display_name}</span>
                      <span className="text-[10px] text-[#555]">{ci.active_count} active</span>
                    </div>
                    <div className="flex items-center gap-3 text-[10px] shrink-0">
                      <span className="text-[#8A8D90]">${ci.total_hourly_cost?.toFixed(1)}/h</span>
                      {ci.failing_count > 0 && <span className="text-[#C9190B]">{ci.failing_count} failing</span>}
                      {ci.cost_per_successful_session && <span className="text-[#6A6E73]">${ci.cost_per_successful_session.toFixed(2)}/session</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {/* Optimization opportunities */}
          {fc.optimization_opportunities?.length > 0 && (
            <div>
              <div className="text-[10px] text-[#8A8D90] uppercase mb-1.5">Optimization Opportunities</div>
              {fc.optimization_opportunities.map((o: any, i: number) => (
                <div key={i} className="flex items-center justify-between bg-[#1a1a1a] rounded px-2.5 py-1.5 border border-[#2a2a2a] mb-1">
                  <span className="text-[11px] text-[#ccc]">{o.description}</span>
                  <span className="text-[10px] text-[#3E8635] font-medium shrink-0">${o.monthly_savings?.toLocaleString(undefined, {maximumFractionDigits: 0})}/mo</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}


/* ---- Remediation Strategies ---- */

function RemediationStrategies() {
  const { data } = useQuery({ queryKey: ['remediation-strategies'], queryFn: () => api.getRemediationStrategies(), refetchInterval: 60000 });
  const [expanded, setExpanded] = useState<number | null>(null);
  if (!data?.strategies?.length) return null;

  const LEVEL_COLORS: Record<string, string> = { platform: '#C9190B', lab: '#F0AB00', cluster: '#4394E5', namespace: '#8A8D90' };
  const SEV_COLORS: Record<string, string> = { critical: '#C9190B', high: '#F0AB00', medium: '#4394E5', low: '#6A6E73' };

  return (
    <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] mb-4 p-4">
      <h3 className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider mb-3">Remediation Strategies — Highest Impact First</h3>
      <div className="space-y-1">
        {data.strategies.slice(0, 10).map((s: any, i: number) => (
          <div key={i} className="bg-[#1a1a1a] rounded border border-[#2a2a2a]">
            <div className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-[#222] transition"
              onClick={() => setExpanded(expanded === i ? null : i)}>
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-[9px] px-1.5 py-0.5 rounded font-medium shrink-0"
                  style={{ backgroundColor: `${LEVEL_COLORS[s.level]}20`, color: LEVEL_COLORS[s.level] }}>{s.level}</span>
                <span className="text-xs text-white truncate">{s.title}</span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-[10px]" style={{ color: SEV_COLORS[s.severity] }}>{s.blast_radius} ns</span>
                <span className="text-[9px] px-1.5 py-0.5 rounded" style={{ backgroundColor: '#22222280', color: '#8A8D90' }}>{s.action_type?.replace(/_/g, ' ')}</span>
              </div>
            </div>
            {expanded === i && (
              <div className="px-3 pb-3 border-t border-[#2e2e2e] pt-2 space-y-1.5">
                <p className="text-[11px] text-white">{s.recommendation}</p>
                <p className="text-[10px] text-[#6A6E73]">{s.evidence}</p>
                {s.expected_impact && <p className="text-[10px] text-[#3E8635]">{s.expected_impact}</p>}
                {s.agnosticv_url && (
                  <a href={s.agnosticv_url} target="_blank" rel="noopener noreferrer"
                    className="text-[10px] text-[#4394E5] hover:underline font-mono block">{s.agnosticv_url.split('/tree/main/')[1] || s.agnosticv_url}</a>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}


const STAGES = ['health', 'pods', 'storage', 'network', 'workload', 'overall'] as const;
const STAGE_LABELS: Record<string, string> = { health: 'HLT', pods: 'POD', storage: 'STG', network: 'NET', workload: 'WRK', overall: 'ALL' };
const STATUS_COLORS: Record<string, string> = { green: '#3E8635', yellow: '#F0AB00', red: '#C9190B', gray: '#555' };


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
  return `${Math.floor(hrs / 24)}d ago`;
}

function SummaryBar({ health, counts }: { health: Record<string, string>; counts: Record<string, Record<string, number>> }) {
  return (
    <div className="grid grid-cols-6 gap-2 mb-4">
      {STAGES.map(s => {
        const status = health[s] || 'gray';
        const c = counts?.[s] || {};
        const total = (c.green || 0) + (c.yellow || 0) + (c.red || 0);
        const pct = total ? Math.round(((c.green || 0) / total) * 100) : 0;
        return (
          <div key={s} className="rounded-lg p-2.5" style={{ backgroundColor: '#1e1e1e', border: `1px solid ${STATUS_COLORS[status]}40` }}>
            <div className="flex items-center gap-1.5 mb-0.5">
              <div className="w-2 h-2 rounded-full" style={{ backgroundColor: STATUS_COLORS[status] }} />
              <span className="text-[10px] font-medium text-[#ccc] uppercase">{STAGE_LABELS[s]}</span>
            </div>
            <div className="text-lg font-bold text-white">{pct}%</div>
            <div className="text-[9px] text-[#6A6E73]">{c.green || 0} ok · {c.red || 0} fail</div>
          </div>
        );
      })}
    </div>
  );
}


/* ---- Expanded Row Detail ---- */

function ExpandedRow({ namespace }: { namespace: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ['ns-detail', namespace],
    queryFn: () => api.getNamespaceDetail(namespace),
    enabled: !!namespace,
  });

  const [cmdOutputs, setCmdOutputs] = useState<Record<string, { output: string; exit_code: number; loading?: boolean }>>({});
  const [aiAnalysis, setAiAnalysis] = useState<{ text: string; llmMetricId?: number } | null>(null);
  const [aiLoading, setAiLoading] = useState(false);

  const runCmd = (cmd: string, key: string) => {
    if (!data) return;
    setCmdOutputs(prev => ({ ...prev, [key]: { output: '', exit_code: 0, loading: true } }));
    api.runDiagnostic({ command: cmd, namespace, cluster: data.cluster })
      .then(r => setCmdOutputs(prev => ({ ...prev, [key]: { output: r.output, exit_code: r.exit_code } })))
      .catch(e => setCmdOutputs(prev => ({ ...prev, [key]: { output: `Error: ${e.message}`, exit_code: -1 } })));
  };

  const runAll = () => {
    (data?.catalog_commands || []).forEach((cmd: string, i: number) => runCmd(cmd, `cat-${i}`));
  };

  const getAiAnalysis = () => {
    if (!data?.issues?.[0]) return;
    setAiLoading(true);
    setAiAnalysis(null);
    api.getRemediation({ failure_class: data.issues[0].failure_class, lab_code: namespace, cluster: data.cluster, context_type: 'lab' })
      .then((r: any) => {
        setAiAnalysis({ text: r?.llm_analysis || r?.analysis || r?.remediation || JSON.stringify(r, null, 2), llmMetricId: r?.llm_metric_id });
        setAiLoading(false);
      })
      .catch(() => setAiLoading(false));
  };

  if (isLoading) return <div className="text-[#6A6E73] py-4 text-center text-xs">Loading...</div>;
  if (!data) return null;

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4">
      {/* Left column: Issues + Diagnostics */}
      <div className="space-y-4">
        {/* Issues */}
        <div>
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-[#6A6E73] mb-1.5">Issues</h4>
          {data.issues?.map((iss: any, i: number) => (
            <div key={i} className="bg-[#1a1a1a] rounded p-2 border border-[#2e2e2e] mb-1">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium" style={{ color: iss.severity === 'warning' ? '#F0AB00' : '#C9190B' }}>{iss.failure_class}</span>
                <span className="text-[10px] text-[#6A6E73]">{iss.count}× · {relativeTime(iss.last_seen)}</span>
              </div>
              {iss.sub_class && (
                <div className="flex items-center gap-1.5 mt-0.5">
                  <span className="text-[10px] px-1 py-0.5 rounded bg-[#333] text-[#ccc]">{iss.sub_class}</span>
                  {iss.workload && <span className="text-[10px] text-[#555]">{iss.workload}</span>}
                  {iss.auto_fix_confidence && (
                    <span className={`text-[10px] px-1 py-0.5 rounded ${
                      iss.auto_fix_confidence === 'high' ? 'bg-[#3E8635]/20 text-[#3E8635]' :
                      iss.auto_fix_confidence === 'medium' ? 'bg-[#F0AB00]/20 text-[#F0AB00]' :
                      'bg-[#555]/20 text-[#8A8D90]'
                    }`}>{iss.auto_fix_confidence} fix</span>
                  )}
                </div>
              )}
              {iss.message && <p className="text-[10px] text-[#8A8D90] mt-0.5 font-mono truncate">{iss.message}</p>}
            </div>
          ))}
        </div>

        {/* Diagnostics */}
        {data.catalog_commands?.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <h4 className="text-[10px] font-semibold uppercase tracking-wider text-[#6A6E73]">Diagnostics</h4>
              <button onClick={runAll} className="text-[10px] text-[#4394E5] hover:underline">Run All</button>
            </div>
            {data.catalog_commands.map((cmd: string, i: number) => {
              const key = `cat-${i}`;
              const result = cmdOutputs[key];
              return (
                <div key={i} className="mb-1.5">
                  <div className="flex items-center gap-1.5">
                    <pre className="flex-1 bg-[#0d0d0d] border border-[#333] rounded px-2 py-1 text-[10px] text-[#4EC9B0] font-mono overflow-x-auto">{cmd}</pre>
                    <button className="bg-[#333] hover:bg-[#444] text-white text-[10px] px-2 py-0.5 rounded shrink-0 disabled:opacity-50"
                      disabled={result?.loading} onClick={() => runCmd(cmd, key)}>
                      {result?.loading ? '...' : result ? 'Re-run' : 'Run'}
                    </button>
                  </div>
                  {result && !result.loading && (
                    <pre className={`mt-0.5 text-[10px] rounded px-2 py-1 font-mono overflow-x-auto max-h-40 overflow-y-auto ${
                      result.exit_code === 0 ? 'bg-[#0d1f0d] text-[#4ade80] border border-[#1a3a1a]' : 'bg-[#1f0d0d] text-[#f87171] border border-[#3a1a1a]'
                    }`}>{result.output || '(no output)'}</pre>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Feedback */}
        {data.issues?.length > 0 && (
          <div>
            <h4 className="text-[10px] font-semibold uppercase tracking-wider text-[#6A6E73] mb-1.5">Notes</h4>
            <IssueFeedbackPanel namespace={namespace} cluster={data.cluster} failure_class={data.issues[0].failure_class} />
          </div>
        )}
      </div>

      {/* Right column: AI Analysis + Incidents + History */}
      <div className="space-y-4">
        {/* AI Analysis */}
        <div>
          <h4 className="text-[10px] font-semibold uppercase tracking-wider text-[#6A6E73] mb-1.5">AI Analysis</h4>
          {!aiAnalysis ? (
            <button className="bg-[#EE0000] hover:bg-[#A30000] text-white text-xs px-4 py-1.5 rounded w-full disabled:opacity-50"
              disabled={aiLoading || !data.issues?.length} onClick={getAiAnalysis}>
              {aiLoading ? 'Analyzing...' : 'Get AI Analysis'}
            </button>
          ) : (
            <div className="space-y-2">
              <FormattedAnalysis text={aiAnalysis.text} namespace={namespace} cluster={data.cluster} />
              <AiAnalysisFeedback llmMetricId={aiAnalysis.llmMetricId} />
            </div>
          )}
        </div>

        {/* Incidents */}
        {data.incidents?.length > 0 && (
          <div>
            <h4 className="text-[10px] font-semibold uppercase tracking-wider text-[#6A6E73] mb-1.5">Incidents ({data.incidents.length})</h4>
            {data.incidents.map((inc: any) => (
              <div key={inc.id} className="bg-[#1a1a1a] rounded p-2 border border-[#2e2e2e] mb-1">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-[#4394E5]">{inc.failure_class || inc.action_type}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                    inc.status === 'pending' ? 'bg-[#F0AB00]/20 text-[#F0AB00]' :
                    inc.status === 'auto_resolved' ? 'bg-[#3E8635]/20 text-[#3E8635]' :
                    'bg-[#555]/30 text-[#8A8D90]'
                  }`}>{inc.status}</span>
                </div>
                {inc.rca_summary && <p className="text-[10px] text-[#8A8D90] mt-0.5">{typeof inc.rca_summary === 'string' ? inc.rca_summary.slice(0, 150) : ''}</p>}
                <div className="flex items-center gap-2 mt-1 text-[9px] text-[#555]">
                  <span>{inc.proposed_by}</span>
                  <span>{relativeTime(inc.proposed_at)}</span>
                  {inc.signal_count > 0 && <span>{inc.signal_count} signals</span>}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Shadow */}
        {data.shadow?.length > 0 && (
          <div>
            <h4 className="text-[10px] font-semibold uppercase tracking-wider text-[#6A6E73] mb-1.5">Shadow Tracking</h4>
            {data.shadow.map((sh: any, i: number) => (
              <div key={i} className="flex items-center justify-between py-1 border-b border-[#222] text-xs">
                <span className="text-[#ccc]">{sh.failure_class}</span>
                {sh.resolved ? <span className="text-[10px] text-[#3E8635]">resolved ({sh.resolution_cause})</span> : <span className="text-[10px] text-[#F0AB00]">tracking</span>}
              </div>
            ))}
          </div>
        )}

        {/* Eval History */}
        {data.eval_history?.length > 0 && (
          <div>
            <h4 className="text-[10px] font-semibold uppercase tracking-wider text-[#6A6E73] mb-1.5">Recent Evaluations</h4>
            {data.eval_history.map((ev: any, i: number) => (
              <div key={i} className="flex items-center gap-2 py-0.5 border-b border-[#222] text-[10px]">
                <span className="text-[#555] w-12 shrink-0">{relativeTime(ev.evaluated_at)}</span>
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${ev.outcome === 'pass' ? 'bg-[#3E8635]' : 'bg-[#C9190B]'}`} />
                <span className="text-[#8A8D90] truncate">{ev.failure_class || ev.outcome}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/* ---- Catalog Item History ---- */

function CatalogItemHistory() {
  const { data, isLoading } = useQuery({
    queryKey: ['catalog-item-history'],
    queryFn: () => api.getCatalogItemHistory(7),
    refetchInterval: 60000,
  });
  const [expanded, setExpanded] = useState<string | null>(null);

  if (isLoading || !data?.items?.length) return null;

  const REC_COLORS: Record<string, string> = {
    watch_and_wait: '#3E8635', investigate: '#F0AB00', candidate_for_automation: '#4394E5', insufficient_data: '#555',
  };

  return (
    <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] mb-4 p-4">
      <h3 className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider mb-3">Lab Health — 7 Day History</h3>
      <div className="space-y-1">
        {data.items.slice(0, 15).map((item: any) => {
          const isOpen = expanded === item.catalog_item;
          return (
            <div key={item.catalog_item} className="bg-[#1a1a1a] rounded border border-[#2a2a2a]">
              <div className="flex items-center justify-between px-3 py-2 cursor-pointer hover:bg-[#222] transition"
                onClick={() => setExpanded(isOpen ? null : item.catalog_item)}>
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-[#555] text-xs">{isOpen ? '▼' : '▶'}</span>
                  <span className="text-xs text-white font-medium truncate">{item.display_name}</span>
                  <span className="text-[10px] text-[#6A6E73] font-mono shrink-0">{item.catalog_item}</span>
                </div>
                <div className="flex items-center gap-3 text-[10px] shrink-0">
                  <span className="text-[#8A8D90]">{item.namespace_count} ns</span>
                  <span className="text-[#C9190B]">{item.total_fails.toLocaleString()} fails</span>
                  <span className="text-[#6A6E73]">{item.fail_rate_pct}%</span>
                </div>
              </div>
              {isOpen && (
                <div className="px-3 pb-3 border-t border-[#2e2e2e] pt-2">
                  {item.agnosticv_url && (
                    <a href={item.agnosticv_url} target="_blank" rel="noopener noreferrer"
                      className="text-[10px] text-[#4394E5] hover:underline block mb-2 font-mono">
                      {item.agnosticv_path}
                    </a>
                  )}
                  <div className="space-y-1.5">
                    {item.failure_classes.map((fc: any) => {
                      const res = fc.resolutions;
                      const rec = res?.recommendation;
                      return (
                        <div key={fc.failure_class} className="bg-[#111] rounded p-2">
                          <div className="flex items-center justify-between mb-1">
                            <div className="flex items-center gap-2">
                              <span className="text-[11px] font-mono text-[#ccc]">{fc.failure_class}</span>
                              <span className="text-[10px] text-[#6A6E73]">{fc.count.toLocaleString()} ({fc.pct_of_failures}%)</span>
                              <span className="text-[10px] text-[#8A8D90]">{fc.affected_namespaces} ns</span>
                            </div>
                            {rec && (
                              <span className="text-[9px] px-1.5 py-0.5 rounded font-medium"
                                style={{ backgroundColor: `${REC_COLORS[rec] || '#555'}20`, color: REC_COLORS[rec] || '#555' }}>
                                {rec.replace(/_/g, ' ')}
                              </span>
                            )}
                          </div>
                          {res && (
                            <div className="flex items-center gap-3 text-[10px] text-[#8A8D90]">
                              <span>{res.self_resolve_pct}% self-resolve</span>
                              {res.avg_ttr_minutes && <span>{res.avg_ttr_minutes}m avg TTR</span>}
                              {res.p95_ttr_minutes && <span>P95: {res.p95_ttr_minutes}m</span>}
                              <span>{res.total} resolutions</span>
                              {Object.entries(res.by_type || {}).map(([type, count]) => (
                                <span key={type} className="text-[#6A6E73]">{(type as string).replace(/_/g, ' ')}: {count as number}</span>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}


/* ---- Main Page ---- */

const ATTENTION_COLORS: Record<string, string> = { stuck: '#C9190B', anomalous: '#F0AB00', provisioning: '#4394E5', expected: '#555' };
const FC_ATTENTION_COLORS: Record<string, string> = { spiking: '#C9190B', spreading: '#F0AB00', stuck: '#C9190B', concentrated: '#4394E5', normal: '#3E8635' };

function FailureClassCard({ fc, namespaces }: { fc: any; namespaces: any[] }) {
  const [expanded, setExpanded] = useState(false);
  const [aiAnalysis, setAiAnalysis] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);

  const getAiAnalysis = () => {
    const affectedNs = namespaces.filter((n: any) =>
      Object.keys(n.stages || {}).some(s => n.stages[s]?.detail?.includes(fc.failure_class))
      || n.top_failure === fc.failure_class
    );
    const sampleNs = affectedNs[0]?.namespace || '';
    const sampleCluster = affectedNs[0]?.cluster || '';
    if (!sampleNs) return;

    setAiLoading(true);
    setAiAnalysis(null);
    api.getRemediation({
      failure_class: fc.failure_class,
      lab_code: sampleNs,
      cluster: sampleCluster,
      context_type: 'failure_class',
    }).then((r: any) => {
      setAiAnalysis(r?.llm_analysis || r?.analysis || JSON.stringify(r, null, 2));
      setAiLoading(false);
    }).catch(() => { setAiAnalysis('Analysis failed'); setAiLoading(false); });
  };

  const attColor = FC_ATTENTION_COLORS[fc.attention] || '#3E8635';

  return (
    <div className="bg-[#1a1a1a] rounded p-2.5 border border-[#2a2a2a]">
      <div className="flex items-center justify-between mb-1 cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <div className="flex items-center gap-2">
          <span className="text-[#555] text-[10px]">{expanded ? '▼' : '▶'}</span>
          <span className="text-xs font-mono text-[#ccc]">{fc.failure_class}</span>
        </div>
        {fc.attention !== 'normal' && (
          <span className="text-[9px] px-1.5 py-0.5 rounded font-medium"
            style={{ backgroundColor: `${attColor}20`, color: attColor }}>{fc.attention}</span>
        )}
      </div>
      <p className="text-[10px] text-[#6A6E73] mb-1.5">{fc.attention_reason}</p>
      <div className="flex items-center gap-3 text-[10px]">
        <span className="text-[#8A8D90]">{fc.affected_namespaces} ns</span>
        <span className="text-[#8A8D90]">{fc.affected_catalog_items?.length || 0} labs</span>
        <span className="text-[#8A8D90]">{fc.affected_clusters?.length || 0} clusters</span>
        {fc.stuck_count > 0 && <span className="text-[#C9190B]">{fc.stuck_count} stuck</span>}
        {fc.self_resolve_pct != null && <span className="text-[#3E8635]">{fc.self_resolve_pct}% self-resolve</span>}
      </div>
      {fc.affected_catalog_items?.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1.5">
          {fc.affected_catalog_items.slice(0, 4).map((c: any) => (
            <span key={c.catalog_item} className="text-[9px] px-1.5 py-0.5 bg-[#222] rounded text-[#8A8D90]">
              {c.catalog_item} <span className="text-[#555]">×{c.count}</span>
            </span>
          ))}
        </div>
      )}
      {expanded && (
        <div className="mt-2 pt-2 border-t border-[#2e2e2e]">
          {fc.affected_clusters?.length > 0 && (
            <div className="flex flex-wrap gap-1 mb-2">
              {fc.affected_clusters.map((c: any) => (
                <span key={c.cluster} className="text-[9px] px-1.5 py-0.5 bg-[#222] rounded text-[#6A6E73]">
                  {c.cluster} <span className="text-[#555]">×{c.count}</span>
                </span>
              ))}
            </div>
          )}
          {fc.resolutions_24h && (
            <div className="flex flex-wrap gap-2 mb-2 text-[10px]">
              {Object.entries(fc.resolutions_24h).map(([type, count]) => (
                <span key={type} className="text-[#8A8D90]">{(type as string).replace(/_/g, ' ')}: {count as number}</span>
              ))}
            </div>
          )}
          <button onClick={getAiAnalysis} disabled={aiLoading}
            className="text-[10px] px-2 py-1 rounded bg-[#222] text-[#4394E5] hover:bg-[#333] transition disabled:opacity-50">
            {aiLoading ? 'Analyzing...' : 'AI Analysis'}
          </button>
          {aiAnalysis && (
            <div className="mt-2 bg-[#111] rounded p-2 text-[10px] text-[#ccc] whitespace-pre-wrap max-h-48 overflow-y-auto">
              <FormattedAnalysis text={aiAnalysis} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function Operations() {
  const [search, setSearch] = useState('');
  const [expandedNs, setExpandedNs] = useState<string | null>(null);
  const [attentionFilter, setAttentionFilter] = useState<string>('needs_attention');
  const [tab, setTab] = useState<'operations' | 'cost' | 'labs' | 'strategies'>('operations');

  const { data, isLoading, error } = useQuery({
    queryKey: ['lifecycle-matrix'],
    queryFn: () => api.getLifecycleMatrix(),
    refetchInterval: 30000,
  });


  const filterData = (items: any[], fields: string[]) => {
    if (!search) return items;
    const q = search.toLowerCase();
    return items.filter(r => fields.some(f => (r[f] || '').toLowerCase().includes(q)));
  };

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-4">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>Operations</h1>
          <p className="text-[#6A6E73] text-xs">
            {data?.summary?.total_monitored || 0} namespaces monitored
            {data?.summary?.needs_attention ? <> — <span className="text-[#C9190B] font-medium">{data.summary.needs_attention} need attention</span></> : null}
            {data?.summary?.expected_noise ? <> · <span className="text-[#555]">{data.summary.expected_noise} expected noise</span></> : null}
          </p>
        </div>
        {tab === 'operations' && (
          <div className="flex items-center gap-2">
            <div className="flex bg-[#1e1e1e] border border-[#333] rounded overflow-hidden text-xs">
              {[
                { key: 'needs_attention', label: 'Needs Attention', count: (data?.summary?.attention_counts?.stuck || 0) + (data?.summary?.attention_counts?.anomalous || 0) },
                { key: 'all', label: 'All', count: data?.summary?.total_namespaces || 0 },
              ].map(f => (
                <button key={f.key}
                  onClick={() => setAttentionFilter(f.key)}
                  className={`px-3 py-1.5 transition ${attentionFilter === f.key ? 'bg-[#333] text-white' : 'text-[#8A8D90] hover:text-white'}`}>
                  {f.label} {f.count > 0 && <span className="text-[10px] ml-1 opacity-60">{f.count}</span>}
                </button>
              ))}
            </div>
            <input type="text" value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search namespace, lab, cluster..."
              className="bg-[#1e1e1e] border border-[#333] rounded px-3 py-1.5 text-sm text-white placeholder-[#555] w-64 focus:outline-none focus:border-[#4394E5]" />
          </div>
        )}
      </div>

      {isLoading && <div className="text-[#6A6E73] py-12 text-center">Loading...</div>}
      {error && <div className="text-[#C9190B] py-12 text-center">Error: {(error as Error).message}</div>}

      {data && (
        <>
          <KpiDashboard />

          {/* Tab bar */}
          <div className="flex gap-1 mb-4 border-b border-[#333]">
            {[
              { key: 'operations', label: 'Operations' },
              { key: 'cost', label: 'Cost' },
              { key: 'labs', label: 'Labs' },
              { key: 'strategies', label: 'Strategies' },
            ].map(t => (
              <button key={t.key} onClick={() => setTab(t.key as any)}
                className={`px-4 py-2 text-xs font-medium transition ${tab === t.key ? 'text-white border-b-2 border-[#EE0000]' : 'text-[#8A8D90] hover:text-white'}`}>
                {t.label}
              </button>
            ))}
          </div>

          {/* Tab: Operations */}
          {tab === 'operations' && (
            <>
              <SummaryBar health={data.summary?.stages_health || {}} counts={data.summary?.stage_counts || {}} />

              {/* Failure Class Correlation */}
              {data.by_failure_class?.length > 0 && (
                <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] mb-4 p-4">
                  <h3 className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider mb-3">Failure Classes — Platform-Wide</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                    {data.by_failure_class.slice(0, 12).map((fc: any) => (
                      <FailureClassCard key={fc.failure_class} fc={fc} namespaces={data.by_namespace || []} />
                    ))}
                  </div>
                </div>
              )}

              <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] min-h-[300px]">
                {(() => {
                  const allRows = filterData(data.by_namespace || [], ['namespace', 'cluster', 'top_failure', 'catalog_item']);
                  const rows = attentionFilter === 'needs_attention'
                    ? allRows.filter((r: any) => r.attention === 'stuck' || r.attention === 'anomalous')
                    : allRows;
                  return (
                    <div>
                      {/* Header */}
                      <div className="grid grid-cols-[20px_200px_100px_72px_repeat(6,44px)_120px_100px_1fr] gap-0 border-b border-[#333] px-3 py-2 text-[#8A8D90] text-xs font-medium">
                        <span></span>
                        <span>Namespace</span>
                        <span>Lab</span>
                        <span>Cluster</span>
                        {STAGES.map(s => <span key={s} className="text-center text-[10px] uppercase">{STAGE_LABELS[s]}</span>)}
                        <span>Top Failure</span>
                        <span>Owner</span>
                        <span>Last Resolution</span>
                      </div>
                      {/* Rows */}
                      {rows.slice(0, 100).map((r: any, i: number) => {
                        const isExpanded = expandedNs === r.namespace;
                        const res = r.last_resolution;
                        const resColor = res?.resolution_type === 'self_resolved' ? '#6A6E73'
                          : res?.resolution_type === 'stargate_remediated' ? '#3E8635'
                          : res?.resolution_type === 'human_remediated' ? '#4394E5'
                          : res?.resolution_type === 'namespace_recycled' ? '#6A6E73'
                          : '#8A8D90';
                        return (
                          <div key={`${r.namespace}-${i}`}>
                            <div
                              className={`grid grid-cols-[20px_200px_100px_72px_repeat(6,44px)_120px_100px_1fr] gap-0 items-center px-3 py-2 border-b border-[#222] cursor-pointer transition ${isExpanded ? 'bg-[#1e1e1e]' : 'hover:bg-[#1a1a1a]'}`}
                              onClick={() => setExpandedNs(isExpanded ? null : r.namespace)}
                            >
                              <span className="text-[#555] text-xs">{isExpanded ? '▼' : '▶'}</span>
                              <div className="flex items-center gap-1.5 truncate">
                                <span className="text-[#4394E5] font-mono text-xs truncate" title={r.namespace}>{r.namespace}</span>
                                {r.attention && r.attention !== 'expected' && (
                                  <span className="text-[9px] px-1.5 py-0.5 rounded font-medium shrink-0"
                                    style={{ backgroundColor: `${ATTENTION_COLORS[r.attention]}20`, color: ATTENTION_COLORS[r.attention] }}
                                    title={r.attention_reason}>{r.attention}</span>
                                )}
                              </div>
                              <span className="text-[#ccc] text-[10px] truncate" title={`${r.lab_name || r.catalog_item} (${r.catalog_item})`}>{r.lab_name || r.catalog_item || ''}</span>
                              <span className="text-[#8A8D90] text-xs">{r.cluster}</span>
                              {STAGES.map(s => (
                                <span key={s} className="flex justify-center">
                                  <span className="w-3 h-3 rounded-full" style={{ backgroundColor: STATUS_COLORS[r.stages?.[s]?.status || 'green'] }} title={r.stages?.[s]?.detail || ''} />
                                </span>
                              ))}
                              <span className="text-xs text-[#C9190B] truncate" title={r.attention_reason}>{r.top_failure || ''}</span>
                              <span className="text-[10px] text-[#8A8D90] truncate" title={r.owner}>{r.owner ? r.owner.split('@')[0] : ''}</span>
                              <span className="text-[10px] truncate" style={{ color: resColor }}>
                                {res ? `${res.resolution_type.replace(/_/g, ' ')}${res.ttr_minutes ? ` · ${res.ttr_minutes}m` : ''}` : ''}
                              </span>
                            </div>
                            {isExpanded && (
                              <div className="border-b border-[#333] bg-[#191919]">
                                <ExpandedRow namespace={r.namespace} />
                              </div>
                            )}
                          </div>
                        );
                      })}
                      {rows.length === 0 && (
                        <div className="px-3 py-8 text-center text-[#3E8635] text-sm">All namespaces healthy</div>
                      )}
                    </div>
                  );
                })()}
              </div>
            </>
          )}

          {/* Tab: Cost */}
          {tab === 'cost' && <CostAnalysis alwaysOpen />}

          {/* Tab: Labs */}
          {tab === 'labs' && <CatalogItemHistory />}

          {/* Tab: Strategies */}
          {tab === 'strategies' && <RemediationStrategies />}
        </>
      )}
    </div>
  );
}
