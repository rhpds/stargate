import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

const STAGES = ['health', 'pods', 'storage', 'network', 'workload', 'overall'] as const;

const STAGE_LABELS: Record<string, string> = {
  health: 'Health',
  pods: 'Pods',
  storage: 'Storage',
  network: 'Network',
  workload: 'Workload',
  overall: 'Overall',
};

const STATUS_COLORS: Record<string, string> = {
  green: '#3E8635',
  yellow: '#F0AB00',
  red: '#C9190B',
  gray: '#555',
};

type Tab = 'namespace' | 'lab' | 'cluster';

function StatusDot({ status, detail }: { status: string; detail: string }) {
  const [hover, setHover] = useState(false);
  return (
    <td className="px-3 py-2 text-center relative">
      <div
        className="inline-block w-3.5 h-3.5 rounded-full cursor-default"
        style={{ backgroundColor: STATUS_COLORS[status] || '#555' }}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
      />
      {hover && detail && (
        <div className="absolute z-50 bg-[#1a1a1a] border border-[#444] rounded px-2 py-1 shadow-lg text-xs text-[#ccc] whitespace-nowrap -translate-x-1/2 left-1/2 top-full mt-1">
          {detail}
        </div>
      )}
    </td>
  );
}

function SummaryBar({ stages_health, stage_counts }: { stages_health: Record<string, string>; stage_counts: Record<string, Record<string, number>> }) {
  return (
    <div className="grid grid-cols-6 gap-2 mb-6">
      {STAGES.map(s => {
        const status = stages_health[s] || 'gray';
        const counts = stage_counts?.[s] || {};
        const total = (counts.green || 0) + (counts.yellow || 0) + (counts.red || 0);
        const greenPct = total ? Math.round(((counts.green || 0) / total) * 100) : 0;
        return (
          <div key={s} className="rounded-lg p-3" style={{ backgroundColor: '#1e1e1e', border: `1px solid ${STATUS_COLORS[status]}40` }}>
            <div className="flex items-center gap-2 mb-1">
              <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: STATUS_COLORS[status] }} />
              <span className="text-xs font-medium text-[#ccc] uppercase">{STAGE_LABELS[s]}</span>
            </div>
            <div className="text-lg font-bold text-white">{greenPct}%</div>
            <div className="text-[10px] text-[#6A6E73]">
              {counts.green || 0} ok · {counts.yellow || 0} warn · {counts.red || 0} fail
            </div>
          </div>
        );
      })}
    </div>
  );
}

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

