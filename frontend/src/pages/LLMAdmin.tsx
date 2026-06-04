import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useLLMMetrics, useLLMConfig, useLLMDrift, useLLMEvaluation, useLLMABTest, useLLMAccuracy, useLLMTimeline } from '../api/hooks';
import { useTimeRange } from '../components/TimeRangeContext';
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

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit' });
}

function HourlyChart({ timeline }: { timeline: any }) {
  if (!timeline?.hours?.length) return null;
  const maxCalls = Math.max(...(timeline.calls as number[]), 1);
  return (
    <div className="flex items-end gap-[2px] h-16">
      {(timeline.hours as string[]).map((h: string, i: number) => {
        const calls = (timeline.calls as number[])[i] ?? 0;
        const errors = (timeline.errors as number[])[i] ?? 0;
        const height = (calls / maxCalls) * 100;
        const hasErrors = errors > 0;
        return (
          <div key={h} className="flex-1 flex flex-col justify-end" title={`${h}: ${calls} calls, ${errors} errors`}>
            <div className="rounded-t" style={{ height: `${Math.max(height, 2)}%`, backgroundColor: hasErrors ? '#C9190B' : '#3E8635', minHeight: '2px' }} />
          </div>
        );
      })}
    </div>
  );
}

export default function LLMAdmin() {
  const metrics = useLLMMetrics();
  const config = useLLMConfig();
  const drift = useLLMDrift();
  const evaluation = useLLMEvaluation();
  const abTest = useLLMABTest();
  const accuracy = useLLMAccuracy();
  const timeline = useLLMTimeline(24);
  const { cluster } = useTimeRange();
  const [endpointFilter, setEndpointFilter] = useState<string>('');
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const recent = useQuery({
    queryKey: ['llm-recent', endpointFilter, cluster],
    queryFn: () => api.getLLMRecent(50, endpointFilter || undefined, cluster || undefined),
    refetchInterval: 15_000,
  });

  const m = metrics.data as any;
  const calls = (recent.data ?? []) as any[];
  const cfg = config.data as any;
  const driftData = drift.data as any;
  const evalData = evaluation.data as any;
  const abData = abTest.data as any;
  const accData = accuracy.data as any;
  const tlData = timeline.data as any;

  const endpoints = m?.calls_by_endpoint ? Object.keys(m.calls_by_endpoint) : [];

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2" style={{ fontFamily: 'Red Hat Display' }}>LLM Admin</h1>
        <p className="text-[#6A6E73]">Model metrics, drift detection, accuracy, and configuration</p>
      </div>

      {/* Metrics cards */}
      {m ? (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <MetricCard label="Total Calls" value={m.total_calls ?? 0} sub={`${m.calls_last_24h ?? 0} last 24h`} />
          <MetricCard label="Total Tokens" value={(m.total_tokens ?? 0).toLocaleString()} />
          <MetricCard label="Est. Cost" value={`$${(m.total_cost_estimate ?? 0).toFixed(4)}`} />
          <MetricCard label="Error Rate" value={`${((m.error_rate ?? 0) * 100).toFixed(1)}%`} />
          <MetricCard label="Avg Confidence" value={m.avg_confidence != null ? `${(m.avg_confidence * 100).toFixed(0)}%` : '--'} />
        </div>
      ) : (
        <p className="text-[#6A6E73]">{metrics.isLoading ? 'Loading...' : 'No metrics available.'}</p>
      )}

      {/* Hourly Timeline */}
      {tlData && (
        <section>
          <SectionHeader>24h Call Volume</SectionHeader>
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
            <HourlyChart timeline={tlData} />
            <div className="flex justify-between text-[10px] text-[#6A6E73] mt-1">
              <span>24h ago</span><span>now</span>
            </div>
          </div>
        </section>
      )}

      {/* Drift Detection */}
      {driftData && (
        <section>
          <SectionHeader>Drift Detection</SectionHeader>
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
            <div className="flex items-center gap-3 mb-3">
              <span className="text-sm text-white font-medium">Status:</span>
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{
                backgroundColor: driftData.status === 'stable' ? '#3E8635' : driftData.status === 'drifting' ? '#F0AB00' : '#C9190B',
                color: '#fff',
              }}>{driftData.status}</span>
            </div>
            {driftData.alerts?.length > 0 && (
              <div className="space-y-1 mb-3">
                {driftData.alerts.map((a: any, i: number) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: a.severity === 'critical' ? '#C9190B' : '#F0AB00' }} />
                    <span className="text-[#d2d2d2]">{a.message}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="grid grid-cols-2 gap-4 text-xs">
              <div><span className="text-[#6A6E73]">Recent (7d): </span><span className="text-white">{driftData.recent?.calls ?? 0} calls, {driftData.recent?.avg_latency ?? 0}ms avg</span></div>
              <div><span className="text-[#6A6E73]">Prior (7d): </span><span className="text-white">{driftData.prior?.calls ?? 0} calls, {driftData.prior?.avg_latency ?? 0}ms avg</span></div>
            </div>
          </div>
        </section>
      )}

      {/* Accuracy & Evaluation */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {accData && (
          <section>
            <SectionHeader>Classification Accuracy</SectionHeader>
            <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><span className="text-[#6A6E73]">Accuracy: </span><span className="text-white font-bold">{accData.accuracy != null ? `${(accData.accuracy * 100).toFixed(1)}%` : '--'}</span></div>
                <div><span className="text-[#6A6E73]">Total Evaluated: </span><span className="text-white">{accData.total_evaluated ?? 0}</span></div>
                <div><span className="text-[#6A6E73]">Correct: </span><span className="text-[#3E8635]">{accData.correct ?? 0}</span></div>
                <div><span className="text-[#6A6E73]">Incorrect: </span><span className="text-[#C9190B]">{accData.incorrect ?? 0}</span></div>
              </div>
            </div>
          </section>
        )}

        {evalData && (
          <section>
            <SectionHeader>Feedback Loop</SectionHeader>
            <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div><span className="text-[#6A6E73]">Proposals: </span><span className="text-white">{evalData.total_proposals ?? 0}</span></div>
                <div><span className="text-[#6A6E73]">Reviewed: </span><span className="text-white">{evalData.reviewed ?? 0}</span></div>
                <div><span className="text-[#6A6E73]">Approved: </span><span className="text-[#3E8635]">{evalData.approved ?? 0}</span></div>
                <div><span className="text-[#6A6E73]">Rejected: </span><span className="text-[#C9190B]">{evalData.rejected ?? 0}</span></div>
                <div><span className="text-[#6A6E73]">Approval Rate: </span><span className="text-white font-bold">{evalData.approval_rate ?? '--'}%</span></div>
                <div><span className="text-[#6A6E73]">Pending: </span><span className="text-[#F0AB00]">{evalData.pending_review ?? 0}</span></div>
              </div>
            </div>
          </section>
        )}
      </div>

      {/* A/B Test Results */}
      {abData?.versions && Object.keys(abData.versions).length > 0 && (
        <section>
          <SectionHeader>Prompt A/B Test</SectionHeader>
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
            <div className="grid grid-cols-[1fr_80px_100px_100px_80px_80px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
              <span>Version</span><span className="text-right">Calls</span><span className="text-right">Success Rate</span><span className="text-right">Avg Latency</span><span className="text-right">Tokens</span><span className="text-right">Cost</span>
            </div>
            {Object.entries(abData.versions).map(([v, d]: [string, any]) => (
              <div key={v} className="grid grid-cols-[1fr_80px_100px_100px_80px_80px] gap-3 items-center py-1.5 text-sm">
                <span className="text-white">{v}</span>
                <span className="text-white text-right">{d.calls}</span>
                <span className="text-right" style={{ color: d.success_rate >= 95 ? '#3E8635' : d.success_rate >= 80 ? '#F0AB00' : '#C9190B' }}>{d.success_rate}%</span>
                <span className="text-white text-right">{d.avg_latency_ms}ms</span>
                <span className="text-white text-right">{d.avg_tokens}</span>
                <span className="text-white text-right">${d.total_cost?.toFixed(4)}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Latency by endpoint */}
      {m && m.calls_by_endpoint && (
        <section>
          <SectionHeader>Latency by Endpoint</SectionHeader>
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
            <div className="grid grid-cols-[150px_80px_100px_100px_100px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
              <span>Endpoint</span><span className="text-right">Calls</span><span className="text-right">Avg (ms)</span><span className="text-right">P95 (ms)</span><span className="text-right">Tokens</span>
            </div>
            {Object.keys(m.calls_by_endpoint).map(ep => (
              <div key={ep} className="grid grid-cols-[150px_80px_100px_100px_100px] gap-3 items-center py-1.5">
                <span className="text-sm text-white">{ep}</span>
                <span className="text-sm text-white text-right">{m.calls_by_endpoint[ep]}</span>
                <span className="text-sm text-white text-right">{(m.avg_latency_ms?.[ep] ?? 0).toLocaleString()}</span>
                <span className="text-sm text-white text-right">{(m.p95_latency_ms?.[ep] ?? 0).toLocaleString()}</span>
                <span className="text-sm text-white text-right">{(m.tokens_by_endpoint?.[ep] ?? 0).toLocaleString()}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Recent calls */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <SectionHeader>Recent LLM Calls</SectionHeader>
          <div className="flex gap-1">
            <button onClick={() => setEndpointFilter('')} className={`text-xs px-3 py-1 rounded ${!endpointFilter ? 'bg-[#EE0000] text-white' : 'bg-[#2e2e2e] text-[#8A8D90] hover:bg-[#333]'}`}>All</button>
            {endpoints.map(ep => (
              <button key={ep} onClick={() => setEndpointFilter(endpointFilter === ep ? '' : ep)} className={`text-xs px-3 py-1 rounded ${endpointFilter === ep ? 'bg-[#EE0000] text-white' : 'bg-[#2e2e2e] text-[#8A8D90] hover:bg-[#333]'}`}>{ep}</button>
            ))}
          </div>
        </div>
        <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
          {calls.length === 0 ? (
            <p className="text-[#6A6E73] text-sm">{recent.isLoading ? 'Loading...' : 'No calls found.'}</p>
          ) : (
            <div className="space-y-0.5">
              <div className="grid grid-cols-[100px_80px_80px_80px_60px_1fr_140px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
                <span>Endpoint</span><span className="text-right">Tokens</span><span className="text-right">Latency</span><span className="text-right">Cost</span><span>Status</span><span>Context</span><span>Time</span>
              </div>
              {calls.slice(0, 30).map((c: any) => (
                <div key={c.id}>
                  <div className="grid grid-cols-[100px_80px_80px_80px_60px_1fr_140px] gap-3 items-center py-1.5 hover:bg-[#2a2a2a] rounded cursor-pointer" onClick={() => setExpandedId(expandedId === c.id ? null : c.id)}>
                    <span className="text-sm text-white">{c.endpoint}</span>
                    <span className="text-sm text-white text-right">{c.total_tokens}</span>
                    <span className="text-sm text-white text-right">{(c.latency_ms / 1000).toFixed(1)}s</span>
                    <span className="text-sm text-white text-right">${c.cost_estimate?.toFixed(4)}</span>
                    <span className={`text-xs font-bold ${c.success ? 'text-[#3E8635]' : 'text-[#C9190B]'}`}>{c.success ? 'OK' : 'ERR'}</span>
                    <span className="text-xs text-[#8A8D90] truncate">{c.failure_class || '--'}{c.lab_code && ` / ${c.lab_code}`}</span>
                    <span className="text-xs text-[#6A6E73]">{c.called_at ? formatTime(c.called_at) : '--'}</span>
                  </div>
                  {expandedId === c.id && (
                    <div className="bg-[#1a1a1a] border border-[#333] rounded-lg p-4 mb-2 mx-2 space-y-3">
                      <div className="grid grid-cols-[120px_1fr] gap-2 text-sm">
                        <span className="text-[#6A6E73]">Call ID</span><span className="text-white">#{c.id}</span>
                        <span className="text-[#6A6E73]">Model</span><span className="text-white">{c.model}</span>
                        <span className="text-[#6A6E73]">Prompt Tokens</span><span className="text-white">{c.prompt_tokens}</span>
                        <span className="text-[#6A6E73]">Completion Tokens</span><span className="text-white">{c.completion_tokens}</span>
                        <span className="text-[#6A6E73]">Confidence</span><span className="text-white">{c.confidence != null ? `${(c.confidence * 100).toFixed(0)}%` : '--'}</span>
                        {c.error_type && <><span className="text-[#6A6E73]">Error</span><span className="text-[#C9190B]">{c.error_type}</span></>}
                      </div>
                      {c.response_preview && (
                        <div>
                          <div className="text-xs text-[#6A6E73] uppercase font-bold mb-1">Response</div>
                          <div className="bg-[#151515] border border-[#2e2e2e] rounded p-3 max-h-[400px] overflow-y-auto">
                            <FormattedAnalysis text={c.response_preview} />
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* Config */}
      {cfg && (
        <section>
          <SectionHeader>Configuration</SectionHeader>
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
            <div className="grid grid-cols-[160px_1fr] gap-2 text-sm">
              <span className="text-[#6A6E73]">Model</span><span className="text-white">{cfg.model}</span>
              <span className="text-[#6A6E73]">API Endpoint</span><span className="text-white">{cfg.api_endpoint}</span>
              {cfg.prompts && Object.entries(cfg.prompts).map(([name, prompt]: [string, any]) => (
                <span key={name} className="contents">
                  <span className="text-[#6A6E73]">{name}</span>
                  <span className="text-white">max_tokens: {prompt.max_tokens} | temp: {prompt.temperature} | timeout: {prompt.timeout}s</span>
                </span>
              ))}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
