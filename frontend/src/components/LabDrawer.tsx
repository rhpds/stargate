/**
 * The lab drill-down for the Drawer (the click-in pattern): the status
 * card, recent evaluations, and the latest investigation's causal chain,
 * rendered inline — the list stays put behind the drawer.
 *
 * Shared by Investigations (queue rows, known-issue namespaces) and
 * Reclamation (stuck teardowns, resolution rows). Anywhere a workload
 * identity appears, clicking it opens this.
 */
import { useQuery } from '@tanstack/react-query';
import { StatusBadge, relativeTime, statusColor, splitAnalysisSections } from './ui';
import FormattedAnalysis from './FormattedAnalysis';
import { api } from '../api/client';

/** /integration/lab-status response (api.getLabStatus) — a type alias so
 *  the client's Record<string, unknown> return casts cleanly. */
type LabStatus = {
  lab_code?: string;
  latest_outcome?: string | null;
  latest_failure_class?: string | null;
  latest_message?: string | null;
  latest_evaluated_at?: string | null;
  latest_cluster?: string | null;
  total_evaluations?: number;
  failure_classes?: Record<string, number>;
  history?: Array<{
    run_id?: string;
    stage_id?: string;
    outcome?: string;
    failure_class?: string | null;
    message?: string | null;
    evaluated_at?: string | null;
    cluster_name?: string | null;
  }>;
};

interface LabInvestigationRow {
  job_id: string;
  status?: string | null;
  failure_class?: string | null;
  root_cause?: string | null;
  has_analysis?: boolean;
  review_state?: string | null;
  created_at?: string | null;
}

function LabDrawerContent({ labCode }: { labCode: string }) {
  const status = useQuery({
    queryKey: ['lab-status', labCode],
    queryFn: () => api.getLabStatus(labCode) as Promise<LabStatus>,
  });
  const invs = useQuery({
    queryKey: ['lab-investigations', labCode],
    queryFn: () => api.getInvestigations({ lab_code: labCode, limit: 5 }),
  });

  // the list returns {investigations} or a bare array — normalize both
  const rows: LabInvestigationRow[] = Array.isArray(invs.data)
    ? invs.data
    : (invs.data?.investigations ?? []);
  const latest = rows.find((r) => r.has_analysis || r.root_cause);
  const detail = useQuery({
    queryKey: ['lab-investigation-detail', latest?.job_id],
    queryFn: () => api.investigatePoll(latest?.job_id ?? ''),
    enabled: !!latest?.job_id,
  });

  const analysisText = detail.data?.analysis || detail.data?.root_cause
    || latest?.root_cause || '';
  const parsed = analysisText ? splitAnalysisSections(analysisText) : null;
  const history = status.data?.history ?? [];
  const failureClasses = Object.entries(status.data?.failure_classes ?? {})
    .sort(([, a], [, b]) => b - a)
    .slice(0, 6);

  return (
    <>
      {status.isLoading && <div className="text-sm text-[#6A6E73]">Loading lab status…</div>}
      {status.error && (
        <div className="bg-[#2e2e2e] border border-[#EE0000]/40 rounded-lg p-3 text-xs text-white">
          Lab status unavailable: {String(status.error)}
        </div>
      )}
      {status.data && (
        <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-base font-bold text-white">{status.data.lab_code ?? labCode}</span>
            {status.data.latest_outcome && (
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full text-white"
                style={{ backgroundColor: statusColor(status.data.latest_outcome) }}>
                {status.data.latest_outcome}
              </span>
            )}
            {status.data.latest_failure_class && (
              <span className="text-xs text-[#6A6E73] truncate">{status.data.latest_failure_class}</span>
            )}
          </div>
          <div className="text-xs text-[#6A6E73]">
            {status.data.total_evaluations ?? 0} evaluations
            {status.data.latest_cluster ? ` · ${status.data.latest_cluster}` : ''}
            {status.data.latest_evaluated_at ? ` · last evaluated ${relativeTime(status.data.latest_evaluated_at)}` : ''}
          </div>
          {status.data.latest_message && (
            <p className="text-xs text-[#9a9a9a]">{status.data.latest_message}</p>
          )}
          {failureClasses.length > 0 && (
            <div className="flex gap-2 flex-wrap pt-1">
              {failureClasses.map(([cls, count]) => (
                <span key={cls}
                  className="text-xs px-2 py-0.5 rounded-full bg-[#1a1a1a] border border-[#2e2e2e] text-[#c7c7c7]">
                  {cls} ×{count}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {history.length > 0 && (
        <div>
          <div className="text-xs font-semibold text-[#8a8a8a] uppercase tracking-wide mb-2">Recent evaluations</div>
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg divide-y divide-[#2e2e2e]">
            {history.map((ev, i) => (
              <div key={`${ev.run_id}-${ev.stage_id}-${i}`}
                className="flex items-center gap-3 px-3 py-2 text-xs">
                <span className="inline-block w-2 h-2 rounded-full shrink-0"
                  style={{ backgroundColor: statusColor(ev.outcome) }}
                  aria-label={`outcome: ${ev.outcome ?? 'unknown'}`} />
                <span className="text-white truncate flex-1" title={ev.stage_id}>{ev.stage_id ?? ev.run_id}</span>
                <span className="text-[#6A6E73] truncate max-w-[40%]">{ev.failure_class ?? ''}</span>
                <span className="text-[#6A6E73] shrink-0" title={ev.message ?? undefined}>
                  {relativeTime(ev.evaluated_at)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="text-xs font-semibold text-[#8a8a8a] uppercase tracking-wide mb-2">Causal chain</div>
        {invs.isLoading && <div className="text-xs text-[#6A6E73]">Loading investigations…</div>}
        {invs.error && (
          <div className="text-xs text-[#EE0000]">Investigations unavailable: {String(invs.error)}</div>
        )}
        {!latest && !invs.isLoading && !invs.error && (
          <div className="text-xs text-[#6A6E73]">No investigation on record for this lab yet.</div>
        )}
        {latest && (
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 space-y-3">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs text-[#6A6E73]">
                investigation {latest.job_id}
                {latest.created_at ? ` · ${relativeTime(latest.created_at)}` : ''}
                {latest.status ? ` · ${latest.status}` : ''}
              </span>
              {parsed?.verdict && (
                <StatusBadge status={parsed.verdict === 'ACTIONABLE' ? 'fail' : 'ok'}
                  label={parsed.verdict} />
              )}
            </div>
            {detail.isLoading && <div className="text-xs text-[#6A6E73]">Loading the diagnosis…</div>}
            {detail.error && (
              <div className="text-xs text-[#EE0000]">Diagnosis unavailable: {String(detail.error)}</div>
            )}
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
              </>
            )}
            {!parsed && !detail.isLoading && !detail.error && (
              <div className="text-xs text-[#6A6E73]">
                {detail.data?.status && detail.data.status !== 'complete'
                  ? `Investigation is ${detail.data.status} — no analysis yet.`
                  : 'No analysis text on record for this investigation.'}
              </div>
            )}
          </div>
        )}
      </div>
    </>
  );
}

/**
 * The five-gate execution preview — the old Remediation page's best
 * feature (salvage item 5): what WOULD happen if we acted. Every gate
 * PASS/BLOCKED, the exact commands, the honest blocked-by reason. The
 * Approver persona's answer to "what needs my decision" — evidence
 * before action, never action without preview.
 */

export { LabDrawerContent };
