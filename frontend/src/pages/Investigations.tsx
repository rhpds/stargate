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
import { request, api } from '../api/client';

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

interface PendingActionParams {
  failure_class?: string | null;
  cluster?: string | null;
  severity?: string | null;
  rca_output?: string | Record<string, unknown> | null;
  evidence_chain?: unknown[] | null;
  description?: string | null;
  remediation_suggestion?: string | null;
}

interface PendingAction {
  id: number;
  action_type: string;
  target: string;
  confidence: number | null;
  proposed_by?: string | null;
  proposed_at?: string | null;
  parameters?: PendingActionParams | null;
}

interface ApprovalQueueResponse {
  pending?: PendingAction[];
  resolved?: PendingAction[];
}

/** One live namespace row from /admin/lifecycle-matrix. */
interface LifecycleNamespace {
  namespace: string;
  attention?: string | null;
  investigation_skip_reason?: string | null;
}

/**
 * Decode a raw investigation_skip_reason (written by
 * engine.attention_classifier.should_auto_investigate, carried on the
 * lifecycle matrix) into the human chip the old Operations page showed —
 * same match order, hyphenated labels for the coverage line.
 */
function decodeSkipReason(reason: string | null | undefined): string {
  const s = reason || '';
  if (!s) return 'pending';
  if (s.includes('TRANSIENT')) return 'learned-transient';
  if (s.startsWith('attention=expected')) return 'expected';
  if (s.startsWith('attention=provisioning')) return 'provisioning';
  if (s.includes('already investigated')) return 'recent';
  if (s.includes('rate limit')) return 'rate-limited';
  if (s.includes('daily')) return 'daily-budget';
  if (s.includes('watch_and_wait')) return 'self-resolves';
  if (s.includes('pattern covered')) return 'pattern-covered';
  if (s.startsWith('attention=stuck') || s.startsWith('attention=anomalous')) return 'eligible';
  return 'skipped';
}

/**
 * rca_output arrives either as JSON (root_cause + evidence_chain) or as
 * prose — the same two shapes the old Remediation RCADetail handled.
 */
