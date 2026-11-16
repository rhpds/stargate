/**
 * Capacity — the planner's page. (Frontend redesign Phase 3, second page.)
 *
 * ONE question: "Will the schedule fit the fleet?" — the forecast's RAG
 * and authority state in headlines, event bounds (Summit/RH1-scale),
 * pool deficits, every number drilling to its evidence. The advisory
 * badge and gate context are visible in plain words, per the redesign's
 * rule: advisory is visible.
 */

import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { MetricCard, SectionHeader, StatusBadge, VerdictBanner, StateStrip, LegendRow } from '../components/ui';
import { request } from '../api/client';

interface ForecastHour {
  hour: string;
  sessions: number;
  vm_slots: number | null;
  deficit_state: string;
}

interface ResourceForecast {
  contract: string;
  authority: string;
  risk: string;
  window_hours: number;
  coverage: {
    sessions_total: number;
    sessions_with_profiles: number;
    sessions_fallback: number;
    lower_bound: boolean;
  };
  supply?: { vm_slots: number; basis: string; window_hours: number };
  peak_hour?: ForecastHour | null;
  hourly: ForecastHour[];
}

interface EventDay {
  sessions: number;
  cohort_bound: number;
  summed_bound: number;
  peak_concurrent: number;
}

interface EventForecast {
  events: Record<string, { event_id: number | null; days: Record<string, EventDay> }>;
}

const riskColor: Record<string, string> = {
  green: '#3E8635',
  amber: '#F0AB00',
  red: '#EE0000',
};