function NamespaceDrawer({ namespace, onClose }: { namespace: string; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ['namespace-detail', namespace],
    queryFn: () => api.getNamespaceDetail(namespace),
    enabled: !!namespace,
  });

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/50" />
      <div
        className="relative w-[480px] h-full bg-[#151515] border-l border-[#333] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 bg-[#151515] border-b border-[#333] px-5 py-4 flex items-center justify-between z-10">
          <div>
            <h2 className="text-white font-semibold text-sm font-mono">{namespace}</h2>
            {data && (
              <p className="text-[#6A6E73] text-xs mt-0.5">
                {data.health_pct}% healthy · {data.total_evals} evals last hour
              </p>
            )}
          </div>
          <button onClick={onClose} className="text-[#6A6E73] hover:text-white text-lg px-2">✕</button>
        </div>

        {isLoading && <div className="text-[#6A6E73] py-12 text-center text-sm">Loading...</div>}

        {data && (
          <div className="px-5 py-4 space-y-6">
            {/* Issues */}
            <section>
              <h3 className="text-[#ccc] text-xs font-semibold uppercase tracking-wider mb-3 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: data.issues?.length ? '#C9190B' : '#3E8635' }} />
                Issues ({data.issues?.length || 0})
              </h3>
              {data.issues?.length > 0 ? (
                <div className="space-y-2">
                  {data.issues.map((iss: any, i: number) => (
                    <div key={i} className="bg-[#1e1e1e] rounded-lg p-3 border border-[#2e2e2e]">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm font-medium" style={{ color: iss.severity === 'warning' ? '#F0AB00' : '#C9190B' }}>
                          {iss.failure_class}
                        </span>
                        <span className="text-[10px] text-[#6A6E73]">{iss.count}× · {relativeTime(iss.last_seen)}</span>
                      </div>
                      {iss.sub_class && (
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs px-1.5 py-0.5 rounded bg-[#333] text-[#ccc]">{iss.sub_class}</span>
                          {iss.workload && <span className="text-[10px] text-[#6A6E73]">{iss.workload}</span>}
                          {iss.auto_fix_confidence && (
                            <span className={`text-[10px] px-1 py-0.5 rounded ${
                              iss.auto_fix_confidence === 'high' ? 'bg-[#3E8635]/20 text-[#3E8635]' :
                              iss.auto_fix_confidence === 'medium' ? 'bg-[#F0AB00]/20 text-[#F0AB00]' :
                              'bg-[#555]/20 text-[#8A8D90]'
                            }`}>
                              {iss.auto_fix_confidence} fix confidence
                            </span>
                          )}
                        </div>
                      )}
                      <p className="text-[#8A8D90] text-xs">{iss.message}</p>
                      <span className="text-[10px] text-[#555] mt-1 inline-block">{iss.cluster}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[#3E8635] text-xs">No active issues</p>
              )}
            </section>

            {/* Incidents */}
            <section>
              <h3 className="text-[#ccc] text-xs font-semibold uppercase tracking-wider mb-3 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: data.incidents?.length ? '#4394E5' : '#555' }} />
                Incidents ({data.incidents?.length || 0})
              </h3>
              {data.incidents?.length > 0 ? (
                <div className="space-y-2">
                  {data.incidents.map((inc: any) => (
                    <div key={inc.id} className="bg-[#1e1e1e] rounded-lg p-3 border border-[#2e2e2e]">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm text-[#4394E5]">{inc.failure_class || inc.action_type}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                          inc.status === 'pending' ? 'bg-[#F0AB00]/20 text-[#F0AB00]' :
                          inc.status === 'auto_resolved' ? 'bg-[#3E8635]/20 text-[#3E8635]' :
                          'bg-[#555]/30 text-[#8A8D90]'
                        }`}>
                          {inc.status}
                        </span>
                      </div>
                      {inc.rca_summary && (
                        <p className="text-[#8A8D90] text-xs mt-1">{typeof inc.rca_summary === 'string' ? inc.rca_summary.slice(0, 150) : ''}</p>
                      )}
                      <div className="flex items-center gap-3 mt-2 text-[10px] text-[#555]">
                        <span>{inc.proposed_by}</span>
                        <span>{relativeTime(inc.proposed_at)}</span>
                        {inc.signal_count > 0 && <span>{inc.signal_count} signals</span>}
                        {inc.confidence && <span>{Math.round(inc.confidence * 100)}% confidence</span>}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[#555] text-xs">No incidents</p>
              )}
            </section>

            {/* Shadow Tracking */}
            <section>
              <h3 className="text-[#ccc] text-xs font-semibold uppercase tracking-wider mb-3 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: data.shadow?.length ? '#8A8D90' : '#555' }} />
                Shadow Tracking ({data.shadow?.length || 0})
              </h3>
              {data.shadow?.length > 0 ? (
                <div className="space-y-1">
                  {data.shadow.map((sh: any, i: number) => (
                    <div key={i} className="flex items-center justify-between py-1.5 border-b border-[#222]">
                      <span className="text-xs text-[#ccc]">{sh.failure_class}</span>
                      <div className="flex items-center gap-2">
                        {sh.resolved ? (
                          <span className="text-[10px] text-[#3E8635]">resolved ({sh.resolution_cause})</span>
                        ) : (
                          <span className="text-[10px] text-[#F0AB00]">tracking</span>
                        )}
                        <span className="text-[10px] text-[#555]">{relativeTime(sh.tracked_at)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-[#555] text-xs">Not tracked in shadow mode</p>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

function NamespaceTable({ data, search, onSelect }: { data: any[]; search: string; onSelect: (ns: string) => void }) {
  const filtered = data.filter(r =>
    !search || r.namespace?.toLowerCase().includes(search.toLowerCase()) || r.cluster?.toLowerCase().includes(search.toLowerCase())
  );
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-[#333]">
          <th className="text-left px-3 py-2 text-[#8A8D90] font-medium">Namespace</th>
          <th className="text-left px-3 py-2 text-[#8A8D90] font-medium">Cluster</th>
          {STAGES.map(s => (
            <th key={s} className="text-center px-3 py-2 text-[#8A8D90] font-medium text-xs uppercase">{STAGE_LABELS[s]}</th>
          ))}
          <th className="text-left px-3 py-2 text-[#8A8D90] font-medium">Top Failure</th>
        </tr>
      </thead>
      <tbody>
        {filtered.slice(0, 200).map((r, i) => (
          <tr
            key={`${r.namespace}-${i}`}
            className="border-b border-[#222] hover:bg-[#1e1e1e] cursor-pointer"
            onClick={() => onSelect(r.namespace)}
          >
            <td className="px-3 py-2 text-[#4394E5] font-mono text-xs hover:underline">{r.namespace}</td>
            <td className="px-3 py-2 text-[#8A8D90] text-xs">{r.cluster}</td>
            {STAGES.map(s => {
              const st = r.stages?.[s] || { status: 'green', detail: '' };
              return <StatusDot key={s} status={st.status} detail={st.detail} />;
            })}
            <td className="px-3 py-2 text-xs text-[#C9190B]">{r.top_failure || ''}</td>
          </tr>
        ))}
        {filtered.length > 200 && (
          <tr><td colSpan={9} className="px-3 py-2 text-center text-[#6A6E73] text-xs">Showing 200 of {filtered.length}</td></tr>
        )}
        {filtered.length === 0 && (
          <tr><td colSpan={9} className="px-3 py-8 text-center text-[#6A6E73]">No namespaces found</td></tr>
        )}
      </tbody>
    </table>
  );
}

function LabTable({ data, search }: { data: any[]; search: string }) {
  const filtered = data.filter(r =>
    !search || r.lab_code?.toLowerCase().includes(search.toLowerCase())
  );
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-[#333]">
          <th className="text-left px-3 py-2 text-[#8A8D90] font-medium">Lab</th>
          <th className="text-center px-3 py-2 text-[#8A8D90] font-medium">NS</th>
          {STAGES.map(s => (
            <th key={s} className="text-center px-3 py-2 text-[#8A8D90] font-medium text-xs uppercase">{STAGE_LABELS[s]}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {filtered.map(r => (
          <tr key={r.lab_code} className="border-b border-[#222] hover:bg-[#1e1e1e]">
            <td className="px-3 py-2">
              <span className="text-[#4394E5] text-sm">{r.lab_code}</span>
              {r.clusters?.length > 0 && (
                <span className="ml-2 text-[10px] text-[#6A6E73]">{r.clusters.join(', ')}</span>
              )}
            </td>
            <td className="px-3 py-2 text-center text-[#ccc] text-xs">{r.namespaces}</td>
            {STAGES.map(s => {
              const st = r.stages?.[s] || { status: 'green', detail: '' };
              return <StatusDot key={s} status={st.status} detail={st.detail} />;
            })}
          </tr>
        ))}
        {filtered.length === 0 && (
          <tr><td colSpan={8} className="px-3 py-8 text-center text-[#6A6E73]">No labs found</td></tr>
        )}
      </tbody>
    </table>
  );
}

function ClusterTable({ data, search }: { data: any[]; search: string }) {
  const filtered = data.filter(r =>
    !search || r.cluster?.toLowerCase().includes(search.toLowerCase())
  );
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-[#333]">
          <th className="text-left px-3 py-2 text-[#8A8D90] font-medium">Cluster</th>
          <th className="text-center px-3 py-2 text-[#8A8D90] font-medium">Namespaces</th>
          {STAGES.map(s => (
            <th key={s} className="text-center px-3 py-2 text-[#8A8D90] font-medium text-xs uppercase">{STAGE_LABELS[s]}</th>
          ))}
          <th className="text-left px-3 py-2 text-[#8A8D90] font-medium">Top Failure</th>
        </tr>
      </thead>
      <tbody>
        {filtered.map(r => (
          <tr key={r.cluster} className="border-b border-[#222] hover:bg-[#1e1e1e]">
            <td className="px-3 py-2">
              <a href={`/cluster/${r.cluster}`} className="text-[#4394E5] hover:underline">{r.cluster}</a>
            </td>
            <td className="px-3 py-2 text-center text-[#ccc]">{r.namespaces}</td>
            {STAGES.map(s => {
              const st = r.stages?.[s] || { status: 'green', detail: '' };
              return <StatusDot key={s} status={st.status} detail={st.detail} />;
            })}
            <td className="px-3 py-2 text-xs text-[#C9190B]">{r.top_failure || ''}</td>
          </tr>
        ))}
        {filtered.length === 0 && (
          <tr><td colSpan={9} className="px-3 py-8 text-center text-[#6A6E73]">No clusters found</td></tr>
        )}
      </tbody>
    </table>
  );
}

export default function LifecycleMatrix() {
  const [tab, setTab] = useState<Tab>('namespace');
  const [search, setSearch] = useState('');
  const [selectedNs, setSelectedNs] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ['lifecycle-matrix'],
    queryFn: () => api.getLifecycleMatrix(),
    refetchInterval: 30000,
  });

  const tabs: { key: Tab; label: string; count?: number }[] = [
    { key: 'namespace', label: 'Issues', count: data?.summary?.total_namespaces },
    { key: 'lab', label: 'By Lab', count: data?.summary?.total_labs },
    { key: 'cluster', label: 'By Cluster', count: data?.summary?.total_clusters },
  ];

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white mb-1" style={{ fontFamily: 'Red Hat Display' }}>
          Lifecycle Matrix
        </h1>
        <p className="text-[#6A6E73] text-sm">
          {data?.summary?.total_monitored ? `${data.summary.total_monitored} namespaces monitored — ` : ''}showing namespaces with active issues
        </p>
      </div>

      {isLoading && <div className="text-[#6A6E73] py-12 text-center">Loading lifecycle data...</div>}
      {error && <div className="text-[#C9190B] py-12 text-center">Error: {(error as Error).message}</div>}

      {data && (
        <>
          <SummaryBar
            stages_health={data.summary?.stages_health || {}}
            stage_counts={data.summary?.stage_counts || {}}
          />

          <div className="flex items-center justify-between mb-4">
            <div className="flex gap-1">
              {tabs.map(t => (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={`px-3 py-1.5 rounded text-sm font-medium transition ${
                    tab === t.key ? 'bg-white/15 text-white' : 'text-[#6A6E73] hover:text-white hover:bg-white/10'
                  }`}
                >
                  {t.label}
                  {t.count !== undefined && (
                    <span className="ml-1.5 text-xs text-[#6A6E73]">({t.count})</span>
                  )}
                </button>
              ))}
            </div>
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Filter..."
              className="bg-[#1e1e1e] border border-[#333] rounded px-3 py-1.5 text-sm text-white placeholder-[#555] w-48 focus:outline-none focus:border-[#4394E5]"
            />
          </div>

          <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] overflow-x-auto">
            {tab === 'namespace' && <NamespaceTable data={data.by_namespace || []} search={search} onSelect={setSelectedNs} />}
            {tab === 'lab' && <LabTable data={data.by_lab || []} search={search} />}
            {tab === 'cluster' && <ClusterTable data={data.by_cluster || []} search={search} />}
          </div>

          <div className="mt-4 flex items-center gap-4 text-xs text-[#6A6E73]">
            <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full inline-block" style={{ backgroundColor: '#3E8635' }} /> Healthy</span>
            <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full inline-block" style={{ backgroundColor: '#F0AB00' }} /> Warning</span>
            <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full inline-block" style={{ backgroundColor: '#C9190B' }} /> Failing</span>
          </div>
        </>
      )}

      {selectedNs && <NamespaceDrawer namespace={selectedNs} onClose={() => setSelectedNs(null)} />}
    </div>
  );
}
