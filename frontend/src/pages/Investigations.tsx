/**
 * Investigations — the workhorse triage page. (Frontend redesign Phase 3, third page.)
 *
 * ONE question: "Why did it fail — and is it one bug or many?" — the
 * known-issues rollup answers the second half ("ten investigations, one
 * chart bug"), the unreviewed queue is the review work, and every entry
 * drills to its causal chain. Reviewing is one click: the adoption loop,
 * surfaced where the work happens.
 */

import React from 'react';
import { Link } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { MetricCard, SectionHeader, StatusBadge, VerdictBanner, relativeTime, statusColor, splitAnalysisSections } from '../components/ui';
import FormattedAnalysis from '../components/FormattedAnalysis';
import { request } from '../api/client';

interface InvestigationRow {
  id: number;
  namespace: string;
  lab_code: string | null;
  cluster: string | null;
  failure_class: string | null;
  status: string;
  review_state: string;
  created_at: string;
  root_cause?: string | null;
}

interface InvestigationsResponse {
  investigations?: InvestigationRow[];
  total?: number;
}

interface KnownIssue {
  signature: string;
  bucket: string;
  title: string;
  failure_class: string | null;
  namespace_count: number;
  investigation_count: number;
  representative_investigation_id: number | null;
  top_root_cause_excerpt: string | null;
  last_seen: string | null;
}

interface KnownIssuesResponse {
  issues?: KnownIssue[];
  summary?: {
    issues: number;
    platform: number;
    platform_self: number;
    lab_family: number;
    unknown: number;
  };
}

