import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  useApprovalQueue,
  useApproveAction,
  useRejectAction,
  useRemediationConfigs,
  useRemediationActivity,
  useRemediation,
} from '../api/hooks';
import { useTimeRange } from '../components/TimeRangeContext';
import { api } from '../api/client';
import FormattedAnalysis from '../components/FormattedAnalysis';
import type {
  ApprovalQueueData,
  PendingActionItem,
  LabRemediationConfig,
  RemediationActivity,
} from '../api/types';

/* ---- helpers ---- */

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '--';
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 0) return 'just now';
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

const STATUS_COLORS: Record<string, string> = {
  approved: '#3E8635',
  executed: '#3E8635',
  completed: '#3E8635',
  rejected: '#C9190B',
  failed: '#C9190B',
  pending: '#F0AB00',
  proposed: '#F0AB00',
};

function statusColor(status: string): string {
  return STATUS_COLORS[status?.toLowerCase()] ?? '#6A6E73';
}

const MODE_LABELS: Record<string, string> = {
  recommend_only: 'Recommend Only',
  low_risk_auto: 'Low-Risk Auto',
  full_auto: 'Full Auto',
};

const MODE_COLORS: Record<string, string> = {
  recommend_only: '#6A6E73',
  low_risk_auto: '#F0AB00',
  full_auto: '#3E8635',
};

/* ---- sub-components ---- */

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
      <div className="text-2xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>
        {value}
      </div>
      <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">{label}</div>
    </div>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">{children}</h2>
  );
}

