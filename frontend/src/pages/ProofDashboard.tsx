import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';

/* ---- constants ---- */

const STATUS_COLORS: Record<string, string> = {
  UNTESTED: 'bg-[#333] text-[#8A8D90]',
  INJECTED: 'bg-[#4394E5] text-white',
  DETECTED: 'bg-[#F0AB00] text-black',
  REMEDIATED: 'bg-[#EC7A08] text-white',
  VERIFIED: 'bg-[#3E8635] text-white',
  PROVEN: 'bg-[#1E8635] text-white border border-[#3E8635]',
  FAILED: 'bg-[#C9190B] text-white',
};

const GATE_COLORS: Record<string, string> = {
  manual: 'bg-[#333] text-[#8A8D90]',
  low_risk_auto: 'bg-[#F0AB00] text-black',
  full_auto: 'bg-[#3E8635] text-white',
};

const STEP_ORDER = ['inject', 'detect', 'remediate', 'verify', 'cleanup'] as const;

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

function StepPipeline({ steps, queryClient, failureClass }: { steps: Record<string, any>; queryClient: any; failureClass: string }) {
  const [continuing, setContinuing] = useState(false);
  const [continueError, setContinueError] = useState<string | null>(null);

  return (
    <div className="space-y-2">
      {STEP_ORDER.map((stepName) => {
        const step = steps?.[stepName];
        const status = step?.status || (step?.success === true ? 'success' : step?.success === false ? 'failed' : null);
        const success = status === 'success' || status === 'clean' || status === 'detected';
        const warning = status === 'timeout' || status === 'skipped' || status === 'awaiting_hitl_approval';
        const notRun = !step || !status;

        const dotColor = notRun
          ? 'bg-[#555]'
          : success
            ? 'bg-[#3E8635]'
            : warning
              ? 'bg-[#F0AB00]'
              : 'bg-[#C9190B]';

        const borderColor = notRun
          ? 'border-[#2e2e2e]'
          : success
            ? 'border-[#3E8635]'
            : warning
              ? 'border-[#F0AB00]'
              : 'border-[#C9190B]';

        return (
          <div key={stepName}>
            <div className={`bg-[#1a1a1a] border ${borderColor} rounded-lg p-3`}>
              <div className="flex items-center gap-2 mb-2">
                <span className={`w-2.5 h-2.5 rounded-full ${dotColor} shrink-0`} />
                <span className="text-sm text-white font-medium capitalize">{stepName}</span>
                {!notRun && (
                  <span className={`text-xs font-bold ml-auto ${success ? 'text-[#3E8635]' : warning ? 'text-[#F0AB00]' : 'text-[#C9190B]'}`}>
                    {status}
                  </span>
                )}
              </div>

              {step?.duration_ms != null && (
                <div className="text-[10px] text-[#6A6E73] mb-2">{step.duration_ms}ms</div>
              )}

              {step?.commands && step.commands.length > 0 && (
                <div className="space-y-2">
                  {step.commands.map((cmd: any, ci: number) => (
                    <div key={ci}>
                      <div className="text-[11px] text-[#C9C9C9] font-mono bg-[#0d0d0d] rounded px-2 py-1 mb-1 truncate" title={cmd.command}>
                        {cmd.command}
                      </div>
                      {(cmd.output !== undefined && cmd.output !== null) && (
                        <pre className={`text-xs rounded px-3 py-2 font-mono overflow-x-auto max-h-40 overflow-y-auto ${
                          cmd.exit_code === 0 ? 'bg-[#0d1f0d] text-[#4ade80] border border-[#1a3a1a]' : 'bg-[#1f0d0d] text-[#f87171] border border-[#3a1a1a]'
                        }`}>{cmd.output || '(no output)'}</pre>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {step?.message && (
                <div className="text-xs text-[#8A8D90] mt-1">{step.message}</div>
              )}
              {step?.reason && (
                <div className="text-xs text-[#8A8D90] mt-1">{step.reason}</div>
              )}
              {step?.detected_class && (
                <div className="text-xs text-[#C9C9C9] mt-1">Detected: <span className="text-white font-medium">{step.detected_class}</span> via {step.source}</div>
              )}
              {step?.pending_id && (
                <div className="mt-2 space-y-2">
                  {continuing ? (
                    <div className="text-xs text-[#4ade80] font-medium animate-pulse">Running remediation → verify → cleanup... this may take 30+ seconds</div>
                  ) : (
                    <>
                      <div className="text-xs text-[#F0AB00]">HITL approval required — approve to run remediation + verify + cleanup</div>
                      <div className="flex items-center gap-3">
                        <button
                          className="bg-[#3E8635] hover:bg-[#2E7625] text-white text-xs px-4 py-1.5 rounded font-medium transition disabled:opacity-50"
                          disabled={continuing}
                          onClick={(e) => {
                            e.stopPropagation();
                            setContinuing(true);
                            setContinueError(null);
                            api.approveAction(step.pending_id)
                              .then(() => api.continueProof(failureClass))
                              .then(() => {
                                setContinuing(false);
                                queryClient.invalidateQueries({ queryKey: ['proof-matrix'] });
                              })
                              .catch((err: any) => {
                                setContinuing(false);
                                setContinueError(err.message || 'Failed');
                              });
                          }}
                        >
                          Approve + Continue
                        </button>
                        <button
                          className="bg-[#C9190B] hover:bg-[#A30000] text-white text-xs px-4 py-1.5 rounded font-medium transition"
                          onClick={(e) => {
                            e.stopPropagation();
                            api.rejectAction(step.pending_id).then(() => {
                              queryClient.invalidateQueries({ queryKey: ['proof-matrix'] });
                            });
                          }}
                        >
                          Reject
                        </button>
                      </div>
                    </>
                  )}
                  {continueError && (
                    <div className="text-xs text-[#f87171] bg-[#1f0d0d] border border-[#3a1a1a] rounded px-3 py-2">{continueError}</div>
                  )}
                </div>
              )}
              {step?.error && (
                <div className="text-xs text-[#f87171] bg-[#1f0d0d] border border-[#3a1a1a] rounded px-3 py-2 font-mono mt-1">
                  {step.error}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ---- main page ---- */

export default function ProofDashboard() {
  const queryClient = useQueryClient();
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  const matrix = useQuery({
    queryKey: ['proof-matrix'],
    queryFn: () => api.getProofMatrix(),
    refetchInterval: 10_000,
  });

  const expandedHistory = useQuery({
    queryKey: ['proof-history', expandedRow],
    queryFn: () => api.getProofHistory(expandedRow!),
    enabled: !!expandedRow,
  });

  const runProof = useMutation({
    mutationFn: (failureClass: string) => api.runProof(failureClass, 'manual'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['proof-matrix'] });
    },
  });

  const KNOWN_INJECTORS = ['pods_crashlooping', 'readiness_probe_failed', 'image_pull_backoff', 'claim_misbound', 'oom_killed', 'quota_exceeded', 'scheduling_failed'];
  const fcMap = matrix.data?.matrix?.failure_classes ?? {};
  const fromApi = Object.entries(fcMap).map(([name, data]: [string, any]) => ({ name, ...data }));
  const existingNames = new Set(fromApi.map((e: any) => e.name));
  const defaults = KNOWN_INJECTORS.filter(n => !existingNames.has(n)).map(n => ({ name: n, status: 'UNTESTED', cycles_completed: 0, consecutive_passes: 0, gate: 'manual', last_run: null }));
  const entries: any[] = [...fromApi, ...defaults];
  void matrix.data?.summary;

  const totalClasses = entries.length;
  const provenCount = entries.filter((e: any) => e.status === 'PROVEN').length;
  const verifiedCount = entries.filter((e: any) => e.status === 'VERIFIED').length;
  const untestedCount = entries.filter((e: any) => e.status === 'UNTESTED' || !e.status).length;

  if (matrix.isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8">
        <p className="text-[#6A6E73]">Loading...</p>
      </div>
    );
  }

  if (matrix.isError) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8">
        <p className="text-[#C9190B]">
          Failed to load proof matrix.{' '}
          <button onClick={() => window.location.reload()} className="underline">
            Refresh
          </button>
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-white mb-2" style={{ fontFamily: 'Red Hat Display' }}>
          Remediation Proof
        </h1>
        <p className="text-[#6A6E73]">
          Test auto-remediation against injected failures in the stargate-test namespace.
          Each failure class progresses through gates: Untested &rarr; Injected &rarr; Detected &rarr; Remediated &rarr; Verified &rarr; Proven.
        </p>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Total Failure Classes" value={totalClasses} />
        <MetricCard label="Proven" value={provenCount} />
        <MetricCard label="Verified" value={verifiedCount} />
        <MetricCard label="Untested" value={untestedCount} />
      </div>

      {/* Proof Matrix table */}
      <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
        {entries.length === 0 ? (
          <p className="text-[#6A6E73] text-sm">No failure classes configured for proof testing yet.</p>
        ) : (
          <div className="space-y-0.5">
            <div className="grid grid-cols-[1fr_100px_70px_90px_110px_90px_100px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
              <span>Failure Class</span>
              <span>Status</span>
              <span className="text-right">Cycles</span>
              <span className="text-right">Consecutive</span>
              <span>Gate</span>
              <span>Last Run</span>
              <span>Action</span>
            </div>

            {entries.map((entry: any) => {
              const fc = entry.failure_class || entry.name || '';
              const status = entry.status || 'UNTESTED';
              const isExpanded = expandedRow === fc;

              return (
                <div key={fc}>
                  <div
                    className={`grid grid-cols-[1fr_100px_70px_90px_110px_90px_100px] gap-3 items-center py-2 rounded cursor-pointer transition ${
                      isExpanded ? 'bg-[#2e2e2e]' : 'hover:bg-[#2a2a2a]'
                    }`}
                    onClick={() => setExpandedRow(isExpanded ? null : fc)}
                  >
                    <span className="text-sm text-white font-medium truncate" title={fc}>
                      <span className="text-[10px] text-[#555] mr-1">{isExpanded ? '▼' : '▶'}</span>
                      {fc}
                    </span>
                    <span>
                      <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${STATUS_COLORS[status] || STATUS_COLORS.UNTESTED}`}>
                        {status}
                      </span>
                    </span>
                    <span className="text-sm text-white text-right">{entry.cycles_completed ?? entry.cycles ?? 0}</span>
                    <span className="text-sm text-white text-right">{entry.consecutive_passes ?? entry.consecutive ?? 0}</span>
                    <span>
                      <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${GATE_COLORS[entry.gate] || GATE_COLORS.manual}`}>
                        {entry.gate ? entry.gate.replace(/_/g, ' ') : 'manual'}
                      </span>
                    </span>
                    <span className="text-xs text-[#6A6E73]">{relativeTime(entry.last_run)}</span>
                    <span>
                      <button
                        className="bg-[#EE0000] hover:bg-[#A30000] text-white text-xs px-3 py-1.5 rounded font-medium transition disabled:opacity-50"
                        disabled={runProof.isPending}
                        onClick={(e) => {
                          e.stopPropagation();
                          runProof.mutate(fc);
                        }}
                      >
                        {runProof.isPending && runProof.variables === fc ? 'Running...' : 'Run Proof'}
                      </button>
                    </span>
                  </div>

                  {/* Expanded detail */}
                  {isExpanded && (
                    <div className="bg-[#1a1a1a] border border-[#333] rounded-lg p-4 mb-2 mx-1 space-y-4">
                      <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold">
                        Last Cycle Result
                      </div>

                      {expandedHistory.isLoading && (
                        <p className="text-[#6A6E73] text-sm">Loading history...</p>
                      )}

                      {expandedHistory.isError && !entry.cycle_results?.length && (
                        <p className="text-[#6A6E73] text-sm">No cycles run yet. Click "Run Proof" to inject a failure and test remediation.</p>
                      )}

                      {(() => {
                        const cycleResults = entry.cycle_results ?? expandedHistory.data?.cycle_results ?? expandedHistory.data?.history ?? [];
                        const lastCycle = cycleResults.length > 0 ? cycleResults[cycleResults.length - 1] : null;

                        if (!lastCycle) {
                          return <p className="text-[#6A6E73] text-sm">No cycles recorded yet.</p>;
                        }

                        const steps = lastCycle.steps || lastCycle;

                        return (
                          <div className="space-y-4">
                            {/* Cycle metadata */}
                            <div className="grid grid-cols-[120px_1fr] gap-1 text-sm">
                              {lastCycle.cycle_id != null && (
                                <>
                                  <span className="text-[#6A6E73]">Cycle</span>
                                  <span className="text-white">#{lastCycle.cycle_id}</span>
                                </>
                              )}
                              {lastCycle.started_at && (
                                <>
                                  <span className="text-[#6A6E73]">Started</span>
                                  <span className="text-white">{relativeTime(lastCycle.started_at)}</span>
                                </>
                              )}
                              {lastCycle.duration_ms != null && (
                                <>
                                  <span className="text-[#6A6E73]">Duration</span>
                                  <span className="text-white">{lastCycle.duration_ms}ms</span>
                                </>
                              )}
                              {lastCycle.result && (
                                <>
                                  <span className="text-[#6A6E73]">Result</span>
                                  <span className={`font-bold ${
                                    lastCycle.result === 'PASS' || lastCycle.result === 'PROVEN' ? 'text-[#3E8635]' : 'text-[#C9190B]'
                                  }`}>{lastCycle.result}</span>
                                </>
                              )}
                            </div>

                            {/* Step pipeline */}
                            <div>
                              <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-2">Pipeline</div>
                              <StepPipeline steps={steps} queryClient={queryClient} failureClass={fc} />
                            </div>

                            {/* Previous cycles summary */}
                            {cycleResults.length > 1 && (
                              <div>
                                <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-2">
                                  Previous Cycles ({cycleResults.length - 1})
                                </div>
                                <div className="flex flex-wrap gap-1">
                                  {cycleResults.slice(0, -1).reverse().map((cycle: any, ci: number) => {
                                    const passed = cycle.result === 'PASS' || cycle.result === 'PROVEN';
                                    return (
                                      <span
                                        key={ci}
                                        className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                                          passed ? 'bg-[#3E8635] text-white' : 'bg-[#C9190B] text-white'
                                        }`}
                                        title={`Cycle ${cycle.cycle_id ?? ci + 1}: ${cycle.result ?? 'unknown'}`}
                                      >
                                        {cycle.cycle_id ?? ci + 1}: {cycle.result ?? '?'}
                                      </span>
                                    );
                                  })}
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })()}

                      {/* Fallback: if no history endpoint data, show inline last_cycle from matrix */}
                      {!expandedHistory.data && !expandedHistory.isLoading && entry.last_cycle && (
                        <div>
                          <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-2">Pipeline</div>
                          <StepPipeline steps={entry.last_cycle.steps || entry.last_cycle} queryClient={queryClient} failureClass={fc} />
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
