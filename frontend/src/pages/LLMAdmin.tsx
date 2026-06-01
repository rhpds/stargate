import { useLLMMetrics, useLLMRecent, useLLMConfig } from '../api/hooks';

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
  return new Date(iso).toLocaleString(undefined, { month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

export default function LLMAdmin() {
  const metrics = useLLMMetrics();
  const recent = useLLMRecent();
  const config = useLLMConfig();

  const m = metrics.data as any;
  const calls = (recent.data ?? []) as any[];
  const cfg = config.data as any;

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2" style={{ fontFamily: 'Red Hat Display' }}>LLM Admin</h1>
        <p className="text-[#6A6E73]">Model metrics, recent calls, and configuration</p>
      </div>

      {/* Metrics cards */}
      {m ? (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <MetricCard label="Total Calls" value={m.total_calls ?? 0} />
          <MetricCard label="Total Tokens" value={(m.total_tokens ?? 0).toLocaleString()} />
          <MetricCard label="Est. Cost" value={`$${(m.total_cost_estimate ?? 0).toFixed(4)}`} />
          <MetricCard label="Error Rate" value={`${(m.error_rate ?? 0).toFixed(1)}%`} />
          <MetricCard label="Model" value={cfg?.model ?? '--'} />
        </div>
      ) : (
        <p className="text-[#6A6E73]">{metrics.isLoading ? 'Loading...' : 'No metrics available.'}</p>
      )}

      {/* Latency by endpoint */}
      {m && m.calls_by_endpoint && (
        <section>
          <SectionHeader>Latency by Endpoint</SectionHeader>
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
            <div className="grid grid-cols-[150px_80px_100px_100px_100px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
              <span>Endpoint</span>
              <span className="text-right">Calls</span>
              <span className="text-right">Avg (ms)</span>
              <span className="text-right">P95 (ms)</span>
              <span className="text-right">Tokens</span>
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
        <SectionHeader>Recent LLM Calls</SectionHeader>
        <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
          {calls.length === 0 ? (
            <p className="text-[#6A6E73] text-sm">{recent.isLoading ? 'Loading...' : 'No recent calls.'}</p>
          ) : (
            <div className="space-y-0.5">
              <div className="grid grid-cols-[100px_80px_80px_80px_60px_1fr_120px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
                <span>Endpoint</span>
                <span className="text-right">Tokens</span>
                <span className="text-right">Latency</span>
                <span className="text-right">Cost</span>
                <span>Status</span>
                <span>Context</span>
                <span>Time</span>
              </div>
              {calls.slice(0, 20).map((c: any) => (
                <div key={c.id} className="grid grid-cols-[100px_80px_80px_80px_60px_1fr_120px] gap-3 items-center py-1.5 hover:bg-[#2a2a2a] rounded">
                  <span className="text-sm text-white">{c.endpoint}</span>
                  <span className="text-sm text-white text-right">{c.total_tokens}</span>
                  <span className="text-sm text-white text-right">{(c.latency_ms / 1000).toFixed(1)}s</span>
                  <span className="text-sm text-white text-right">${c.cost_estimate?.toFixed(4)}</span>
                  <span className={`text-xs font-bold ${c.success ? 'text-[#3E8635]' : 'text-[#C9190B]'}`}>
                    {c.success ? 'OK' : 'ERR'}
                  </span>
                  <span className="text-xs text-[#8A8D90] truncate" title={c.failure_class || c.lab_code || ''}>
                    {c.failure_class || c.lab_code || '--'}
                  </span>
                  <span className="text-xs text-[#6A6E73]">{c.called_at ? formatTime(c.called_at) : '--'}</span>
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
              <span className="text-[#6A6E73]">Model</span>
              <span className="text-white">{cfg.model}</span>
              <span className="text-[#6A6E73]">API Endpoint</span>
              <span className="text-white">{cfg.api_endpoint}</span>
              {cfg.prompts && Object.entries(cfg.prompts).map(([name, prompt]: [string, any]) => (
                <span key={name} className="contents">
                  <span className="text-[#6A6E73]">{name}</span>
                  <span className="text-white">
                    max_tokens: {prompt.max_tokens} | temp: {prompt.temperature} | timeout: {prompt.timeout}s | v{prompt.version}
                  </span>
                </span>
              ))}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
