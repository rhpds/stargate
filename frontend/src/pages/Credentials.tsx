/**
 * Credentials — are the keys StarGate depends on still working?
 *
 * Built for the 2026 Turkey Vulture rotation (GPTEINFRA-18544). Reachability
 * probes call a 401 a pass, so a revoked token used to look healthy until
 * something downstream broke. Every row here was exercised against its own
 * service, and the expiry comes from the token's own claim.
 */

import { Link } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCredentials } from '../api/hooks';
import { api } from '../api/client';
import type { CredentialRow } from '../api/types';
import { MetricCard, SectionHeader, StatusBadge, VerdictBanner, relativeTime } from '../components/ui';

const FAILURE_LABELS: Record<string, string> = {
  credential_missing: 'not found where configured',
  credential_rejected: 'rejected by the service',
  credential_unreachable: 'service unreachable',
  credential_expiring: 'expires soon',
  credential_no_expiry: 'no expiry — legacy token',
};

function expiryTone(days: number | null): string {
  if (days === null) return '#6A6E73';
  if (days <= 30) return '#EE0000';
  if (days <= 90) return '#F0AB00';
  return '#6A6E73';
}

function CredentialRowView({ row }: { row: CredentialRow }) {
  const tone = row.outcome === 'fail' ? '#EE0000' : row.outcome === 'warn' ? '#F0AB00' : '#3E8635';
  return (
    <div className="flex items-center gap-3 py-2 border-b border-[#1a1a1a] last:border-0">
      <span
        className="shrink-0 w-2 h-2 rounded-full"
        style={{ backgroundColor: tone }}
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-white text-sm font-medium truncate">{row.credential}</span>
          {row.kind && (
            <span className="text-[10px] uppercase tracking-wider text-[#6A6E73]">{row.kind}</span>
          )}
        </div>
        <div className="text-xs text-[#6A6E73] truncate" title={row.message}>
          {row.failure_class
            ? (FAILURE_LABELS[row.failure_class] ?? row.failure_class)
            : (row.message || 'authenticated')}
          {row.source ? ` · ${row.source}` : ''}
        </div>
      </div>
      {row.days_left === null && row.failure_class === 'credential_no_expiry' && (
        <span
          className="shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded-full"
          style={{ backgroundColor: '#EE000022', color: '#EE0000' }}
          title="Token carries no exp claim — it never expires"
        >
          no expiry
        </span>
      )}
      {row.days_left !== null && (
        <span
          className="shrink-0 text-[10px] font-semibold px-2 py-0.5 rounded-full"
          style={{ backgroundColor: `${expiryTone(row.days_left)}22`, color: expiryTone(row.days_left) }}
          title={row.expires_at ? `Expires ${row.expires_at}` : undefined}
        >
          {row.days_left}d
        </span>
      )}
      <StatusBadge status={row.outcome} />
      <span className="shrink-0 w-20 text-right text-[10px] text-[#6A6E73]">
        {row.checked_at ? relativeTime(row.checked_at) : '—'}
      </span>
    </div>
  );
}

export default function Credentials() {
  const { data, isLoading, isError } = useCredentials();
  const queryClient = useQueryClient();
  const refresh = useMutation({
    mutationFn: () => api.getCredentials(true),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['credentials'] }),
  });

  if (isLoading) {
    return (
      <div className="max-w-6xl mx-auto p-6 space-y-4 animate-pulse">
        <div className="h-8 bg-[#212121] rounded w-64" />
        <div className="h-24 bg-[#212121] rounded-xl" />
        <div className="h-64 bg-[#212121] rounded-lg" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="max-w-6xl mx-auto p-6">
        <p className="text-[#EE0000]">Failed to load credential health.</p>
      </div>
    );
  }

  const { summary, credentials, generated_at } = data;
  const rejected = credentials.filter((c) => c.outcome === 'fail');
  const expiringSoon = credentials.filter((c) => c.days_left !== null && c.days_left <= 90);
  const state = summary.rejected > 0 ? 'red' : summary.degraded > 0 || summary.expiring > 0 ? 'amber' : summary.total > 0 ? 'green' : 'unknown';

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Are our credentials still working?</h1>
          <p className="text-sm text-[#6A6E73] mt-1">
            Each credential is exercised against its own service · probed {relativeTime(generated_at)} ·
            {' '}rotation-relevant (GPTEINFRA-18544)
          </p>
        </div>
        <button
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
          className="shrink-0 px-3 py-1.5 rounded bg-[#212121] border border-[#2e2e2e] text-xs text-white hover:border-[#555] disabled:opacity-50"
        >
          {refresh.isPending ? 'Probing…' : 'Verify now'}
        </button>
      </header>

      {summary.total === 0 ? (
        <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-6 text-sm text-[#6A6E73]">
          No credential probes recorded yet. The loop runs every 15 minutes —
          press <span className="text-white">Verify now</span> to run one immediately.
        </div>
      ) : (
        <>
          <VerdictBanner
            state={state as 'green' | 'amber' | 'red' | 'unknown'}
            headline={
              summary.rejected > 0
                ? `${summary.rejected} credential${summary.rejected === 1 ? '' : 's'} rejected`
                : summary.expiring > 0
                  ? `All ${summary.total} credentials work — ${summary.expiring} expire within 90 days`
                  : `All ${summary.total} credentials verified`
            }
            chips={
              summary.rejected > 0
                ? rejected.slice(0, 4).map((c) => c.credential)
                : expiringSoon.slice(0, 4).map((c) => `${c.credential} · ${c.days_left}d`)
            }
            meta={`Last probe ${relativeTime(generated_at)}`}
          />

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <MetricCard label="Verified" value={summary.verified} />
            <MetricCard label="Rejected" value={summary.rejected} onClick={() => {}} />
            <MetricCard label="Expiring ≤90d" value={summary.expiring} />
            <MetricCard label="Tracked" value={summary.total} />
          </div>

          <section>
            <SectionHeader right={`${credentials.length} credentials`}>Credential health</SectionHeader>
            <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg px-4 py-2">
              {credentials.map((row) => (
                <CredentialRowView key={row.credential} row={row} />
              ))}
            </div>
            <p className="text-xs text-[#6A6E73] mt-2">
              Expiry is read from the credential's own claim where it has one; an
              opaque token shows no countdown. Findings feed the same evaluation
              history as every other signal — see <Link to="/failures" className="text-[#73BCF7]">Taxonomy</Link>.
            </p>
          </section>
        </>
      )}
    </div>
  );
}
