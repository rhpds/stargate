/**
 * Provisioning — the pipeline page. (Frontend redesign Phase 3.)
 *
 * ONE question: "Are provisions succeeding, and what's failing?" —
 * the verdict comes from the failure rate, the pipeline strip shows
 * every subject at a glance, labs are listed exceptions-first with
 * their failing instances, and the 24h trend shows whether the
 * failure rate is moving. Per the redesign's rule: never color alone.
 */

import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  MetricCard,
  SectionHeader,
  StatusBadge,
  VerdictBanner,
  StateStrip,
  STATUS_COLORS,
  relativeTime,
} from '../components/ui';
import { request } from '../api/client';
import type { ProvisioningOverview, ProvisioningInstance } from '../api/types';

interface TrendPoint {
  captured_at?: string;
  total?: number;
  started?: number;
  failed?: number;
  failure_rate?: number | null;
}

/**
 * State classification. Failed semantics mirror the backend
 * (/dashboard/provisioning): a subject counts as failed when its
 * state contains "failed" or "error".
 */
function isFailedState(state: string): boolean {
  const s = state.toLowerCase();
  return s.includes('fail') || s.includes('error');
}

function isPendingState(state: string): boolean {
  const s = state.toLowerCase();
  return (
    s.includes('pending') || s.includes('wait') || s.includes('provision') ||
    s.includes('init') || s.includes('queue') || s.includes('creat')
  );
}

function isGoodState(state: string): boolean {
  const s = state.toLowerCase();
  return s === 'started' || s === 'ready' || s === 'running' ||
    s === 'active' || s === 'available';
}

/** Single source of truth for state color (strip, dots, badges). */
function stateColor(state: string): string {
  if (isFailedState(state)) return '#EE0000';
  if (isGoodState(state)) return '#3E8635';
  if (isPendingState(state)) return '#F0AB00';
  return STATUS_COLORS[state.toLowerCase()] ?? '#6A6E73';
}

type StripState = 'green' | 'amber' | 'red' | 'unknown';

function stripStateFor(state: string): StripState {
  const c = stateColor(state);
  if (c === '#EE0000') return 'red';
  if (c === '#F0AB00') return 'amber';
  if (c === '#3E8635') return 'green';
  return 'unknown';
}

/** Severity for exceptions-first ordering: failed, then pending, then good. */
function stateSeverity(state: string): number {
  if (isFailedState(state)) return 0;
  if (isPendingState(state)) return 1;
  if (isGoodState(state)) return 2;
  return 3;
}

function fmtRate(rate: number): string {
  return `${Number.isInteger(rate) ? rate : rate.toFixed(1)}%`;
}

