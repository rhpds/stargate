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

function NamespaceTable({ data, search }: { data: any[]; search: string }) {
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
          <tr key={`${r.namespace}-${i}`} className="border-b border-[#222] hover:bg-[#1e1e1e]">
            <td className="px-3 py-2 text-[#ccc] font-mono text-xs">{r.namespace}</td>
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

  const { data, isLoading, error } = useQuery({
    queryKey: ['lifecycle-matrix'],
    queryFn: () => api.getLifecycleMatrix(),
    refetchInterval: 30000,
  });

  const tabs: { key: Tab; label: string; count?: number }[] = [
    { key: 'namespace', label: 'By Namespace', count: data?.summary?.total_namespaces },
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
          Namespace health by category — health, pods, storage, network, workload — sorted by most failures
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
            {tab === 'namespace' && <NamespaceTable data={data.by_namespace || []} search={search} />}
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
    </div>
  );
}
