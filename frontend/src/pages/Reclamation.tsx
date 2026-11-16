/**
 * Reclamation — the teardown page. (Frontend redesign Phase 3, fourth pillar.)
 *
 * ONE question: "Are teardowns completing, and are we leaking resources?" —
 * red when storage outlives its namespace (orphaned PVs), amber when
 * teardowns are stuck, green only when both are observed clear: a zero is
 * only healthy when every query succeeded (the collectors' own rule).
 * Resolution outcomes show how reclamation landed (reclaimed /
 * self_resolved / namespace_recycled) with TTR. Every row drills to its
 * namespace's evidence.
 */

import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { MetricCard, SectionHeader, StatusBadge, VerdictBanner, relativeTime } from '../components/ui';
import { request } from '../api/client';
import type { StuckInstances } from '../api/types';

// --- Local endpoint contracts (getResolutions / monitoring gaps are
// untyped in the shared client; these follow the backend routers exactly) ---

interface StuckTeardownEntry {
  anarchy_subject: string;
  namespace: string;
  state: string;
  age_hours: number;
  cluster: string;
  namespace_exists?: boolean | null;
}

interface StuckTeardownsResult {
  total_subjects?: number;
  stuck?: StuckTeardownEntry[];
  stuck_count?: number;
  threshold_hours?: number;
  error?: string;
  partial?: boolean;
}

interface OrphanedPv {
  pv_name: string;
  bound_to_namespace: string;
  bound_to_pvc: string;
  status: string;
  capacity: string;
  storage_class: string;
}

interface ResourceLeaksResult {
  total_pvs?: number;
  orphaned_pvs?: OrphanedPv[];
  orphaned_count?: number;
  orphaned_capacity_gi?: number;
  orphaned_pvc_count?: number;
  error?: string;
}

interface MonitoringGaps {
  stuck_teardowns?: StuckTeardownsResult;
  resource_leaks?: ResourceLeaksResult;
}

interface ResolutionRow {
  id: number;
  lab_code: string;
  cluster: string | null;
  failure_class: string | null;
  resolution_type: string;
  resolved_by: string | null;
  resolution_action: string | null;
  detected_at: string | null;
  resolved_at: string | null;
  ttr_minutes: number | null;
}

interface ResolutionsData {
  total: number;
  by_type: Record<string, number>;
  avg_ttr_minutes: number | null;
  records: ResolutionRow[];
}

// --- Merged stuck-teardown row: live detector (age, cluster) enriched with
// the Babylon snapshot's destroy-state instances ---

interface TeardownRow {
  namespace: string;
  state: string;
  ageHours: number | null;
  cluster: string | null;
  subject: string | null;
  namespaceExists: boolean | null;
}

// "stopped" is a suspend, not a teardown — only destroy-prefixed states count.
const isTeardownState = (state: string) => (state || '').toLowerCase().includes('destroy');

const TEARDOWN_COLORS: Record<string, string> = {
  destroying: '#F0AB00', // stalled mid-destroy, past threshold
  'destroy-failed': '#EE0000',
  'destroy-error': '#EE0000',
};

const OUTCOME_CHIP: Record<string, string> = {
  reclaimed: 'bg-[#3E8635]/15 text-[#3E8635] border border-[#3E8635]/30',
  namespace_recycled: 'bg-[#73BCF7]/15 text-[#73BCF7] border border-[#73BCF7]/30',
  self_resolved: 'bg-white/5 text-[#c7c7c7] border border-[#3a3a3a]',
};

function formatAge(hours: number | null): string {
  if (hours == null) return 'unknown';
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours < 48) return `${hours.toFixed(1)}h`;
  return `${(hours / 24).toFixed(1)}d`;
}