function fmtTime(iso?: string): string {
  if (!iso) return '--';
  const dt = new Date(iso);
  return Number.isNaN(dt.getTime())
    ? '--'
    : dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

/** Failure-rate sparkline with the 5% / 15% verdict thresholds marked. */
function FailureRateSparkline({ points }: { points: TrendPoint[] }) {
  const W = 600;
  const H = 48;
  const rates = points.map((p) => Number(p.failure_rate ?? 0) || 0);
  const maxRate = Math.max(20, ...rates);
  const x = (i: number) => (rates.length <= 1 ? W / 2 : (i / (rates.length - 1)) * W);
  const y = (r: number) => H - 3 - (Math.min(r, maxRate) / maxRate) * (H - 6);
  const path = rates
    .map((r, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)} ${y(r).toFixed(1)}`)
    .join(' ');
  const last = rates[rates.length - 1] ?? 0;
  const peak = rates.length > 0 ? Math.max(...rates) : 0;
  const stroke = last < 5 ? '#3E8635' : last <= 15 ? '#F0AB00' : '#EE0000';
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs text-[#6A6E73] mb-1">
        <span>
          failure rate · <span className="text-white font-semibold">{fmtRate(last)}</span> now · peak {fmtRate(peak)}
        </span>
        <span>{points.length} snapshots</span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-12"
        preserveAspectRatio="none"
        role="img"
        aria-label={`Failure rate over the last 24 hours: now ${fmtRate(last)}, peak ${fmtRate(peak)}, thresholds 5% amber and 15% red`}
      >
        <line x1="0" x2={W} y1={y(5)} y2={y(5)} stroke="#F0AB00" strokeWidth="1"
          strokeDasharray="4 4" strokeOpacity="0.6" vectorEffect="non-scaling-stroke" />
        <line x1="0" x2={W} y1={y(15)} y2={y(15)} stroke="#EE0000" strokeWidth="1"
          strokeDasharray="4 4" strokeOpacity="0.6" vectorEffect="non-scaling-stroke" />
        <path d={path} fill="none" stroke={stroke} strokeWidth="1.5"
          strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        {rates.length > 0 && (
          <circle cx={x(rates.length - 1)} cy={y(last)} r="3" fill={stroke} />
        )}
      </svg>
      <div className="flex justify-between text-[10px] text-[#6A6E73]">
        <span>{fmtTime(points[0]?.captured_at)}</span>
        <span>dashed lines: 5% amber · 15% red thresholds</span>
        <span>{fmtTime(points[points.length - 1]?.captured_at)}</span>
      </div>
    </div>
  );
}

const MAX_STRIP_CELLS = 500;

export default function Provisioning() {
  const overview = useQuery({
    queryKey: ['provisioning-overview'],
    queryFn: () => request<ProvisioningOverview>('/dashboard/provisioning'),
    refetchInterval: 30_000,
  });
  const trends = useQuery({
    queryKey: ['provisioning-trends', 24],
    queryFn: () => request<{ timeline: TrendPoint[] }>('/dashboard/provisioning-trends?hours=24'),
    refetchInterval: 60_000,
  });

  const d = overview.data;
  const total = d?.total ?? 0;
  const started = d?.started ?? 0;
  const failed = d?.failed ?? 0;
  const rate = Number(d?.failure_rate) || 0;

  // green < 5%, amber 5–15%, red > 15%
  const verdict: 'green' | 'amber' | 'red' | 'unknown' =
    total === 0 ? 'unknown' : rate < 5 ? 'green' : rate <= 15 ? 'amber' : 'red';
  const headline =
    verdict === 'unknown'
      ? 'No provisioning data in the window'
      : verdict === 'green'
        ? failed === 0
          ? `100% success — no provisions failing`
          : `${Math.round(100 - rate)}% success — ${failed} of ${total} provisions failed`
        : `Failure rate ${Math.round(rate)}% — ${failed} provision${failed === 1 ? '' : 's'} failing`;

  // states, exceptions-first, then by count
  const stateEntries = Object.entries(d?.by_state ?? {}).sort(
    (a, b) => stateSeverity(a[0]) - stateSeverity(b[0]) || b[1] - a[1],
  );

  // pipeline strip: one cell per subject (scaled down past the cap),
  // so block width is proportional to real counts
  const scale = total > MAX_STRIP_CELLS ? MAX_STRIP_CELLS / total : 1;
  const stripCells = stateEntries.flatMap(([state, count]) => {
    const cells = Math.max(1, Math.round(count * scale));
    const title = `${state} — ${count} subject${count === 1 ? '' : 's'}`;
    return Array.from({ length: cells }, () => ({
      state: stripStateFor(state),
      title,
    }));
  });

  // failing instances per lab, from the problem states
  const problemInstancesByLab: Record<string, ProvisioningInstance[]> = {};
  for (const [state, insts] of Object.entries(d?.subjects_by_state ?? {})) {
    if (!isFailedState(state)) continue;
    for (const inst of insts ?? []) {
      if (!inst?.lab_code) continue;
      (problemInstancesByLab[inst.lab_code] ??= []).push(inst);
    }
  }

  const allLabs = Object.entries(d?.labs_affected ?? {});
  const failingLabs = allLabs
    .filter(([, s]) => s.failed > 0)
    .sort((a, b) => b[1].failed - a[1].failed);

  const stateBadgeColors = Object.fromEntries(
    stateEntries.map(([state]) => [state.toLowerCase(), stateColor(state)]),
  );

  const timeline = trends.data?.timeline ?? [];

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-white">Are provisions succeeding, and what&apos;s failing?</h1>
        <p className="text-sm text-[#6A6E73] mt-1">
          AnarchySubject pipeline, {total} subjects · last snapshot {d ? relativeTime(d.timestamp) : '—'} ·{' '}
          <Link to="/trends" className="text-[#73BCF7]">full trends</Link>
        </p>
      </header>

      {overview.error && (
        <div className="bg-[#2e2e2e] border border-[#EE0000]/40 rounded-lg p-4 text-sm text-white">
          Failed to load provisioning data: {String(overview.error)}.
        </div>
      )}
      {overview.isLoading && !d && (
        <div className="text-sm text-[#6A6E73]">Loading provisioning pipeline…</div>
      )}

      {d && (
        <section aria-label="Provisioning verdict">
          <VerdictBanner
            state={verdict}
            headline={headline}
            chips={[
              `${total} total`,
              `${started} started`,
              `${failed} failed`,
              `failure rate ${fmtRate(rate)}`,
            ]}
            meta={`as of ${relativeTime(d.timestamp)}`}
          />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
            <MetricCard
              label="Total provisions"
              value={total}
              sub="AnarchySubjects in the pipeline"
            />
            <MetricCard label="Started" value={started} accent={failed === 0 ? 'green' : undefined} />
            <MetricCard
              label="Failed"
              value={failed}
              accent={failed === 0 ? 'green' : rate > 15 ? 'red' : 'amber'}
            />
            <MetricCard
              label="Failure rate"
              value={fmtRate(rate)}
              accent={verdict === 'unknown' ? undefined : verdict}
              sub="green < 5% · amber 5–15% · red > 15%"
            />
          </div>
        </section>
      )}

      <section aria-label="Pipeline state">
        <SectionHeader right={`${total} subjects`}>Pipeline state</SectionHeader>
        {total > 0 ? (
          <>
            <StateStrip height="h-6" cells={stripCells} />
            <div className="mt-2 flex gap-3 flex-wrap text-xs text-[#8a8a8a]">
              {stateEntries.map(([state, count]) => {
                const unmapped = stateSeverity(state) === 3;
                return (
                  <span key={state} className="flex items-center gap-1.5">
                    <span
                      className={`w-2 h-2 rounded-sm inline-block ${unmapped ? 'border border-dashed border-[#6A6E73]' : ''}`}
                      style={unmapped ? undefined : { backgroundColor: stateColor(state) }}
                    />
                    {state} {count}
                  </span>
                );
              })}
            </div>
          </>
        ) : (
          d && <div className="text-sm text-[#6A6E73]">No subjects in the pipeline.</div>
        )}
      </section>

      <section aria-label="Affected labs">
        <SectionHeader right={`${failingLabs.length} of ${allLabs.length} labs failing`}>
          Affected labs
        </SectionHeader>
        {d && failingLabs.length === 0 && (
          <div className="text-sm text-[#3E8635] flex items-center gap-2">
            <span aria-hidden="true">✓</span> no labs failing — all {allLabs.length} labs at 0 failed provisions
          </div>
        )}
        <div className="space-y-2">
          {failingLabs.slice(0, 20).map(([lab, s]) => {
            const affected = problemInstancesByLab[lab] ?? [];
            return (
              <Link
                key={lab}
                to={`/lab/${encodeURIComponent(lab)}`}
                aria-label={`Lab ${lab}: ${s.failed} of ${s.total} provisions failed`}
                className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-3 hover:border-[#555] transition block"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-semibold text-white truncate">{lab}</span>
                  <span className="text-xs font-semibold text-[#EE0000] whitespace-nowrap">
                    {s.failed} failed · {s.started}/{s.total} started
                  </span>
                </div>
                {affected.length > 0 && (
                  <div className="mt-1.5 text-xs text-[#8a8a8a] flex flex-wrap gap-x-3 gap-y-0.5">
                    {affected.slice(0, 4).map((inst, i) => (
                      <span
                        key={`${inst.anarchy_name}-${i}`}
                        className="truncate max-w-[220px]"
                        title={`${inst.anarchy_name} (${inst.state})`}
                      >
                        {inst.anarchy_name}
                      </span>
                    ))}
                    {affected.length > 4 && (
                      <span className="text-[#6A6E73]">+ {affected.length - 4} more</span>
                    )}
                  </div>
                )}
              </Link>
            );
          })}
        </div>
        {failingLabs.length > 20 && (
          <div className="text-xs text-[#6A6E73] mt-2">
            + {failingLabs.length - 20} more affected labs
          </div>
        )}
      </section>

      <section aria-label="Failure rate over time">
        <SectionHeader right="24h window">Failure rate over time</SectionHeader>
        {trends.isLoading && (
          <div className="text-sm text-[#6A6E73]">Loading history…</div>
        )}
        {trends.error && (
          <div className="text-sm text-[#6A6E73]">
            History unavailable ({String(trends.error)}).
          </div>
        )}
        {!trends.isLoading && !trends.error && timeline.length >= 2 && (
          <FailureRateSparkline points={timeline} />
        )}
        {!trends.isLoading && !trends.error && timeline.length < 2 && (
          <div className="text-sm text-[#6A6E73]">
            Not enough history yet — the trend appears once snapshots accumulate.
          </div>
        )}
      </section>

      <section aria-label="State breakdown">
        <SectionHeader right={`${stateEntries.length} states`}>State breakdown</SectionHeader>
        {d && stateEntries.length === 0 && (
          <div className="text-sm text-[#6A6E73]">No states observed.</div>
        )}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {stateEntries.map(([state, count]) => (
            <div key={state} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-3">
              <div className="flex items-center justify-between gap-2">
                <StatusBadge status={state} colors={stateBadgeColors} />
                <span className="text-sm font-bold text-white tabular-nums">{count}</span>
              </div>
              <div className="text-xs text-[#6A6E73] mt-1">
                {total > 0 ? `${Math.round((count / total) * 100)}% of ${total}` : '--'}
              </div>
            </div>
          ))}
        </div>
      </section>

      <p className="text-xs text-[#6A6E73]">
        A subject counts as failed when its state contains &quot;failed&quot; or &quot;error&quot;;
        states classify as started (green), pending/provisioning (amber), failed (red).{' '}
        <Link to="/trends" className="text-[#73BCF7]">Full trends →</Link>
      </p>
    </div>
  );
}