function QueueRow({
  inv,
  onApprove,
  onReject,
}: {
  inv: InvestigationRow;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const detail = useQuery({
    queryKey: ['investigation-detail', inv.id],
    queryFn: () =>
      request<{ analysis?: string; root_cause?: string; remediation_suggestion?: string }>(
        `/dashboard/investigations/${inv.id}`),
    enabled: open,
  });
  const parsed = detail.data?.analysis || detail.data?.root_cause
    ? splitAnalysisSections(detail.data.analysis || detail.data.root_cause || '')
    : null;

  return (
    <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg">
      <div className="p-3 flex items-center justify-between gap-4 cursor-pointer" onClick={() => setOpen(!open)}>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: statusColor(inv.status) }}
              aria-label={`status: ${inv.status}`} />
            <Link to={`/lab/${inv.lab_code ?? inv.namespace}`}
              className="text-sm text-white font-medium truncate hover:text-[#73BCF7]"
              onClick={(e) => e.stopPropagation()}>
              {inv.lab_code ?? inv.namespace}
            </Link>
            <span className="text-xs text-[#6A6E73] truncate">{inv.failure_class ?? '(unclassified)'}</span>
            {parsed?.verdict && (
              <StatusBadge status={parsed.verdict === 'ACTIONABLE' ? 'fail' : 'ok'}
                label={parsed.verdict} />
            )}
          </div>
          <div className="text-xs text-[#6A6E73] mt-0.5">
            {inv.namespace} · {inv.cluster} · {relativeTime(inv.created_at)}
            {open ? ' · ▲' : ' · ▼'}
          </div>
        </div>
        <div className="flex gap-2 shrink-0" onClick={(e) => e.stopPropagation()}>
          <button className="text-xs px-3 py-1.5 rounded bg-[#3E8635]/20 text-[#3E8635] border border-[#3E8635]/40 hover:bg-[#3E8635]/30 transition"
            onClick={() => onApprove(inv.id)} aria-label={`Approve diagnosis for ${inv.lab_code ?? inv.namespace}`}>
            ✓ Approve
          </button>
          <button className="text-xs px-3 py-1.5 rounded bg-[#EE0000]/10 text-[#EE0000] border border-[#EE0000]/30 hover:bg-[#EE0000]/20 transition"
            onClick={() => onReject(inv.id)} aria-label={`Reject diagnosis for ${inv.lab_code ?? inv.namespace}`}>
            ✕ Reject
          </button>
        </div>
      </div>
      {open && (
        <div className="border-t border-[#2e2e2e] p-4 space-y-3">
          {detail.isLoading && <div className="text-xs text-[#6A6E73]">Loading diagnosis…</div>}
          {detail.error && <div className="text-xs text-[#EE0000]">Failed to load detail: {String(detail.error)}</div>}
          {parsed && (
            <>
              {parsed.diagnosis && (
                <div>
                  <div className="text-xs font-semibold text-[#8a8a8a] uppercase tracking-wide mb-1">Diagnosis</div>
                  <div className="text-sm text-white"><FormattedAnalysis text={parsed.diagnosis} /></div>
                </div>
              )}
              {parsed.rootCause && (
                <div>
                  <div className="text-xs font-semibold text-[#8a8a8a] uppercase tracking-wide mb-1">Root Cause</div>
                  <div className="text-sm text-white"><FormattedAnalysis text={parsed.rootCause} /></div>
                </div>
              )}
              {(parsed.shadowRemediation || parsed.remaining) && (
                <div>
                  <div className="text-xs font-semibold text-[#8a8a8a] uppercase tracking-wide mb-1">Remediation</div>
                  <div className="text-sm text-white">
                    <FormattedAnalysis text={parsed.shadowRemediation || parsed.remaining || ''} />
                  </div>
                </div>
              )}
              {!parsed.diagnosis && !parsed.rootCause && detail.data?.root_cause && (
                <div className="text-sm text-white"><FormattedAnalysis text={detail.data.root_cause} /></div>
              )}
              {parsed?.verdict === 'ACTIONABLE' && (
                <GatePreview namespace={inv.namespace} failureClass={inv.failure_class ?? ''} cluster={inv.cluster ?? ''} />
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * The five-gate execution preview — the old Remediation page's best
 * feature (salvage item 5): what WOULD happen if we acted. Every gate
 * PASS/BLOCKED, the exact commands, the honest blocked-by reason. The
 * Approver persona's answer to "what needs my decision" — evidence
 * before action, never action without preview.
 */
function GatePreview({ namespace, failureClass, cluster }: { namespace: string; failureClass: string; cluster: string }) {
  const [open, setOpen] = React.useState(false);
  const preview = useQuery({
    queryKey: ['gate-preview', namespace, failureClass],
    queryFn: () =>
      request<{
        gates?: { gate: string; status: string; description?: string }[];
        blocked_by?: string | null;
        commands_to_run?: string[];
        execution_target?: string;
        verdict?: string;
      }>('/admin/remediation/preview', {
        method: 'POST',
        body: JSON.stringify({ namespace, failure_class: failureClass, cluster }),
      }),
    enabled: open,
  });

  return (
    <div className="border border-[#2e2e2e] rounded-lg overflow-hidden">
      <button
        className="w-full text-left px-3 py-2 text-xs font-semibold text-[#c7c7c7] hover:bg-white/5 transition flex items-center justify-between"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
      >
        <span>Preview fix — what would the five gates do?</span>
        <span aria-hidden="true">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="p-3 space-y-2 border-t border-[#2e2e2e]">
          {preview.isLoading && <div className="text-xs text-[#6A6E73]">Checking gates…</div>}
          {preview.error && <div className="text-xs text-[#EE0000]">Preview failed: {String(preview.error)}</div>}
          {preview.data && (
            <>
              <div className={`text-sm font-bold ${preview.data.blocked_by ? 'text-[#F0AB00]' : 'text-[#3E8635]'}`}>
                {preview.data.blocked_by
                  ? `Blocked at: ${preview.data.blocked_by}`
                  : 'All gates passed — ready to execute (requires approval)'}
              </div>
              {(preview.data.gates ?? []).map((g) => (
                <div key={g.gate} className="flex items-center gap-2 text-xs">
                  <span
                    className={`inline-block w-4 h-4 rounded flex items-center justify-center font-bold ${
                      g.status === 'PASS' ? 'bg-[#3E8635]/20 text-[#3E8635]'
                        : g.status === 'BLOCKED' ? 'bg-[#EE0000]/20 text-[#EE0000]'
                          : 'bg-[#6A6E73]/20 text-[#6A6E73]'
                    }`}
                    aria-label={g.status}>
                    {g.status === 'PASS' ? '✓' : g.status === 'BLOCKED' ? '✖' : '…'}
                  </span>
                  <span className="text-white font-medium">{g.gate}</span>
                  {g.description && <span className="text-[#8a8a8a] truncate">{g.description}</span>}
                </div>
              ))}
              {(preview.data.commands_to_run ?? []).length > 0 && (
                <div className="mt-2">
                  <div className="text-xs text-[#8a8a8a] mb-1">Commands that would run:</div>
                  <pre className="text-xs text-[#c7c7c7] bg-[#1a1a1a] rounded p-2 overflow-x-auto">
                    {(preview.data.commands_to_run ?? []).join('\n')}
                  </pre>
                </div>
              )}
              {preview.data.execution_target && (
                <div className="text-xs text-[#6A6E73]">target: {preview.data.execution_target}</div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Investigations() {
  const qc = useQueryClient();
  const queue = useQuery({
    queryKey: ['investigations-queue'],
    queryFn: () =>
      request<InvestigationsResponse>('/dashboard/investigations?limit=25'),
    refetchInterval: 60_000,
  });
  const known = useQuery({
    queryKey: ['known-issues'],
    queryFn: () =>
      request<KnownIssuesResponse>('/dashboard/known-issues?window_hours=168'),
    refetchInterval: 300_000,
  });

  const stats = useQuery({
    queryKey: ['investigation-stats'],
    queryFn: () => request<{ investigations_today?: number; daily_limit?: number; queue_depth?: number; auto_investigate?: boolean }>(
      '/dashboard/investigations/stats'),
    refetchInterval: 120_000,
  });

  const review = useMutation({
    mutationFn: (v: { id: number; approved: boolean }) =>
      request<{ ok?: boolean }>(`/dashboard/investigations/${v.id}/review`, {
        method: 'POST',
        body: JSON.stringify({ approved: v.approved }),
      }).catch(() =>
        // fall back to the MCP review path if the dashboard route is absent
        request<Record<string, unknown>>('/integration/review-diagnosis', {
          method: 'POST',
          body: JSON.stringify({ investigation_id: v.id, approved: v.approved, notes: 'via UI' }),
        })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['investigations-queue'] }),
  });

  const s = known.data?.summary;
  const issues = known.data?.issues ?? [];
  const unreviewed = (queue.data?.investigations ?? []).filter(
    (i) => i.review_state === 'unreviewed',
  );

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-white">
          Why did it fail — and is it one bug or many?
        </h1>
        <p className="text-sm text-[#6A6E73] mt-1">
          Known issues group shared root causes (last 7 days); the queue is the
          review work. Approvals publish knowledge entries and resolve model
          disputes.
        </p>
        {stats.data && (
          <p className="text-xs text-[#8a8a8a] mt-1">
            auto-investigate {stats.data.auto_investigate === false ? 'OFF' : 'ON'} ·{' '}
            {stats.data.investigations_today ?? 0} of {stats.data.daily_limit ?? 200} daily budget ·{' '}
            queue {stats.data.queue_depth ?? 0}
            {stats.data.auto_investigate === false && (
              <span className="text-[#F0AB00] ml-2">⚠ auto-investigate is OFF</span>
            )}
          </p>
        )}
      </header>

      {queue.error && (
        <div className="bg-[#2e2e2e] border border-[#EE0000]/40 rounded-lg p-4 text-sm text-white">
          Failed to load: {String(queue.error)}
        </div>
      )}
      {queue.isLoading && !queue.data && (
        <div className="text-sm text-[#6A6E73]">Loading the queue…</div>
      )}

      {s && (() => {
        const totalInv = issues.reduce((a, ki) => a + ki.investigation_count, 0);
        const sorted = [...issues].sort((a, b) => b.investigation_count - a.investigation_count);
        const top = sorted[0];
        const topShare = totalInv > 0 && top
          ? Math.round((top.investigation_count / totalInv) * 100) : 0;
        const bucketColors: Record<string, string> = {
          platform: '#EE0000', platform_self: '#F0AB00', lab_family: '#73BCF7', unknown: '#6A6E73',
        };
        return (
        <section aria-label="Known issues summary">
          <SectionHeader right={`unreviewed queue: ${unreviewed.length} · review = knowledge`}>
            Known issues (last 7 days)
          </SectionHeader>
          <VerdictBanner
            state={sorted.length === 0 ? 'unknown' : topShare >= 50 ? 'amber' : 'green'}
            headline={sorted.length === 0
              ? 'No known issues in the window — no failure class spans 3+ namespaces'
              : topShare >= 50
                ? `One bug — issue #1 covers ${topShare}% of ${totalInv} failed investigations`
                : `${sorted.length} issues, none dominant (${totalInv} investigations total)`}
            chips={[
              `${s.platform} platform · ${s.platform_self} platform-self · ${s.lab_family} lab-family`,
              `oldest waiting ${unreviewed.length > 0 ? relativeTime(unreviewed[unreviewed.length - 1]?.created_at) : '—'}`,
            ]}
          />
          {sorted.length > 0 && totalInv > 0 && (
            <div className="mt-3" role="img"
              aria-label={`Concentration: top issue covers ${topShare}% of ${totalInv} investigations`}>
              <div className="flex h-6 rounded-lg overflow-hidden gap-px">
                {sorted.slice(0, 8).map((ki) => (
                  <div key={ki.signature}
                    title={`${ki.title || ki.failure_class}: ${ki.investigation_count} investigations (${Math.round(100 * ki.investigation_count / totalInv)}%)`}
                    className="transition-opacity hover:opacity-80"
                    style={{
                      width: `${(ki.investigation_count / totalInv) * 100}%`,
                      backgroundColor: bucketColors[ki.bucket] ?? '#6A6E73',
                    }} />
                ))}
              </div>
              <div className="text-xs text-[#8a8a8a] mt-1">
                top issue: {top?.title || top?.failure_class} — {top?.namespace_count} namespaces × {top?.investigation_count} investigations
              </div>
            </div>
          )}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
            <MetricCard label="Open issues" value={s.issues} />
            <MetricCard label="Platform" value={s.platform} sub="infra-side fixes" />
            <MetricCard label="Platform-self" value={s.platform_self} sub="StarGate's own bugs" />
            <MetricCard label="Lab family" value={s.lab_family} sub="shared chart/config bugs" />
          </div>
          {issues.length === 0 && (
            <div className="text-sm text-[#6A6E73] mt-3">
              No known issues in the window — no failure class spans 3+
              namespaces with a shared root cause.
            </div>
          )}
          <div className="mt-3 space-y-2">
            {issues.slice(0, 5).map((ki) => (
              <div key={ki.signature} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-white truncate">
                    {ki.title || ki.failure_class || ki.signature}
                  </span>
                  <StatusBadge status={ki.bucket} />
                </div>
                <div className="text-xs text-[#6A6E73] mt-1 flex gap-4">
                  <span>
                    {ki.namespace_count} namespaces · {ki.investigation_count} investigations
                  </span>
                  {ki.last_seen && <span>last seen {relativeTime(ki.last_seen)}</span>}
                </div>
                {ki.top_root_cause_excerpt && (
                  <p className="text-xs text-[#9a9a9a] mt-1 line-clamp-2">
                    {ki.top_root_cause_excerpt}
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>
        );
      })()}

      <section aria-label="Unreviewed investigations">
        <SectionHeader right="approve publishes knowledge; reject marks re-examination">
          Review queue
        </SectionHeader>
        {unreviewed.length === 0 && (
          <div className="text-sm text-[#6A6E73]">Queue clear — every investigation reviewed.</div>
        )}
        <div className="space-y-2">
          {[...unreviewed].sort((a, b) => a.created_at.localeCompare(b.created_at)).slice(0, 15).map((inv) => (
            <QueueRow key={inv.id} inv={inv}
              onApprove={(id) => review.mutate({ id, approved: true })}
              onReject={(id) => review.mutate({ id, approved: false })} />
          ))}
        </div>
      </section>
    </div>
  );
}

export default Investigations;
