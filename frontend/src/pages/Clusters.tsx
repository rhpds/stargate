/**
 * Clusters — the drill target. (The missing route the new pages link to.)
 *
 * ONE question: "Which cluster, and how is it?" — the fleet's clusters,
 * exceptions first, each drilling to its detail.
 */

import { Link } from 'react-router-dom';
import { StatusBadge, relativeTime } from '../components/ui';
import { useOverview } from '../api/hooks';

interface ClusterRow {
  name: string;
  rag: 'green' | 'amber' | 'red' | string;
  detail: string;
  avg_cpu?: number;
  vms?: number;
  sandboxes?: number;
}

function classify(c: {
  cluster?: string;
  name?: string;
  health_rate?: number;
  avg_cpu_pct?: number;
}): ClusterRow {
  const name = c.cluster || c.name || '?';
  const rate = c.health_rate ?? 100;
  const rag = rate >= 90 && (c.avg_cpu_pct ?? 0) < 80 ? 'green' : rate >= 70 ? 'amber' : 'red';
  return {
    name,
    rag,
    detail: `${Math.round(rate)}% healthy`,
    avg_cpu: c.avg_cpu_pct,
    vms: (c as { total_vms?: number }).total_vms,
    sandboxes: (c as { sandbox_active?: number }).sandbox_active,
  };
}

export default function Clusters() {
  const overview = useOverview();
  const clusters = (overview.data?.clusters?.scans ?? [])
    .map(classify)
    .sort((a, b) => ({ red: 0, amber: 1, green: 2 }[a.rag] ?? 3) - ({ red: 0, amber: 1, green: 2 }[b.rag] ?? 3));

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-white">Clusters</h1>
        <p className="text-sm text-[#6A6E73] mt-1">
          {clusters.length} clusters, exceptions first · last scan{' '}
          {overview.data ? relativeTime(overview.data.timestamp) : '—'}
        </p>
      </header>

      {overview.error && (
        <div className="bg-[#2e2e2e] border border-[#EE0000]/40 rounded-lg p-4 text-sm text-white">
          Failed to load: {String(overview.error)}
        </div>
      )}
      {overview.isLoading && !overview.data && (
        <div className="text-sm text-[#6A6E73]">Loading clusters…</div>
      )}
      {clusters.length === 0 && !overview.isLoading && (
        <div className="text-sm text-[#6A6E73]">No cluster data in the window.</div>
      )}

      <div className="space-y-2">
        {clusters.map((c) => (
          <Link
            key={c.name}
            to={`/cluster/${c.name}`}
            className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 flex items-center justify-between gap-4 hover:border-[#555] transition"
          >
            <div className="min-w-0">
              <div className="flex items-center gap-3">
                <StatusBadge status={c.rag} label={c.rag === 'green' ? 'healthy' : c.rag === 'amber' ? 'degraded' : 'critical'} />
                <span className="text-base font-semibold text-white">{c.name}</span>
              </div>
              <div className="text-xs text-[#6A6E73] mt-1 flex gap-4">
                <span>{c.detail}</span>
                {c.avg_cpu != null && <span>cpu {Math.round(c.avg_cpu)}%</span>}
                {c.vms != null && <span>{c.vms} VMs</span>}
                {c.sandboxes != null && <span>{c.sandboxes} sandboxes</span>}
              </div>
            </div>
            <span className="text-[#6A6E73] text-sm" aria-hidden="true">→</span>
          </Link>
        ))}
      </div>
    </div>
  );
}
