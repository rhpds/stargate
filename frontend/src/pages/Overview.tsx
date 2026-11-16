/**
 * Overview — the 30-second page. (Frontend redesign Phase 3, first page.)
 *
 * ONE question: "Is anything on fire right now?" — answered in headlines,
 * every number drills to its evidence, RAG is consistent and labeled.
 * Per docs/frontend-redesign-plan.md §2/§3/§5.
 */

import { Link } from 'react-router-dom';
import { MetricCard, SectionHeader, StatusBadge, VerdictBanner, FleetStrip, relativeTime } from '../components/ui';
import { useHealth, useOverview, useEvents } from '../api/hooks';
import { useQuery } from '@tanstack/react-query';
import { request } from '../api/client';

interface ClusterRag {
  name: string;
  rag: 'green' | 'amber' | 'red' | string;
  detail?: string;
}

function clusterRag(cluster: {
  name?: string;
  cluster?: string;
  health_rate?: number;
  avg_cpu_pct?: number;
  status?: string;
}): ClusterRag {
  const name = cluster.name || cluster.cluster || '?';
  const rate = cluster.health_rate ?? 100;
  if (rate >= 90 && (cluster.avg_cpu_pct ?? 0) < 80) {
    return { name, rag: 'green', detail: `${Math.round(rate)}% healthy` };
  }
  if (rate >= 70) {
    return { name, rag: 'amber', detail: `${Math.round(rate)}% healthy` };
  }
  return {
    name,
    rag: 'red',
    detail: cluster.status ? String(cluster.status) : `${Math.round(rate)}% healthy`,
  };
}