function ApprovalQueue({
  pending,
  onApprove,
  onReject,
}: {
  pending: PendingActionItem[];
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
}) {
  if (pending.length === 0) {
    return <p className="text-[#6A6E73] text-sm">No pending actions in the queue.</p>;
  }

  return (
    <div className="space-y-3">
      {pending.map((item) => (
        <div
          key={item.id}
          className="bg-[#1a1a1a] border border-[#333] rounded-lg p-4 flex items-start justify-between gap-4"
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-white text-sm font-medium">{item.action_type}</span>
              <span
                className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                style={{
                  backgroundColor:
                    item.confidence >= 0.8
                      ? '#3E8635'
                      : item.confidence >= 0.5
                      ? '#F0AB00'
                      : '#C9190B',
                  color: '#fff',
                }}
              >
                {Math.round(item.confidence * 100)}% confidence
              </span>
            </div>
            <div className="text-xs text-[#6A6E73] mb-1">
              Target: <span className="text-white">{item.target}</span>
            </div>
            <div className="text-xs text-[#6A6E73]">
              Proposed: {relativeTime(item.proposed_at)}
            </div>
          </div>
          <div className="flex gap-2 shrink-0">
            <button
              onClick={() => onApprove(item.id)}
              className="px-3 py-1.5 rounded text-xs font-semibold text-white transition hover:opacity-80"
              style={{ backgroundColor: '#3E8635' }}
            >
              Approve
            </button>
            <button
              onClick={() => onReject(item.id)}
              className="px-3 py-1.5 rounded text-xs font-semibold text-white transition hover:opacity-80"
              style={{ backgroundColor: '#C9190B' }}
            >
              Reject
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

function ActivityTable({ activity }: { activity: RemediationActivity[] }) {
  if (activity.length === 0) {
    return <p className="text-[#6A6E73] text-sm">No remediation activity recorded.</p>;
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[1fr_120px_80px_140px] gap-2 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-1 border-b border-[#2e2e2e]">
        <span>Action</span>
        <span>Target</span>
        <span>Status</span>
        <span>Executed</span>
      </div>
      {activity.map((act) => (
        <div
          key={act.id}
          className="grid grid-cols-[1fr_120px_80px_140px] gap-2 items-center py-1.5 border-b border-[#1a1a1a]"
        >
          <span className="text-sm text-white truncate">{act.action_type}</span>
          <span className="text-xs text-[#6A6E73] truncate">{act.target}</span>
          <span>
            <span
              className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
              style={{ backgroundColor: statusColor(act.status), color: '#fff' }}
            >
              {act.status}
            </span>
          </span>
          <span className="text-xs text-[#6A6E73]">{relativeTime(act.executed_at ?? act.created_at)}</span>
        </div>
      ))}
    </div>
  );
}

function ConfigTable({ configs }: { configs: LabRemediationConfig[] }) {
  if (configs.length === 0) {
    return <p className="text-[#6A6E73] text-sm">No remediation configs found.</p>;
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[1fr_140px_100px] gap-2 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-1 border-b border-[#2e2e2e]">
        <span>Lab</span>
        <span>Execution Mode</span>
        <span className="text-right">Max Actions/hr</span>
      </div>
      {configs.map((cfg) => (
        <div
          key={cfg.lab_code}
          className="grid grid-cols-[1fr_140px_100px] gap-2 items-center py-1.5 border-b border-[#1a1a1a]"
        >
          <span className="text-sm text-white truncate">{cfg.display_name || cfg.lab_code}</span>
          <span>
            <span
              className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
              style={{
                backgroundColor: MODE_COLORS[cfg.execution_mode] ?? '#6A6E73',
                color: '#fff',
              }}
            >
              {MODE_LABELS[cfg.execution_mode] ?? cfg.execution_mode}
            </span>
          </span>
          <span className="text-sm text-[#6A6E73] text-right">{cfg.max_actions_per_hour}</span>
        </div>
      ))}
    </div>
  );
}

/* ---- main page ---- */

export default function Remediation() {
  const { cluster } = useTimeRange();
  const approvalQueue = useApprovalQueue();
  const approveAction = useApproveAction();
  const rejectAction = useRejectAction();
  const remediationConfigs = useRemediationConfigs();
  const remediationActivity = useRemediationActivity();
  const remediation = useRemediation();
  const recommendations = useQuery({
    queryKey: ['remediation-recommendations', cluster],
    queryFn: () => api.getRemediationRecommendations(20, cluster || undefined),
    refetchInterval: 30_000,
  });

  const [expandedRec, setExpandedRec] = useState<number | null>(null);
  const [aiAnalysis, setAiAnalysis] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [remediateConfirm, setRemediateConfirm] = useState(false);
  const [remediateResult, setRemediateResult] = useState<any>(null);
  const [remediateLoading, setRemediateLoading] = useState(false);

  const isLoading =
    approvalQueue.isLoading || remediationConfigs.isLoading || remediationActivity.isLoading;
  const hasError =
    approvalQueue.isError || remediationConfigs.isError || remediationActivity.isError;

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8">
        <p className="text-[#6A6E73]">Loading...</p>
      </div>
    );
  }

  if (hasError) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8">
        <p className="text-[#C9190B]">Failed to load remediation data.</p>
      </div>
    );
  }

  const queueData = approvalQueue.data as ApprovalQueueData;
  const pending = queueData.pending ?? [];
  const configs = (remediationConfigs.data as { configs: LabRemediationConfig[] })?.configs ?? [];
  const activity = (remediationActivity.data as { activity: RemediationActivity[] })?.activity ?? [];

  const totalPending = pending.length;
  const recentExecuted = activity.filter((a) => a.status === 'executed' || a.status === 'completed').length;

  const handleApprove = (id: number) => {
    approveAction.mutate(id);
  };
  const handleReject = (id: number) => {
    rejectAction.mutate(id);
  };

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-white mb-2" style={{ fontFamily: 'Red Hat Display' }}>
          Remediation
        </h1>
        <p className="text-[#6A6E73]">Approval queue, execution history, playbook catalog</p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Recommendations" value={recommendations.data?.total ?? 0} />
        <MetricCard label="Ecosystem Issues" value={recommendations.data?.ecosystem_count ?? 0} />
        <MetricCard label="Pending Approval" value={totalPending} />
        <MetricCard label="Executed Actions" value={recentExecuted} />
      </div>

      {/* Auto-generated Recommendations */}
      <section>
        <SectionHeader>Recommendations (Last Hour)</SectionHeader>
        <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
          {!recommendations.data?.recommendations?.length ? (
            <p className="text-[#6A6E73] text-sm">{recommendations.isLoading ? 'Loading...' : 'No failures detected in the last hour.'}</p>
          ) : (
            <div className="space-y-0.5">
              <div className="grid grid-cols-[1fr_120px_150px_80px_80px_100px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
                <span>Namespace</span>
                <span>Cluster</span>
                <span>Failure Class</span>
                <span className="text-right">Count</span>
                <span>Severity</span>
                <span>Suggested Action</span>
              </div>
              {recommendations.data.recommendations.map((r: any, i: number) => (
                <div key={i}>
                  <div
                    className={`grid grid-cols-[1fr_120px_150px_80px_80px_100px] gap-3 items-center py-1.5 rounded cursor-pointer transition ${
                      expandedRec === i ? 'bg-[#2e2e2e]' : 'hover:bg-[#2a2a2a]'
                    } ${r.is_ecosystem ? 'border-l-2 border-l-[#EE0000]' : 'opacity-50'}`}
                    onClick={() => {
                      if (expandedRec === i) {
                        setExpandedRec(null);
                      } else {
                        setExpandedRec(i);
                        setAiAnalysis(null);
                        setRemediateConfirm(false);
                        setRemediateResult(null);
                      }
                    }}
                  >
                    <span className="text-sm text-white font-medium truncate">
                      {r.namespace}
                      {r.is_ecosystem && <span className="ml-1 text-[10px] text-[#EE0000] font-bold uppercase">eco</span>}
                    </span>
                    <span className="text-xs text-[#8A8D90]">{r.cluster}</span>
                    <span className="text-xs text-white truncate" title={r.failure_class}>{r.failure_class}</span>
                    <span className="text-sm text-white text-right font-bold">{r.count}</span>
                    <span className={`text-xs font-bold ${
                      r.severity === 'critical' ? 'text-[#C9190B]' :
                      r.severity === 'high' ? 'text-[#F0AB00]' :
                      r.severity === 'medium' ? 'text-[#6A6E73]' : 'text-[#555]'
                    }`}>{r.severity}</span>
                    <span className="text-xs text-[#8A8D90] truncate" title={r.catalog_action || 'no action mapped'}>
                      {r.catalog_action || '--'}
                    </span>
                  </div>

                  {expandedRec === i && (
                    <div className="bg-[#1a1a1a] border border-[#333] rounded-lg p-4 mb-2 mx-1 space-y-3">
                      <div className="grid grid-cols-[140px_1fr] gap-2 text-sm">
                        <span className="text-[#6A6E73]">Namespace</span>
                        <span className="text-white font-medium">{r.namespace}</span>
                        <span className="text-[#6A6E73]">Cluster</span>
                        <span className="text-white">{r.cluster}</span>
                        <span className="text-[#6A6E73]">Failure Class</span>
                        <span className="text-white font-medium">{r.failure_class}</span>
                        <span className="text-[#6A6E73]">Occurrences</span>
                        <span className="text-white font-bold">{r.count}</span>
                        <span className="text-[#6A6E73]">Severity</span>
                        <span className={`font-bold ${
                          r.severity === 'critical' ? 'text-[#C9190B]' :
                          r.severity === 'high' ? 'text-[#F0AB00]' :
                          r.severity === 'medium' ? 'text-[#6A6E73]' : 'text-[#555]'
                        }`}>{r.severity}</span>
                        <span className="text-[#6A6E73]">Last Seen</span>
                        <span className="text-white">{relativeTime(r.last_seen)}</span>
                        <span className="text-[#6A6E73]">Catalog Action</span>
                        <span className="text-white">{r.catalog_action || 'No action mapped'}</span>
                        {r.catalog_action && (
                          <>
                            <span className="text-[#6A6E73]">Risk Level</span>
                            <span className={`font-semibold ${
                              r.catalog_risk === 'low' ? 'text-[#3E8635]' :
                              r.catalog_risk === 'medium' ? 'text-[#F0AB00]' : 'text-[#C9190B]'
                            }`}>{r.catalog_risk}</span>
                          </>
                        )}
                      </div>

                      {r.sample_message && (
                        <div>
                          <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-1">Sample Error</div>
                          <div className="text-xs text-[#C9C9C9] bg-[#151515] rounded px-3 py-2 font-mono">{r.sample_message}</div>
                        </div>
                      )}

                      {r.catalog_commands && r.catalog_commands.length > 0 && (
                        <div>
                          <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-1">Catalog Commands</div>
                          {r.catalog_commands.map((cmd: string, ci: number) => (
                            <div key={ci} className="text-xs text-[#C9C9C9] bg-[#151515] rounded px-3 py-1.5 mb-1 font-mono">{cmd}</div>
                          ))}
                        </div>
                      )}

                      <div className="flex gap-3 pt-2">
                        <button
                          className="bg-[#EE0000] hover:bg-[#A30000] text-white text-sm px-4 py-2 rounded disabled:opacity-50"
                          disabled={aiLoading}
                          onClick={(e) => {
                            e.stopPropagation();
                            setAiLoading(true);
                            setAiAnalysis(null);
                            remediation.mutate(
                              { failure_class: r.failure_class, lab_code: r.namespace, cluster: r.cluster, context_type: 'lab' },
                              {
                                onSuccess: (data: any) => {
                                  setAiAnalysis(data?.llm_analysis || data?.analysis || data?.remediation || JSON.stringify(data, null, 2));
                                  setAiLoading(false);
                                },
                                onError: (err: any) => {
                                  setAiAnalysis(`Analysis failed: ${err.message}`);
                                  setAiLoading(false);
                                },
                              },
                            );
                          }}
                        >
                          {aiLoading ? 'Analyzing...' : 'Get AI Analysis'}
                        </button>

                        {r.is_ecosystem && !remediateConfirm && !remediateResult && (
                          <button
                            className="bg-[#F0AB00] hover:bg-[#C58C00] text-black text-sm px-4 py-2 rounded font-medium"
                            onClick={(e) => { e.stopPropagation(); setRemediateConfirm(true); }}
                          >
                            Remediate
                          </button>
                        )}
                      </div>

                      {aiAnalysis && (
                        <div className="bg-[#151515] border border-[#2e2e2e] rounded p-4">
                          <FormattedAnalysis text={aiAnalysis} />
                        </div>
                      )}

                      {remediateConfirm && !remediateResult && (
                        <div className="flex items-center gap-3 border-t border-[#333] pt-3">
                          <span className="text-sm text-[#F0AB00] font-medium">Execute remediation on {r.namespace}?</span>
                          <button
                            className="bg-[#EE0000] hover:bg-[#A30000] text-white text-sm px-4 py-2 rounded font-medium disabled:opacity-50"
                            disabled={remediateLoading}
                            onClick={(e) => {
                              e.stopPropagation();
                              setRemediateLoading(true);
                              api.executeRemediation({
                                namespace: r.namespace,
                                failure_class: r.failure_class,
                                cluster: r.cluster,
                              }).then((result) => {
                                setRemediateResult(result);
                                setRemediateLoading(false);
                                setRemediateConfirm(false);
                              }).catch((err) => {
                                setRemediateResult({ error: err.message });
                                setRemediateLoading(false);
                                setRemediateConfirm(false);
                              });
                            }}
                          >
                            {remediateLoading ? 'Executing...' : 'Confirm'}
                          </button>
                          <button
                            className="text-[#6A6E73] text-sm hover:text-white"
                            onClick={(e) => { e.stopPropagation(); setRemediateConfirm(false); }}
                          >
                            Cancel
                          </button>
                        </div>
                      )}

                      {remediateResult && (
                        <div className={`text-sm rounded p-3 ${remediateResult.executed ? 'bg-[#1a2e1a] border border-[#3E8635] text-[#3E8635]' : 'bg-[#2e1a1a] border border-[#C9190B] text-[#C9190B]'}`}>
                          {remediateResult.executed
                            ? `Remediation executed on ${r.namespace}`
                            : `Remediation blocked: ${remediateResult.reason || remediateResult.error || 'unknown'}`
                          }
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* Approval Queue */}
      <section>
        <SectionHeader>Approval Queue</SectionHeader>
        <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
          <ApprovalQueue pending={pending} onApprove={handleApprove} onReject={handleReject} />
        </div>
      </section>

      {/* Execution History */}
      <section>
        <SectionHeader>Execution History</SectionHeader>
        <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 overflow-x-auto">
          <ActivityTable activity={activity} />
        </div>
      </section>

      {/* Playbook Catalog (Remediation Configs) */}
      <section>
        <SectionHeader>Lab Remediation Configs</SectionHeader>
        <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 overflow-x-auto">
          <ConfigTable configs={configs} />
        </div>
      </section>
    </div>
  );
}
