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

const PIPELINE_STAGES = ['detect', 'hypothesize', 'classify', 'recommend', 'prove', 'trust'] as const;

const STAGE_SYSTEMS: Record<string, string> = {
  detect: 'Deepfield',
  hypothesize: 'GeoLux',
  classify: 'GeoLux',
  recommend: 'GeoLux',
  prove: 'StarGate',
  trust: 'StarGate',
};

function dimensionColor(dims: Record<string, string> | undefined): string {
  if (!dims) return '#333';
  const vals = Object.values(dims);
  if (vals.length === 0) return '#333';
  const greens = vals.filter(v => v === 'green').length;
  if (greens === vals.length) return '#3E8635';
  if (greens > 0) return '#F0AB00';
  // Check if there's any evidence at all (not all 'red' with no_evidence marker)
  const hasEvidence = vals.some(v => v !== 'gray');
  if (!hasEvidence) return '#333';
  return '#C9190B';
}

function DimensionTooltip({ dims }: { dims: Record<string, string> | undefined }) {
  if (!dims) return null;
  const dimColors: Record<string, string> = {
    green: '#3E8635',
    yellow: '#F0AB00',
    red: '#C9190B',
    gray: '#555',
  };
  return (
    <div className="absolute z-50 bg-[#1a1a1a] border border-[#444] rounded px-2 py-1.5 shadow-lg -translate-x-1/2 left-1/2 top-full mt-1 whitespace-nowrap">
      <div className="flex items-center gap-2">
        {Object.entries(dims).map(([key, val]) => (
          <div key={key} className="flex items-center gap-1">
            <div className="w-2 h-2 rounded-full" style={{ backgroundColor: dimColors[val] || '#555' }} />
            <span className="text-[10px] text-[#8A8D90] uppercase">{key}</span>
          </div>
        ))}
      </div>
    </div>
  );
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

function ProofTimeline({ steps, queryClient, failureClass }: { steps: Record<string, any>; queryClient: any; failureClass: string }) {
  const [continuing, setContinuing] = useState(false);
  const [continueError, setContinueError] = useState<string | null>(null);
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set());

  const toggleStep = (name: string) => {
    setExpandedSteps(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  return (
    <div className="space-y-0">
      {STEP_ORDER.map((stepName, idx) => {
        const step = steps?.[stepName];
        const status = step?.status || (step?.success === true ? 'success' : step?.success === false ? 'failed' : null);
        const success = status === 'success' || status === 'clean' || status === 'detected';
        const warning = status === 'timeout' || status === 'skipped' || status === 'awaiting_hitl_approval' || status === 'waiting';
        const notRun = !step || !status;
        const isLast = idx === STEP_ORDER.length - 1;
        const cmds: any[] = step?.commands || [];
        const isStepExpanded = expandedSteps.has(stepName);

        const dotColor = notRun
          ? 'bg-[#555]'
          : success
            ? 'bg-[#3E8635]'
            : warning
              ? 'bg-[#F0AB00]'
              : 'bg-[#C9190B]';

        const statusColor = notRun
          ? 'text-[#555]'
          : success
            ? 'text-[#3E8635]'
            : warning
              ? 'text-[#F0AB00]'
              : 'text-[#C9190B]';

        const lineColor = notRun
          ? 'bg-[#333]'
          : success
            ? 'bg-[#3E8635]'
            : warning
              ? 'bg-[#F0AB00]'
              : 'bg-[#C9190B]';

        return (
          <div key={stepName} className="flex gap-3">
            {/* Timeline line + dot */}
            <div className="flex flex-col items-center w-4 shrink-0">
              <div className={`w-3 h-3 rounded-full ${dotColor} shrink-0 mt-1`} />
              {!isLast && (
                <div className={`w-0.5 flex-1 ${notRun ? 'border-l border-dashed border-[#333]' : lineColor}`} />
              )}
            </div>
            {/* Content */}
            <div className="flex-1 pb-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-white font-medium capitalize">{stepName}</span>
                {!notRun && (
                  <span className={`text-xs font-bold ${statusColor}`}>{status}</span>
                )}
              </div>

              {step?.duration_ms != null && (
                <div className="text-[10px] text-[#6A6E73] mt-0.5">{step.duration_ms}ms</div>
              )}

              {/* Context messages */}
              {step?.detected_class && (
                <div className="text-xs text-[#C9C9C9] mt-1">Detected: <span className="text-white font-medium">{step.detected_class}</span> via {step.source}</div>
              )}
              {step?.message && (
                <div className="text-xs text-[#8A8D90] mt-1">{step.message}</div>
              )}
              {step?.reason && (
                <div className="text-xs text-[#8A8D90] mt-1">{step.reason}</div>
              )}

              {/* Waiting step hint */}
              {notRun && idx > 0 && (() => {
                const prevName = STEP_ORDER[idx - 1] as string;
                const prevStep = steps?.[prevName];
                const prevStatus = prevStep?.status || (prevStep?.success === true ? 'success' : prevStep?.success === false ? 'failed' : null);
                const prevPending = prevStep?.pending_id;
                if (prevPending) return <div className="text-xs text-[#555] mt-1">Runs after {prevName} is approved.</div>;
                if (!prevStatus) return <div className="text-xs text-[#555] mt-1">Runs after {prevName}.</div>;
                return null;
              })()}

              {/* HITL buttons */}
              {step?.pending_id && !continuing && (
                <div className="mt-2 space-y-2">
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
                </div>
              )}
              {continuing && stepName === 'remediate' && (
                <div className="text-xs text-[#4ade80] font-medium animate-pulse mt-2">Running remediation &rarr; verify &rarr; cleanup...</div>
              )}

              {/* Command toggle */}
              {cmds.length > 0 && (
                <button onClick={() => toggleStep(stepName)} className="text-xs text-[#6A6E73] hover:text-white mt-1 flex items-center gap-1">
                  <span>{isStepExpanded ? '▼' : '▶'}</span>
                  {isStepExpanded ? 'Hide' : 'Show'} commands ({cmds.length})
                </button>
              )}
              {isStepExpanded && cmds.length > 0 && (
                <div className="mt-2 space-y-1">
                  {cmds.map((cmd: any, ci: number) => (
                    <div key={ci}>
                      <div className="text-[11px] text-[#C9C9C9] font-mono bg-[#0d0d0d] rounded px-2 py-1 truncate" title={cmd.command}>
                        {cmd.command}
                      </div>
                      {cmd.output != null && (
                        <pre className={`text-xs rounded px-3 py-2 font-mono overflow-x-auto max-h-40 overflow-y-auto ${
                          cmd.exit_code === 0 ? 'bg-[#0d1f0d] text-[#4ade80] border border-[#1a3a1a]' : 'bg-[#1f0d0d] text-[#f87171] border border-[#3a1a1a]'
                        }`}>{cmd.output || '(no output)'}</pre>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Errors */}
              {continueError && stepName === 'remediate' && (
                <div className="text-xs text-[#f87171] bg-[#1f0d0d] border border-[#3a1a1a] rounded px-3 py-2 mt-1">{continueError}</div>
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

function ProofExplanation({ failureClass, result }: { failureClass: string; result: string }) {
  const hasResult = result === 'PASS' || result === 'FAIL' || result === 'PROVEN' || result === 'FAILED';
  const { data, isLoading } = useQuery({
    queryKey: ['proof-explain', failureClass],
    queryFn: () => api.getProofExplanation(failureClass),
    enabled: !!failureClass && hasResult,
    staleTime: 60000,
  });

  if (!hasResult) return null;
  if (isLoading) return <div className="text-xs text-[#6A6E73] animate-pulse mt-2">Generating explanation...</div>;
  if (!data?.explanation) return null;

  const borderColor = result === 'PASS' || result === 'PROVEN' ? '#3E8635' : '#C9190B';

  return (
    <div className="mt-3 rounded-lg p-3" style={{ backgroundColor: `${borderColor}10`, border: `1px solid ${borderColor}30` }}>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: borderColor }}>
          AI Analysis
        </span>
        {data.model && <span className="text-[10px] text-[#555]">{data.model}</span>}
      </div>
      <p className="text-xs text-[#ccc] leading-relaxed">{data.explanation}</p>
    </div>
  );
}

function PipelineRubricCell({ stage }: { stage: { status: string; system: string | null; dimensions: Record<string, string> } | undefined }) {
  const [showDims, setShowDims] = useState(false);
  const color = dimensionColor(stage?.dimensions);

  return (
    <div
      className="relative flex flex-col items-center cursor-pointer"
      onMouseEnter={() => setShowDims(true)}
      onMouseLeave={() => setShowDims(false)}
      onClick={() => setShowDims(prev => !prev)}
    >
      <div className="w-3.5 h-3.5 rounded-full" style={{ backgroundColor: color }} />
      {stage?.system && (
        <span className="text-[9px] text-[#555] mt-0.5 truncate max-w-[70px] text-center">{stage.system}</span>
      )}
      {showDims && stage?.dimensions && <DimensionTooltip dims={stage.dimensions} />}
    </div>
  );
}

function PipelineRubricMatrix() {
  const pipelineQuery = useQuery({
    queryKey: ['pipeline-matrix'],
    queryFn: () => api.getPipelineMatrix(),
    refetchInterval: 10_000,
  });

  if (pipelineQuery.isLoading) {
    return (
      <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
        <p className="text-[#6A6E73] text-sm">Loading pipeline matrix...</p>
      </div>
    );
  }

  if (pipelineQuery.isError) {
    return (
      <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
        <p className="text-[#C9190B] text-sm">Failed to load pipeline matrix.</p>
      </div>
    );
  }

  const failureClasses = pipelineQuery.data?.matrix?.failure_classes ?? {};
  const fcNames = Object.keys(failureClasses);

  if (fcNames.length === 0) {
    return null;
  }

  return (
    <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
      <div className="mb-3">
        <h2 className="text-lg font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>
          Pipeline Rubric Matrix
        </h2>
        <p className="text-xs text-[#6A6E73] mt-0.5">
          Track each failure class through the cross-system proof pipeline.
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#2e2e2e]">
              <th className="text-left text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 pr-4 min-w-[160px]">
                Failure Class
              </th>
              {PIPELINE_STAGES.map(stage => (
                <th key={stage} className="text-center pb-2 px-2 min-w-[80px]">
                  <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold">{stage}</div>
                  <div className="text-[9px] text-[#555] mt-0.5">{STAGE_SYSTEMS[stage]}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {fcNames.map(fc => {
              const fcData = failureClasses[fc];
              const stages = fcData?.stages ?? {};
              return (
                <tr key={fc} className="border-b border-[#1a1a1a] hover:bg-[#2a2a2a] transition">
                  <td className="py-2 pr-4">
                    <span className="text-sm text-white font-medium truncate block max-w-[200px]" title={fc}>
                      {fc}
                    </span>
                    {fcData?.current_stage && (
                      <span className="text-[9px] text-[#6A6E73]">at {fcData.current_stage}</span>
                    )}
                  </td>
                  {PIPELINE_STAGES.map(stage => (
                    <td key={stage} className="py-2 px-2">
                      <PipelineRubricCell stage={stages[stage]} />
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-4 mt-3 pt-2 border-t border-[#2e2e2e]">
        <span className="text-[10px] text-[#6A6E73] uppercase tracking-wider">Legend:</span>
        {[
          { color: '#3E8635', label: 'All passed' },
          { color: '#F0AB00', label: 'Partial' },
          { color: '#C9190B', label: 'Failed' },
          { color: '#333', label: 'Not started' },
        ].map(item => (
          <div key={item.label} className="flex items-center gap-1">
            <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: item.color }} />
            <span className="text-[10px] text-[#8A8D90]">{item.label}</span>
          </div>
        ))}
        <span className="text-[10px] text-[#555] ml-2">Hover for TDD/EDD/CDD/BDD detail — TDD = Structural completeness | EDD = Evidence citations | CDD = Contract conformance | BDD = Behavioral outcomes</span>
      </div>
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
    refetchInterval: 5_000,
  });

  const expandedHistory = useQuery({
    queryKey: ['proof-history', expandedRow],
    queryFn: () => api.getProofHistory(expandedRow!),
    enabled: !!expandedRow,
    refetchInterval: expandedRow ? 5_000 : false,
  });

  const [runError, setRunError] = useState<string | null>(null);
  const runProof = useMutation({
    mutationFn: (failureClass: string) => api.runProof(failureClass, 'manual'),
    onSuccess: () => {
      setRunError(null);
      queryClient.invalidateQueries({ queryKey: ['proof-matrix'] });
    },
    onError: (err: any) => {
      setRunError(err.message || 'Failed to run proof');
    },
  });

  const KNOWN_INJECTORS = [
    'pods_crashlooping', 'readiness_probe_failed', 'image_pull_backoff', 'claim_misbound',
    'oom_killed', 'quota_exceeded', 'scheduling_failed', 'backoff_limit_exceeded',
    'image_pull_secret_missing', 'deprecated_api', 'pvc_binding_failed',
    'sync_failed', 'pod_pending', 'volume_mount_failed', 'invalid_configuration',
    'datasource_unrecognized', 'volume_attach_failed', 'volume_resize_failed',
    'resolution_failed', 'hpa_metric_failure',
  ];
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

      {runError && (
        <div className="bg-[#1f0d0d] border border-[#3a1a1a] rounded-lg p-3 text-sm text-[#f87171]">
          {runError}
          {runError.includes('expired') && (
            <button onClick={() => window.location.reload()} className="ml-2 underline text-white">Refresh</button>
          )}
        </div>
      )}

      {/* Pipeline Rubric Matrix */}
      <PipelineRubricMatrix />

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
                              <ProofTimeline steps={steps} queryClient={queryClient} failureClass={fc} />
                              <ProofExplanation failureClass={fc} result={lastCycle.result || status} />
                            </div>

                            {/* Previous cycles summary */}
                            {cycleResults.length > 1 && (
                              <div>
                                <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-2">
                                  Previous Cycles ({cycleResults.length - 1})
                                </div>
                                <div className="flex flex-wrap gap-1">
                                  {cycleResults.slice(0, -1).reverse().map((cycle: any, ci: number) => {
                                    const passed = cycle.success === true;
                                    const label = passed ? 'PASS' : cycle.success === false ? 'FAIL' : '...';
                                    return (
                                      <span
                                        key={ci}
                                        className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${
                                          passed ? 'bg-[#3E8635] text-white' : 'bg-[#C9190B] text-white'
                                        }`}
                                        title={`Cycle ${ci + 1}: ${label}`}
                                      >
                                        {ci + 1}: {label}
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
                          <ProofTimeline steps={entry.last_cycle.steps || entry.last_cycle} queryClient={queryClient} failureClass={fc} />
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