export default function Capacity() {
  const forecast = useQuery({
    queryKey: ['resource-forecast'],
    queryFn: () => request<ResourceForecast>('/api/v1/resource-forecast?hours=72'),
    refetchInterval: 300_000,
  });
  const cost = useQuery({
    queryKey: ['cost-analysis'],
    queryFn: () => request<{
      monthly_cost?: number; waste_pct?: number; failure_cost_monthly?: number;
      optimization_opportunities?: { description: string; sandbox_count: number; action?: string }[];
    }>('/admin/cost-analysis'),
    refetchInterval: 600_000,
  });
  const events = useQuery({
    queryKey: ['event-forecast'],
    queryFn: () => request<EventForecast>('/api/v1/event-forecast?days=90'),
    refetchInterval: 300_000,
  });

  const f = forecast.data;
  const error = forecast.error || events.error;

  const rankedEvents = Object.entries(events.data?.events ?? {})
    .map(([id, ev]: [string, EventForecast['events'][string]]) => ({
      id,
      peak: Math.max(0, ...Object.values(ev.days).map((d) => d.peak_concurrent)),
      days: Object.entries(ev.days).sort(([a], [b]) => a.localeCompare(b)),
    }))
    .sort((a, b) => b.peak - a.peak)
    .slice(0, 6);

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-white">Will the schedule fit the fleet?</h1>
        <p className="text-sm text-[#6A6E73] mt-1">
          {f ? (
            <>
              capacity-forecast/v1 · window {f.window_hours}h ·{' '}
              <span className="font-semibold">authority: {f.authority}</span> — the forecast
              has not been promoted to alerting; treat demand as a floor, not a ceiling
            </>
          ) : (
            'loading forecast…'
          )}
        </p>
      </header>

      {error && (
        <div className="bg-[#2e2e2e] border border-[#EE0000]/40 rounded-lg p-4 text-sm text-white">
          Failed to load capacity data: {String(error)}
        </div>
      )}
      {forecast.isLoading && !f && (
        <div className="text-sm text-[#6A6E73]">Loading forecast…</div>
      )}

      {f && (
        <section aria-label="Forecast">
          <VerdictBanner
            state={f.risk === 'green' ? 'green' : f.risk === 'red' ? 'red' : f.risk === 'amber' ? 'amber' : 'unknown'}
            headline={
              f.risk === 'green'
                ? 'Yes — observed headroom across the window'
                : f.risk === 'red'
                  ? 'No — observed demand exceeds supply'
                  : f.supply
                    ? `Amber — no deficit observed, but ${f.hourly.filter((h) => h.deficit_state === 'lower_bound_demand').length} of ${f.hourly.length} hours are lower-bound`
                    : 'Amber — supply not yet observed; hours read indeterminate'
            }
            chips={[
              `ADVISORY — NOT WIRED TO ALERTING`,
              f.supply ? `supply ${Math.round(f.supply.vm_slots).toLocaleString()} slots (${f.supply.basis})` : 'supply unobserved',
              `${f.coverage.sessions_fallback} unprofiled sessions — demand is a floor`,
            ]}
            meta={`window ${f.window_hours}h`}
          />
          <div className="mt-4">
            <StateStrip
              height="h-10"
              cells={f.hourly.map((h) => ({
                state: h.deficit_state === 'deficit' ? 'red' as const
                  : h.deficit_state === 'headroom' ? 'green' as const
                    : h.deficit_state === 'lower_bound_demand' ? 'floor' as const
                      : 'unknown' as const,
                title: `${h.hour} — ${h.vm_slots ?? '?'} slots (${h.deficit_state})`,
              }))}
            />
            <div className="mt-2"><LegendRow /></div>
          </div>
          <div className="mt-6">
          <SectionHeader right={`supply basis: ${f.supply?.basis ?? 'unobserved'}`}>
            Fleet forecast
          </SectionHeader>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <MetricCard
              label="Risk"
              value={<StatusBadge status={f.risk} colors={riskColor} /> as unknown as string}
              sub={f.risk === 'green' ? 'observed headroom' : 'see coverage'}
            />
            <MetricCard
              label="Observed supply"
              value={f.supply ? Math.round(f.supply.vm_slots).toLocaleString() : '—'}
              sub={f.supply ? `${f.supply.window_hours}h peak density` : 'unobserved'}
            />
            <MetricCard
              label="Peak demand (VM slots)"
              value={f.peak_hour?.vm_slots ?? '—'}
              sub={f.peak_hour?.hour?.slice(0, 16).replace('T', ' ')}
            />
            <MetricCard
              label="Coverage"
              value={`${f.coverage.sessions_with_profiles}/${f.coverage.sessions_total}`}
              sub={
                f.coverage.lower_bound
                  ? `${f.coverage.sessions_fallback} unprofiled — demand is a lower bound`
                  : 'fully observed'
              }
            />
          </div>
          </div>
        </section>
      )}

      <section aria-label="Upcoming events">
        <SectionHeader right="bounds, not points — cohort = one rotating audience; summed = separate audiences">
          Upcoming events
        </SectionHeader>
        {rankedEvents.length === 0 && !events.isLoading && (
          <div className="text-sm text-[#6A6E73]">No scheduled events in the window.</div>
        )}
        <div className="space-y-2">
          {rankedEvents.map((ev) => (
            <div
              key={ev.id}
              className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-3"
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-white">event {ev.id}</span>
                <span className="text-xs text-[#6A6E73]">
                  peak concurrent {ev.peak.toLocaleString()}
                </span>
              </div>
              <div className="mt-2 space-y-1">
                {ev.days.map(([date, d]) => (
                  <div key={date} className="text-xs text-[#6A6E73] flex gap-4">
                    <span className="w-24">{date}</span>
                    <span>{d.sessions} sessions</span>
                    <span>cohort ≤ {d.cohort_bound}</span>
                    <span>summed {d.summed_bound}</span>
                    <span className="text-white">peak {d.peak_concurrent}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {cost.data && (
        <section aria-label="Cost of failure">
          <SectionHeader right="estimates use default unit rates — capacity consumed, not direct spend">
            Are we burning money on failures?
          </SectionHeader>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <MetricCard label="Monthly cost" value={cost.data.monthly_cost != null ? `$${Math.round(cost.data.monthly_cost).toLocaleString()}` : '—'} />
            <MetricCard label="Waste" value={cost.data.waste_pct != null ? `${cost.data.waste_pct.toFixed(1)}%` : '—'}
              accent={cost.data.waste_pct != null ? (cost.data.waste_pct > 10 ? 'red' : cost.data.waste_pct > 5 ? 'amber' : 'green') : undefined} />
            <MetricCard label="Failure cost / mo" value={cost.data.failure_cost_monthly != null ? `$${Math.round(cost.data.failure_cost_monthly).toLocaleString()}` : '—'} />
          </div>
          {((cost.data.optimization_opportunities ?? []).length > 0) && (
            <div className="mt-3 space-y-1">
              {(cost.data.optimization_opportunities ?? []).slice(0, 4).map((o, i: number) => (
                <div key={i} className="text-xs text-[#c7c7c7] flex gap-2">
                  <span className="text-[#F0AB00]">⚠</span>
                  <span className="flex-1">{o.description}</span>
                  <span className="text-[#6A6E73] whitespace-nowrap">{o.sandbox_count} sandboxes</span>
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      <p className="text-xs text-[#6A6E73]">
        Deficit states per hour resolve against the observed supply; hours without both
        sides observed read indeterminate, never green.{' '}
        <Link to="/operations" className="text-[#73BCF7]">
          Full operations view →
        </Link>
      </p>
    </div>
  );
}