export default function Reclamation() {
  const stuck = useQuery({
    queryKey: ['reclamation', 'stuck-instances'],
    queryFn: () => request<StuckInstances>('/dashboard/stuck-instances'),
    refetchInterval: 30_000,
  });
  // Live detectors (oc subprocesses) — slow by design, refresh gently.
  const gaps = useQuery({
    queryKey: ['reclamation', 'monitoring-gaps'],
    queryFn: () => request<MonitoringGaps>('/admin/monitoring-gaps'),
    refetchInterval: 600_000,
  });
  const resolutions = useQuery({
    queryKey: ['reclamation', 'resolutions'],
    queryFn: () => request<ResolutionsData>('/dashboard/resolutions?hours=168'),
    refetchInterval: 120_000,
  });

  const teardownRows = useMemo<TeardownRow[]>(() => {
    const byNs = new Map<string, TeardownRow>();
    // Live detector first — the richest row (age, cluster, existence).
    for (const e of gaps.data?.stuck_teardowns?.stuck ?? []) {
      const ns = e.namespace || e.anarchy_subject;
      if (!ns) continue;
      byNs.set(ns, {
        namespace: ns,
        state: e.state || 'unknown',
        ageHours: e.age_hours ?? null,
        cluster: e.cluster && e.cluster !== 'unknown' ? e.cluster : null,
        subject: e.anarchy_subject || null,
        namespaceExists: e.namespace_exists ?? null,
      });
    }
    // Babylon snapshot — adds destroy-failed rows the live scan can't see
    // (or when it errored); existing rows only gain the subject name.
    for (const [lab, instances] of Object.entries(stuck.data?.by_lab ?? {})) {
      for (const inst of instances ?? []) {
        if (!isTeardownState(inst.state)) continue;
        const ns = inst.namespace || lab;
        if (!ns) continue;
        const existing = byNs.get(ns);
        if (existing) {
          existing.subject = existing.subject || inst.name || null;
        } else {
          byNs.set(ns, {
            namespace: ns,
            state: inst.state,
            ageHours: null,
            cluster: null,
            subject: inst.name || null,
            namespaceExists: null,
          });
        }
      }
    }
    return [...byNs.values()].sort((a, b) => (b.ageHours ?? -1) - (a.ageHours ?? -1));
  }, [gaps.data, stuck.data]);

  const leaks = gaps.data?.resource_leaks;
  const orphanedPvs = leaks?.orphaned_pvs ?? [];
  // A failed scan means unobserved, not zero — never green across a gap.
  const leakScanFailed = !!gaps.error || !!leaks?.error;
  const leakCount = leakScanFailed || !leaks
    ? null
    : (leaks.orphaned_count ?? orphanedPvs.length);
  const leakedCapacityGi = leaks?.orphaned_capacity_gi ?? 0;

  const destroyFailed = stuck.data?.platform_stuck?.destroy_failed ?? 0;
  const stuckTeardownCount = Math.max(teardownRows.length, destroyFailed);
  const stuckObserved = !stuck.isLoading && !stuck.error;
  const thresholdHours = gaps.data?.stuck_teardowns?.threshold_hours ?? 2;

  const verdict: 'green' | 'amber' | 'red' | 'unknown' =
    leakCount != null && leakCount > 0 ? 'red'
      : stuckTeardownCount > 0 ? 'amber'
        : stuckObserved && leakCount === 0 ? 'green'
          : 'unknown';

  const scanning = stuck.isLoading || gaps.isLoading;
  const plural = (n: number, noun: string) => `${n} ${noun}${n === 1 ? '' : 's'}`;
  const headline = scanning
    ? 'Checking teardowns and leaks…'
    : verdict === 'red'
      ? stuckTeardownCount > 0
        ? `${plural(stuckTeardownCount, 'stuck teardown')}, ${plural(leakCount ?? 0, 'resource leak')}`
        : `${plural(leakCount ?? 0, 'orphaned PV')} — storage outliving deleted namespaces`
      : verdict === 'amber'
        ? `${plural(stuckTeardownCount, 'stuck teardown')} — destroy not completing`
        : verdict === 'green'
          ? 'Clean — all teardowns completing'
          : stuckObserved
            ? 'No stuck teardowns — leak scan unavailable'
            : 'Teardown state unobserved';

  const outcomeEntries = Object.entries(resolutions.data?.by_type ?? {})
    .sort(([, a], [, b]) => b - a);
  const outcomeTotal = resolutions.data?.total ?? 0;
  const recentResolutions = (resolutions.data?.records ?? []).slice(0, 8);

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-white">Are teardowns completing, and are we leaking resources?</h1>
        <p className="text-sm text-[#6A6E73] mt-1">
          Stuck destroys, orphaned storage, and how resolutions landed · leak detector runs live
          against the cluster (10-minute cadence) ·{' '}
          <Link to="/operations" className="text-[#73BCF7]">full operations view →</Link>
        </p>
      </header>

      {stuck.error && (
        <div className="bg-[#2e2e2e] border border-[#EE0000]/40 rounded-lg p-4 text-sm text-white">
          Failed to load stuck instances: {String(stuck.error)}
        </div>
      )}

      <section aria-label="Teardown health">
        <VerdictBanner
          state={verdict}
          headline={headline}
          chips={[
            `stuck threshold ${thresholdHours}h`,
            `destroy-failed ${destroyFailed}`,
            leakCount != null ? `${leakedCapacityGi} Gi orphaned` : 'leaks unobserved',
          ]}
          meta={resolutions.data
            ? `avg TTR ${resolutions.data.avg_ttr_minutes ?? '—'}m · last 7 days`
            : undefined}
        />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
          <MetricCard
            label="Stuck teardowns"
            value={stuckTeardownCount}
            sub={`destroy-failed ${destroyFailed} · threshold ${thresholdHours}h`}
            accent={stuckTeardownCount > 0 ? 'amber' : 'green'}
          />
          <MetricCard
            label="Orphaned PVs"
            value={leakCount ?? '—'}
            sub={leakCount != null && leakCount > 0 ? `${leakedCapacityGi} Gi leaked` : 'live leak scan'}
            accent={leakCount != null && leakCount > 0 ? 'red' : leakCount === 0 ? 'green' : undefined}
          />
          <MetricCard
            label="Resolutions (7d)"
            value={resolutions.data?.total ?? '—'}
            sub={`avg TTR ${resolutions.data?.avg_ttr_minutes ?? '—'}m`}
          />
          <MetricCard
            label="Reclaimed"
            value={resolutions.data?.by_type?.reclaimed ?? 0}
            sub="lifecycle-complete teardowns"
            accent={(resolutions.data?.by_type?.reclaimed ?? 0) > 0 ? 'green' : undefined}
          />
        </div>
      </section>

      <section aria-label="Stuck teardowns">
        <SectionHeader right={`${teardownRows.length} namespace${teardownRows.length === 1 ? '' : 's'} · destroy states only`}>
          Stuck teardowns
        </SectionHeader>
        {gaps.data?.stuck_teardowns?.error && (
          <div className="text-xs text-[#F0AB00] mb-2">
            ⚠ Live teardown detector {gaps.data.stuck_teardowns.partial ? 'partial' : 'failed'}:{' '}
            {gaps.data.stuck_teardowns.error} — snapshot data below may be incomplete.
          </div>
        )}
        {teardownRows.length === 0 && !stuck.isLoading && (
          <div className="text-sm text-[#3E8635] flex items-center gap-2">
            <span aria-hidden="true">✓</span>
            No teardowns stuck — nothing in destroying or destroy-failed past the threshold
          </div>
        )}
        <ul className="space-y-2">
          {teardownRows.map((row) => (
            <li key={row.namespace}>
              <Link
                to={`/lab/${encodeURIComponent(row.namespace)}`}
                aria-label={`Stuck teardown ${row.namespace}, state ${row.state}`}
                className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-3 hover:border-[#555] transition block"
              >
                <div className="flex items-center justify-between gap-4">
                  <span className="text-sm font-semibold text-white truncate font-mono">
                    {row.namespace}
                  </span>
                  <StatusBadge status={row.state} colors={TEARDOWN_COLORS} />
                </div>
                <div className="text-xs text-[#6A6E73] mt-1 flex gap-4 flex-wrap">
                  <span>age {formatAge(row.ageHours)}</span>
                  {row.cluster && <span>cluster {row.cluster}</span>}
                  {row.subject && <span className="truncate max-w-[24rem]">subject {row.subject}</span>}
                  {row.namespaceExists === false && (
                    <span className="text-[#F0AB00]">namespace already gone — control-plane leftover</span>
                  )}
                  {row.namespaceExists === true && <span>namespace still on cluster</span>}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section aria-label="Resolution outcomes">
        <SectionHeader
          right={resolutions.data ? `last 7 days · avg TTR ${resolutions.data.avg_ttr_minutes ?? '—'}m` : 'last 7 days'}
        >
          Resolution outcomes
        </SectionHeader>
        {resolutions.error && (
          <div className="bg-[#2e2e2e] border border-[#EE0000]/40 rounded-lg p-3 text-sm text-white">
            Failed to load resolutions: {String(resolutions.error)}
          </div>
        )}
        {resolutions.isLoading && (
          <div className="text-sm text-[#6A6E73]">Loading resolutions…</div>
        )}
        {resolutions.data && outcomeEntries.length === 0 && (
          <div className="text-sm text-[#6A6E73]">No resolutions recorded in the last 7 days.</div>
        )}
        {outcomeEntries.length > 0 && (
          <div className="flex gap-2 flex-wrap" role="list" aria-label="Resolution type distribution">
            {outcomeEntries.map(([type, count]) => (
              <span
                key={type}
                role="listitem"
                className={`text-xs font-semibold px-2.5 py-1 rounded-full ${OUTCOME_CHIP[type] ?? 'bg-white/5 text-[#c7c7c7] border border-[#3a3a3a]'}`}
              >
                {type} · {count}
                {outcomeTotal > 0 && ` (${Math.round((count / outcomeTotal) * 100)}%)`}
              </span>
            ))}
          </div>
        )}
        {recentResolutions.length > 0 && (
          <ul className="mt-3 space-y-1" aria-label="Recent resolutions">
            {recentResolutions.map((r) => (
              <li key={r.id} className="text-sm text-white flex justify-between gap-4 items-baseline">
                <span className="truncate">
                  <Link
                    to={`/lab/${encodeURIComponent(r.lab_code)}`}
                    className="text-[#73BCF7] hover:underline font-mono"
                  >
                    {r.lab_code}
                  </Link>
                  <span className="text-[#c7c7c7] mx-2">{r.resolution_type}</span>
                  {r.failure_class && (
                    <span className="text-xs text-[#6A6E73]">{r.failure_class}</span>
                  )}
                </span>
                <span className="text-xs text-[#6A6E73] whitespace-nowrap">
                  {r.ttr_minutes != null ? `TTR ${r.ttr_minutes}m` : 'TTR —'} ·{' '}
                  {relativeTime(r.resolved_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Resource leaks">
        <SectionHeader right={leaks ? `${leaks.total_pvs ?? '—'} PVs scanned` : 'live cluster scan'}>
          Resource leaks
        </SectionHeader>
        {gaps.isLoading && (
          <div className="text-sm text-[#6A6E73]">Running leak scan (live cluster query)…</div>
        )}
        {!gaps.isLoading && leakScanFailed && (
          <div className="bg-[#2e2e2e] border border-[#F0AB00]/40 rounded-lg p-3 text-sm text-white">
            Leak scan unavailable — {String(gaps.error || leaks?.error)}. The verdict above reads
            unknown, not clean: a zero is only healthy when the scan succeeded.
          </div>
        )}
        {leakCount === 0 && (
          <div className="text-sm text-[#3E8635] flex items-center gap-2">
            <span aria-hidden="true">✓</span>
            No orphaned PVs — no volume is bound to a deleted namespace
          </div>
        )}
        {orphanedPvs.length > 0 && (
          <ul className="space-y-2">
            {orphanedPvs.map((pv) => (
              <li
                key={pv.pv_name}
                className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-3"
                aria-label={`Orphaned PV ${pv.pv_name}, ${pv.capacity}, bound to deleted namespace ${pv.bound_to_namespace}`}
              >
                <div className="flex items-center justify-between gap-4">
                  <span className="text-sm font-semibold text-white font-mono truncate">
                    {pv.pv_name}
                  </span>
                  <span className="text-xs font-semibold text-[#EE0000] whitespace-nowrap">
                    {pv.capacity} · {pv.status}
                  </span>
                </div>
                <div className="text-xs text-[#6A6E73] mt-1 flex gap-4 flex-wrap">
                  <span>
                    bound to{' '}
                    <Link
                      to={`/lab/${encodeURIComponent(pv.bound_to_namespace)}`}
                      className="text-[#73BCF7] hover:underline font-mono"
                    >
                      {pv.bound_to_namespace}
                    </Link>{' '}
                    (deleted)
                  </span>
                  <span>claim {pv.bound_to_pvc}</span>
                  {pv.storage_class && pv.storage_class !== '?' && (
                    <span>class {pv.storage_class}</span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        {(leaks?.orphaned_pvc_count ?? 0) > 0 && (
          <div className="text-xs text-[#F0AB00] mt-2">
            ⚠ {leaks?.orphaned_pvc_count} orphaned PVC(s) referencing missing volumes —{' '}
            <Link to="/proof" className="text-[#73BCF7] hover:underline">
              full detector output in the Proof Lab
            </Link>
          </div>
        )}
      </section>

      <p className="text-xs text-[#6A6E73]">
        Stuck teardowns merge the live AnarchySubject detector (age, cluster — stuck past{' '}
        {thresholdHours}h) with the Babylon snapshot's destroy-failed instances; leaks are PVs
        bound to namespaces that no longer exist.{' '}
        <Link to="/proof" className="text-[#73BCF7]">Detector details in the Proof Lab →</Link>
      </p>
    </div>
  );
}
