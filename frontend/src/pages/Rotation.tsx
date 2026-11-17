/**
 * Rotation — the Turkey Vulture epic as two truths side by side.
 *
 * Jira is the source of truth for the plan: tickets, owners, status. The audit
 * ingest is the filter: which credential values are actually live, where, and
 * how many have no ticket at all. The page deliberately does not reconcile
 * them — the gap between the two is the finding.
 */

import type { RotationProvider, RotationResponse, RotationTrendPoint } from '../api/types';
import { useRotation } from '../api/hooks';
import { MetricCard, SectionHeader, relativeTime } from '../components/ui';

function pctTone(pct: number): string {
  if (pct >= 75) return '#3E8635';
  if (pct >= 40) return '#F0AB00';
  return '#EE0000';
}

function ProgressBar({ pct }: { pct: number }) {
  return (
    <div className="flex items-center gap-2 min-w-[110px]">
      <div className="h-1.5 flex-1 rounded-full bg-[#2e2e2e] overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{ width: `${Math.min(100, Math.max(0, pct))}%`, backgroundColor: pctTone(pct) }}
        />
      </div>
      <span className="w-9 text-right text-xs tabular-nums text-[#c7c7c7]">{pct}%</span>
    </div>
  );
}

function TrendChart({ trend }: { trend: RotationTrendPoint[] }) {
  if (trend.length < 2) {
    return (
      <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-5 text-sm text-[#6A6E73]">
        {trend.length === 1 ? (
          <>
            One snapshot so far (<span className="text-white">{trend[0]?.date}</span>). The line
            appears once there is a second day to compare — snapshots are written daily by the
            sync loop.
          </>
        ) : (
          'No snapshots yet. The first successful Jira sync creates one.'
        )}
      </div>
    );
  }

  const width = 640;
  const height = 160;
  const pad = 8;
  const max = Math.max(...trend.map((t) => Math.max(t.tickets, t.verified_live)), 1);
  const step = (width - pad * 2) / (trend.length - 1);
  const points = (key: 'closed' | 'tickets') =>
    trend
      .map((t, i) => `${pad + i * step},${height - pad - (t[key] / max) * (height - pad * 2)}`)
      .join(' ');

  return (
    <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
      <div className="flex items-center gap-4 mb-2 text-xs text-[#6A6E73]">
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-0.5 inline-block" style={{ backgroundColor: '#3E8635' }} />
          closed
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-3 h-0.5 inline-block" style={{ backgroundColor: '#6A6E73' }} />
          total tickets
        </span>
        <span className="ml-auto">
          {trend[0]?.date} → {trend[trend.length - 1]?.date}
        </span>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full h-40"
        role="img"
        aria-label="Rotation trend: closed tickets against total tickets"
      >
        <polyline points={points('tickets')} fill="none" stroke="#6A6E73" strokeWidth="2" />
        <polyline points={points('closed')} fill="none" stroke="#3E8635" strokeWidth="2" />
      </svg>
    </div>
  );
}

function ProviderRow({ row }: { row: RotationProvider }) {
  return (
    <tr className="border-b border-[#1a1a1a] last:border-0">
      <td className="py-2 pr-4 text-sm text-white">{row.provider}</td>
      <td className="py-2 px-2 text-right text-sm tabular-nums text-[#c7c7c7]">{row.tickets}</td>
      <td className="py-2 px-2 text-right text-sm tabular-nums text-[#c7c7c7]">{row.closed}</td>
      <td className="py-2 px-2">
        <ProgressBar pct={row.closed_pct} />
      </td>
      <td className="py-2 px-2 text-right text-sm tabular-nums text-[#c7c7c7]">{row.in_progress}</td>
      <td className="py-2 px-2 text-right text-sm tabular-nums text-[#c7c7c7]">{row.unassigned}</td>
      <td className="py-2 px-2 text-right text-sm tabular-nums text-white">{row.verified_live}</td>
      <td className="py-2 px-2 text-right text-sm tabular-nums text-[#c7c7c7]">{row.live_locations}</td>
      <td className="py-2 pl-2 text-right text-sm tabular-nums" style={{ color: row.untracked_live ? '#F0AB00' : '#6A6E73' }}>
        {row.untracked_live}
      </td>
    </tr>
  );
}

function EmptyState({ data }: { data: RotationResponse }) {
  const unconfigured = data.source.jira === 'unconfigured';
  return (
    <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-6 text-sm text-[#6A6E73]">
      <p className="text-white font-medium mb-1">
        {unconfigured ? 'Jira is not configured in this deployment' : 'No rotation snapshot yet'}
      </p>
      <p>
        {unconfigured
          ? 'Set STARGATE_JIRA_URL, STARGATE_JIRA_EMAIL and STARGATE_JIRA_TOKEN, then restart the API. The sync runs every 30 minutes.'
          : 'The Jira sync has not written a snapshot yet. It runs every 30 minutes after startup; check STARGATE_ROTATION_SYNC_ENABLED.'}
      </p>
      <p className="mt-3">
        Nothing is shown as zero that has not been measured — an empty page is the honest state.
      </p>
    </div>
  );
}

export default function Rotation() {
  const { data, isLoading, isError } = useRotation();

  if (isLoading) {
    return (
      <div className="max-w-6xl mx-auto p-6 space-y-4 animate-pulse">
        <div className="h-8 bg-[#212121] rounded w-72" />
        <div className="h-24 bg-[#212121] rounded-xl" />
        <div className="h-64 bg-[#212121] rounded-lg" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="max-w-6xl mx-auto p-6">
        <p className="text-[#EE0000]">Failed to load the rotation snapshot.</p>
      </div>
    );
  }

  const { summary, providers, trend, source, last_sync, links } = data;
  const hasData = summary.providers > 0;

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-white">Turkey Vulture rotation</h1>
        <p className="text-sm text-[#6A6E73] mt-1">
          Jira owns the plan (GPTEINFRA-18544) · the audit owns what is live ·{' '}
          {last_sync ? `Jira synced ${relativeTime(last_sync)}` : 'no Jira sync yet'}
        </p>
        {links.length > 0 && (
          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-xs">
            <span className="text-[#6A6E73]">Source data:</span>
            {links.map((link) => (
              <a
                key={link.url}
                href={link.url}
                target="_blank"
                rel="noreferrer"
                className="text-[#73BCF7] hover:underline"
              >
                {link.label} ↗
              </a>
            ))}
          </div>
        )}
      </header>

      {!hasData ? (
        <EmptyState data={data} />
      ) : (
        <>
          {summary.untracked_live > 0 && (
            <div className="bg-[#212121] border-l-2 rounded-lg px-4 py-3 text-sm" style={{ borderColor: '#F0AB00' }}>
              <span className="text-white font-medium">
                {summary.untracked_live} live credential{summary.untracked_live === 1 ? '' : 's'} have no ticket.
              </span>{' '}
              <span className="text-[#6A6E73]">
                These exist in the clusters but outside the epic — Jira cannot show work it was
                never told about. They are the next candidates to file.
              </span>
            </div>
          )}

          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
            <MetricCard label="Tickets" value={summary.tickets} sub={`${summary.providers} providers`} />
            <MetricCard
              label="Closed"
              value={`${summary.closed_pct}%`}
              sub={`${summary.closed} of ${summary.tickets}`}
              accent={summary.closed_pct >= 75 ? 'green' : summary.closed_pct >= 40 ? 'amber' : 'red'}
            />
            <MetricCard label="In progress" value={summary.in_progress} />
            <MetricCard
              label="Unassigned"
              value={summary.unassigned}
              sub={summary.tickets ? `${Math.round((100 * summary.unassigned) / summary.tickets)}% of tickets` : undefined}
              accent={summary.unassigned > 0 ? 'amber' : undefined}
            />
            <MetricCard label="Verified live" value={summary.verified_live} sub="values hash-matched" />
            <MetricCard
              label="Untracked live"
              value={summary.untracked_live}
              sub="no Jira ticket"
              accent={summary.untracked_live > 0 ? 'amber' : undefined}
            />
          </div>

          <section>
            <SectionHeader right={`${summary.live_locations} live locations`}>
              Progress by provider
            </SectionHeader>
            <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg px-4 py-2 overflow-x-auto">
              <table className="w-full min-w-[760px]">
                <thead>
                  <tr className="text-[10px] uppercase tracking-wider text-[#6A6E73] border-b border-[#2e2e2e]">
                    <th className="text-left font-medium py-2 pr-4">Provider</th>
                    <th className="text-right font-medium py-2 px-2">Tickets</th>
                    <th className="text-right font-medium py-2 px-2">Closed</th>
                    <th className="text-left font-medium py-2 px-2">% closed</th>
                    <th className="text-right font-medium py-2 px-2">In prog.</th>
                    <th className="text-right font-medium py-2 px-2">Unassigned</th>
                    <th className="text-right font-medium py-2 px-2">Verified live</th>
                    <th className="text-right font-medium py-2 px-2">Locations</th>
                    <th className="text-right font-medium py-2 pl-2">Untracked</th>
                  </tr>
                </thead>
                <tbody>
                  {providers.map((row) => (
                    <ProviderRow key={row.provider} row={row} />
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-xs text-[#6A6E73] mt-2">
              Ticket columns come from Jira. <span className="text-[#c7c7c7]">Verified live</span>,
              locations and untracked come from the admin-run audit ingest — StarGate's
              cluster-reader SA cannot read Secrets, so it never probes customer credentials.
            </p>
          </section>

          <section>
            <SectionHeader right={`${trend.length} snapshot${trend.length === 1 ? '' : 's'}`}>
              Trend
            </SectionHeader>
            <TrendChart trend={trend} />
          </section>

          <p className="text-xs text-[#6A6E73]">
            Jira source: <span className="text-[#c7c7c7]">{source.jira}</span> · verification
            source: <span className="text-[#c7c7c7]">{source.verification}</span> · generated{' '}
            {relativeTime(data.generated_at)}
          </p>
        </>
      )}
    </div>
  );
}