function parseRcaOutput(
  rca: string | Record<string, unknown> | null | undefined,
): { root_cause?: string; evidence_chain?: unknown[] } | null {
  if (!rca) return null;
  if (typeof rca === 'object') return rca as { root_cause?: string; evidence_chain?: unknown[] };
  const cleaned = rca.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```\s*$/, '').trim();
  try {
    const parsed = JSON.parse(cleaned);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null; // prose — the caller falls back to the raw string
  }
}

/** Evidence-chain entries are strings or signal objects; render either. */
function evidenceText(e: unknown): string {
  if (typeof e === 'string') return e;
  if (e && typeof e === 'object') {
    const rec = e as Record<string, unknown>;
    for (const k of ['description', 'message', 'summary', 'reason']) {
      const v = rec[k];
      if (typeof v === 'string') return v;
    }
  }
  return JSON.stringify(e);
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
          <DiagnosticsRunner namespace={inv.lab_code ?? inv.namespace} cluster={inv.cluster ?? ''} lab={inv.lab_code ?? inv.namespace} />
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

/**
 * Diagnostics runner (salvage item 9): the same read-only evidence
 * commands the backend gathers for an investigation (its
 * _BASELINE_DIAGNOSTICS set), runnable by the human reviewing the
 * diagnosis — trust, but verify. Behind a collapsed <details> so the
 * causal chain stays uncluttered; output colored by exit code.
 */
const EVIDENCE_COMMANDS = [
  'oc get pods -n {namespace} -o wide',
  'oc get events -n {namespace} --sort-by=.lastTimestamp',
  'oc get svc -n {namespace}',
  'oc get pvc -n {namespace}',
];

function DiagnosticsRunner({ namespace, cluster, lab }: { namespace: string; cluster: string; lab: string }) {
  const [results, setResults] = React.useState<Record<string, { output: string; exit_code: number; loading?: boolean }>>({});

  const run = (cmd: string) => {
    setResults((prev) => ({ ...prev, [cmd]: { output: '', exit_code: 0, loading: true } }));
    api.runDiagnostic({ command: cmd, namespace, cluster })
      .then((data) => setResults((prev) => ({ ...prev, [cmd]: { output: data.output, exit_code: data.exit_code } })))
      .catch((err: { message?: string }) =>
        setResults((prev) => ({ ...prev, [cmd]: { output: `Error: ${err?.message || 'request failed'}`, exit_code: -1 } })));
  };

  return (
    <details className="border border-[#2e2e2e] rounded-lg overflow-hidden">
      <summary className="px-3 py-2 text-xs font-semibold text-[#c7c7c7] cursor-pointer hover:bg-white/5 transition select-none">
        Run the evidence commands yourself
      </summary>
      <div className="p-3 space-y-2 border-t border-[#2e2e2e]">
        <div className="text-xs text-[#6A6E73]">
          Read-only oc commands against {lab}{cluster ? ` on ${cluster}` : ''} — the same evidence the diagnosis rests on.
        </div>
        {EVIDENCE_COMMANDS.map((template) => {
          const cmd = template.replace('{namespace}', namespace).replace('{cluster}', cluster);
          const result = results[cmd];
          return (
            <div key={template}>
              <div className="flex items-center gap-2">
                <pre className="flex-1 text-xs text-[#4EC9B0] bg-[#1a1a1a] border border-[#2e2e2e] rounded px-2 py-1 font-mono overflow-x-auto">{cmd}</pre>
                <button
                  className="text-xs px-3 py-1.5 rounded bg-[#73BCF7]/10 text-[#73BCF7] border border-[#73BCF7]/30 hover:bg-[#73BCF7]/20 transition disabled:opacity-50 shrink-0"
                  disabled={result?.loading}
                  onClick={() => run(cmd)}
                  aria-label={`Run ${cmd}`}>
                  {result?.loading ? '…' : result ? 'Re-run' : 'Run'}
                </button>
              </div>
              {result && !result.loading && (
                <pre className={`mt-1 text-xs rounded px-2 py-1 font-mono overflow-x-auto max-h-40 overflow-y-auto ${
                  result.exit_code === 0
                    ? 'bg-[#0d1f0d] text-[#4ade80] border border-[#1a3a1a]'
                    : 'bg-[#1f0d0d] text-[#f87171] border border-[#3a1a1a]'
                }`}>{result.output || '(no output)'}</pre>
              )}
            </div>
          );
        })}
      </div>
    </details>
  );
}

/**
 * One pending action, compact (salvage item 6): chips for
 * severity/confidence, the RCA's root cause + evidence chain when
 * present (else the action description), and the two decisions a human
 * can make — Acknowledge (reviewed, nothing executes) or Dismiss
 * (false positive).
 */
function ApprovalRow({
  item,
  busy,
  onAcknowledge,
  onDismiss,
}: {
  item: PendingAction;
  busy?: boolean;
  onAcknowledge: (id: number) => void;
  onDismiss: (id: number) => void;
}) {
  const params = item.parameters ?? {};
  const rca = parseRcaOutput(params.rca_output);
  const proseRca = typeof params.rca_output === 'string' && params.rca_output.trim()
    ? params.rca_output.trim() : null;
  const description = rca?.root_cause || proseRca || params.description || params.remediation_suggestion || null;
  const chain = (rca?.evidence_chain ?? params.evidence_chain ?? []) as unknown[];
  const evidence = chain.slice(0, 2);
  const confidence = typeof item.confidence === 'number' ? item.confidence : null;

  return (
    <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-3">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm text-white font-medium truncate">{item.action_type}</span>
            {params.severity && (
              <StatusBadge status={params.severity}
                colors={{ critical: '#EE0000', high: '#F0AB00', medium: '#6A6E73', low: '#6A6E73' }} />
            )}
            {confidence !== null && (
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full"
                style={{
                  backgroundColor: confidence >= 0.8 ? '#3E8635' : confidence >= 0.5 ? '#F0AB00' : '#EE0000',
                  color: confidence >= 0.5 && confidence < 0.8 ? '#151515' : '#fff',
                }}>
                {Math.round(confidence * 100)}% confidence
              </span>
            )}
            {params.failure_class && (
              <span className="text-xs text-[#6A6E73] truncate">{params.failure_class}</span>
            )}
          </div>
          <div className="text-xs text-[#6A6E73] mt-0.5">
            {item.target}
            {params.cluster ? ` · ${params.cluster}` : ''}
            {item.proposed_at ? ` · ${relativeTime(item.proposed_at)}` : ''}
            {item.proposed_by && item.proposed_by !== 'stargate' ? ` · via ${item.proposed_by}` : ''}
          </div>
          {description && (
            <p className="text-xs text-[#9a9a9a] mt-1 line-clamp-2">{description}</p>
          )}
          {evidence.length > 0 && (
            <div className="text-xs text-[#8a8a8a] mt-1 space-y-0.5">
              {evidence.map((e, i) => (
                <div key={i} className="flex gap-1.5 min-w-0">
                  <span className="text-[#6A6E73] shrink-0">{i + 1}.</span>
                  <span className="truncate">{evidenceText(e)}</span>
                </div>
              ))}
              {chain.length > evidence.length && (
                <span className="text-[#6A6E73]">+{chain.length - evidence.length} more evidence</span>
              )}
            </div>
          )}
        </div>
        <div className="flex gap-2 shrink-0">
          <button className="text-xs px-3 py-1.5 rounded bg-[#3E8635]/20 text-[#3E8635] border border-[#3E8635]/40 hover:bg-[#3E8635]/30 transition disabled:opacity-50"
            disabled={busy}
            onClick={() => onAcknowledge(item.id)}
            aria-label={`Acknowledge ${item.action_type} for ${item.target}`}
            title="Mark as acknowledged — no action will be executed">
            ✓ Acknowledge
          </button>
          <button className="text-xs px-3 py-1.5 rounded bg-[#EE0000]/10 text-[#EE0000] border border-[#EE0000]/30 hover:bg-[#EE0000]/20 transition disabled:opacity-50"
            disabled={busy}
            onClick={() => onDismiss(item.id)}
            aria-label={`Dismiss ${item.action_type} for ${item.target}`}
            title="Dismiss this finding">
            ✕ Dismiss
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Pending actions (salvage item 6): the approval queue the old
 * Remediation page owned, surfaced below the review queue where the
 * review work already happens. Acknowledge/Dismiss hit the same
 * /admin/approval-queue endpoints (api.approveAction / api.rejectAction).
 */
function PendingActionsSection() {
  const qc = useQueryClient();
  const queue = useQuery({
    queryKey: ['approval-queue'],
    queryFn: () => request<ApprovalQueueResponse>('/admin/approval-queue'),
    refetchInterval: 60_000,
  });
  const acknowledge = useMutation({
    mutationFn: (id: number) => api.approveAction(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['approval-queue'] }),
  });
  const dismiss = useMutation({
    mutationFn: (id: number) => api.rejectAction(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['approval-queue'] }),
  });

  const pending = queue.data?.pending ?? [];
  const rowBusy = (id: number) =>
    (acknowledge.isPending && acknowledge.variables === id)
    || (dismiss.isPending && dismiss.variables === id);

  return (
    <section aria-label="Pending actions">
      <SectionHeader right="acknowledge = reviewed, nothing executed; dismiss = false positive">
        Pending actions
      </SectionHeader>
      {queue.error && (
        <div className="text-xs text-[#EE0000]">Approval queue unavailable: {String(queue.error)}</div>
      )}
      {queue.isLoading && (
        <div className="text-sm text-[#6A6E73]">Loading pending actions…</div>
      )}
      {!queue.isLoading && !queue.error && pending.length === 0 && (
        <div className="text-sm text-[#6A6E73]">Nothing pending — no findings waiting on a human decision.</div>
      )}
      {(acknowledge.error || dismiss.error) && (
        <div className="text-xs text-[#EE0000] mb-2">
          Decision failed: {String(acknowledge.error ?? dismiss.error)}
        </div>
      )}
      <div className="space-y-2">
        {pending.map((item) => (
          <ApprovalRow key={item.id} item={item} busy={rowBusy(item.id)}
            onAcknowledge={(id) => acknowledge.mutate(id)}
            onDismiss={(id) => dismiss.mutate(id)} />
        ))}
      </div>
    </section>
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

  // Salvage item 7 — skip-reason coverage: which stuck namespaces did
  // NOT get investigated, and why. The honest "what we didn't look at"
  // line. Merge ported from the old Operations investigations tab:
  // lifecycle-matrix by_namespace joined against recent investigations
  // (a namespace is covered when an investigation exists for its
  // lab_code).
  const lifecycle = useQuery({
    queryKey: ['lifecycle-matrix'],
    queryFn: async (): Promise<{ by_namespace?: LifecycleNamespace[] }> => api.getLifecycleMatrix(),
    refetchInterval: 120_000,
  });
  const coverageInvs = useQuery({
    queryKey: ['investigations-coverage'],
    queryFn: async (): Promise<unknown> => api.getInvestigations({ limit: 100 }),
    refetchInterval: 60_000,
  });

  const skipCoverage = React.useMemo(() => {
    if (!lifecycle.data || !coverageInvs.data) return null;
    const raw = coverageInvs.data;
    const invList: Array<{ lab_code?: string | null }> = Array.isArray(raw)
      ? raw
      : ((raw as { investigations?: Array<{ lab_code?: string | null }> }).investigations ?? []);
    const investigated = new Set(
      invList.map((i) => i.lab_code).filter((c): c is string => !!c),
    );
    const counts = new Map<string, number>();
    let total = 0;
    for (const ns of lifecycle.data.by_namespace ?? []) {
      if (ns.attention !== 'stuck' || investigated.has(ns.namespace)) continue;
      total += 1;
      const label = decodeSkipReason(ns.investigation_skip_reason);
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }
    if (total === 0) return null;
    const reasons = [...counts.entries()].sort((a, b) => b[1] - a[1]);
    return { total, reasons };
  }, [lifecycle.data, coverageInvs.data]);

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
          {skipCoverage && (
            <div className="mt-2 text-xs text-[#8a8a8a] flex items-center gap-2 flex-wrap"
              role="status"
              aria-label={`${skipCoverage.total} stuck namespaces not investigated`}>
              <span>{skipCoverage.total} stuck namespaces not investigated —</span>
              {skipCoverage.reasons.map(([label, count]) => (
                <span key={label}
                  className="px-2 py-0.5 rounded-full bg-[#1a1a1a] border border-[#2e2e2e] text-[#c7c7c7]">
                  {count} {label}
                </span>
              ))}
            </div>
          )}
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

      <PendingActionsSection />
    </div>
  );
}

export default Investigations;