export default function Overview() {
  const health = useHealth();
  const overview = useOverview();
  const events = useEvents();

  const isLoading = health.isLoading || overview.isLoading;
  const error = health.error || overview.error;

  const clusters: ClusterRag[] = (overview.data?.clusters?.scans ?? []).map(clusterRag);
  const failingLabs = overview.data?.errors?.total_failures ?? 0;
  const fleetRag =
    clusters.some((c) => c.rag === 'red') ? 'red'
      : clusters.some((c) => c.rag === 'amber') ? 'amber'
        : clusters.length > 0 ? 'green' : 'unknown';
  const kpis = useQuery({
    queryKey: ['platform-kpis'],
    queryFn: () => request<{ slos?: { name: string; current: number; target: number; status: string }[] }>(
      '/admin/platform-kpis'),
    refetchInterval: 300_000,
  });
  const breachedSlos = (kpis.data?.slos ?? []).filter(
    (s) => s.status === 'breached' || s.status === 'at_risk');

  const recentCritical = (events.data ?? [])
    .filter((e) => (e.outcome ?? '').toLowerCase() === 'fail')
    .slice(0, 5);

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-white">Is anything on fire right now?</h1>
        <p className="text-sm text-[#6A6E73] mt-1">
          Fleet state, last scan {health.data ? relativeTime(health.data.timestamp) : '—'} ·
          {' '}
          <Link to="/clusters" className="text-[#73BCF7]">drill into clusters</Link>
        </p>
      </header>

      {error && (
        <div className="bg-[#2e2e2e] border border-[#EE0000]/40 rounded-lg p-4 text-sm text-white">
          Failed to load fleet state: {String(error)}.{' '}
          <Link to="/" className="text-[#73BCF7]">Retry</Link> · check{' '}
          <a href="/health" className="text-[#73BCF7]">platform health</a>.
        </div>
      )}
      {isLoading && !overview.data && (
        <div className="text-sm text-[#6A6E73]">Loading fleet state…</div>
      )}

      <section aria-label="Fleet status">
        <SectionHeader right={`${clusters.length} clusters`}>Fleet status</SectionHeader>
        <div className="mb-4">
          <FleetStrip segments={clusters.map((c) => ({ name: c.name, rag: c.rag }))} />
        </div>
        <VerdictBanner
          state={fleetRag === 'unknown' ? 'unknown' : fleetRag}
          headline={
            fleetRag === 'green'
              ? `No — all ${clusters.length} clusters healthy`
              : fleetRag === 'red'
                ? `Yes — ${clusters.filter((c) => c.rag === 'red').length} critical, ${clusters.filter((c) => c.rag === 'amber').length} degraded`
                : fleetRag === 'amber'
                  ? `Attention — ${clusters.filter((c) => c.rag === 'amber').length} cluster(s) degraded`
                  : 'No cluster data in the window'
          }
          chips={[
            `${clusters.filter((c) => c.rag === 'red').length} critical`,
            `${clusters.filter((c) => c.rag === 'amber').length} degraded`,
            `${clusters.filter((c) => c.rag === 'green').length} healthy`,
          ]}
          meta={health.data ? `as of ${relativeTime(health.data.timestamp)}` : undefined}
          drillTo="/clusters"
          drillLabel="view clusters →"
        />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
          <MetricCard label="Failing labs" value={failingLabs} sub="last hour"
            accent={failingLabs > 0 ? 'amber' : 'green'} />
          <MetricCard
            label="Scanners"
            value={health.data?.components?.scanners === 'ok' ? 'ok' : 'stale'}
            sub={health.data ? `age ${health.data.components?.scanner_age_minutes ?? '?'}m` : undefined}
          />
          <MetricCard
            label="Database"
            value={health.data?.components?.database === 'ok' ? 'ok' : 'degraded'}
          />
        </div>
      </section>

      {kpis.data?.slos && (
        <section aria-label="Service level objectives">
          {breachedSlos.length === 0 ? (
            <div className="text-sm text-[#3E8635] flex items-center gap-2">
              <span aria-hidden="true">✓</span> all {kpis.data.slos.length} SLOs met
            </div>
          ) : (
            <div className="flex gap-2 flex-wrap">
              {breachedSlos.map((s) => (
                <span key={s.name}
                  className={`text-xs font-semibold px-2 py-1 rounded ${s.status === 'breached' ? 'bg-[#EE0000]/15 text-[#EE0000] border border-[#EE0000]/30' : 'bg-[#F0AB00]/15 text-[#F0AB00] border border-[#F0AB00]/30'}`}>
                  {s.status === 'breached' ? '✖' : '⚠'} {s.name}: {s.current} vs target {s.target}
                </span>
              ))}
            </div>
          )}
        </section>
      )}

      <section aria-label="Clusters">
        <SectionHeader right={<Link to="/clusters" className="text-[#73BCF7]">all clusters →</Link>}>
          Clusters
        </SectionHeader>
        {clusters.length === 0 && !isLoading && (
          <div className="text-sm text-[#6A6E73]">No cluster data in the window.</div>
        )}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[...clusters].sort((a, b) => ({ red: 0, amber: 1, green: 2 }[a.rag] ?? 3) - ({ red: 0, amber: 1, green: 2 }[b.rag] ?? 3)).map((c) => (
            <Link
              key={c.name}
              to={`/cluster/${c.name}`}
              className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-3 hover:border-[#555] transition"
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-white">{c.name}</span>
                <StatusBadge status={c.rag} />
              </div>
              {c.detail && <div className="text-xs text-[#6A6E73] mt-1">{c.detail}</div>}
            </Link>
          ))}
        </div>
      </section>

      <section aria-label="Recent critical events">
        <SectionHeader right={<Link to="/failures" className="text-[#73BCF7]">all events →</Link>}>
          Recent critical events
        </SectionHeader>
        {recentCritical.length === 0 && (
          <div className="text-sm text-[#6A6E73]">None in the recent window.</div>
        )}
        <ul className="space-y-1">
          {recentCritical.map((e, i: number) => (
            <li key={e.event_id ?? i} className="text-sm text-white flex justify-between gap-4">
              <span className="truncate">
                <span className="text-[#6A6E73] mr-2">{e.event_type}</span>
                {e.lab_code ?? e.cluster_name ?? ''}
              </span>
              <span className="text-xs text-[#6A6E73] whitespace-nowrap">
                {relativeTime(e.timestamp)}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
