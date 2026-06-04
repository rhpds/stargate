import { useParams, Link } from 'react-router-dom';
import { useState } from 'react';
import { useLabDetail } from '../api/hooks';
import type { LabDetail as LabDetailType, EvaluationHistory } from '../api/types';

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

function pct(n: number, d: number): string {
  if (d === 0) return '--';
  return `${Math.round((n / d) * 100)}%`;
}

const STATUS_COLORS: Record<string, string> = {
  pass: '#3E8635', healthy: '#3E8635', active: '#3E8635', started: '#3E8635',
  fail: '#C9190B', critical: '#C9190B',
  warn: '#F0AB00', warning: '#F0AB00', degraded: '#F0AB00',
};

function statusColor(status: string): string {
  if (status.includes('failed') || status.includes('error')) return '#C9190B';
  return STATUS_COLORS[status?.toLowerCase()] ?? '#6A6E73';
}

/* ---- sub-components ---- */

function MetricCard({ label, value, onClick }: { label: string; value: string | number; onClick?: () => void }) {
  return (
    <div className={`bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 ${onClick ? 'cursor-pointer hover:border-[#555] transition' : ''}`} onClick={onClick}>
      <div className="text-2xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>{value}</div>
      <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">{label}</div>
    </div>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return <h2 className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">{children}</h2>;
}

function StageRollup({ history }: { history: EvaluationHistory[] }) {
  const byStage: Record<string, { pass: number; fail: number; warn: number; total: number }> = {};
  for (const ev of history) {
    if (!byStage[ev.stage_id]) byStage[ev.stage_id] = { pass: 0, fail: 0, warn: 0, total: 0 };
    const s = byStage[ev.stage_id]!;
    s.total++;
    if (ev.outcome === 'pass') s.pass++;
    else if (ev.outcome === 'fail') s.fail++;
    else s.warn++;
  }
  const stages = Object.entries(byStage);
  if (stages.length === 0) return null;
  return (
    <div className="flex gap-1 overflow-x-auto pb-1">
      {stages.map(([stage, counts]) => {
        const rate = counts.total > 0 ? Math.round((counts.pass / counts.total) * 100) : 0;
        const bg = rate >= 80 ? '#3E8635' : rate >= 50 ? '#F0AB00' : '#C9190B';
        return (
          <div key={stage} className="shrink-0 bg-[#212121] border border-[#2e2e2e] rounded px-3 py-2 text-center min-w-[100px]">
            <div className="text-[10px] text-[#6A6E73] uppercase truncate mb-1" title={stage}>{stage}</div>
            <div className="text-sm font-bold" style={{ color: bg }}>{rate}%</div>
            <div className="text-[10px] text-[#6A6E73]">{counts.pass}/{counts.total}</div>
          </div>
        );
      })}
    </div>
  );
}

function EvalTimeline({ history, expandedId, setExpandedId }: { history: EvaluationHistory[]; expandedId: string | null; setExpandedId: (id: string | null) => void }) {
  if (history.length === 0) return <p className="text-[#6A6E73] text-sm">No evaluation history.</p>;
  return (
    <div className="space-y-1">
      <div className="grid grid-cols-[140px_1fr_80px_1fr] gap-2 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-1 border-b border-[#2e2e2e]">
        <span>Timestamp</span><span>Stage</span><span>Outcome</span><span>Failure Class</span>
      </div>
      {history.map((ev, i) => {
        const rowId = `${ev.run_id}-${ev.stage_id}-${i}`;
        const isExpanded = expandedId === rowId;
        return (
          <div key={rowId}>
            <div
              onClick={() => setExpandedId(isExpanded ? null : rowId)}
              className="grid grid-cols-[140px_1fr_80px_1fr] gap-2 items-center text-sm py-1.5 border-b border-[#1a1a1a] cursor-pointer hover:bg-[#1e1e1e] rounded transition"
            >
              <span className="text-[#6A6E73] text-xs">{ev.evaluated_at ? relativeTime(ev.evaluated_at) : '--'}</span>
              <span className="text-white text-xs truncate">{ev.stage_id}</span>
              <span><span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: statusColor(ev.outcome), color: '#fff' }}>{ev.outcome}</span></span>
              {ev.failure_class ? (
                <Link to={`/failures?selected=${encodeURIComponent(ev.failure_class)}`} onClick={(e) => e.stopPropagation()} className="text-xs text-[#73BCF7] hover:underline truncate">{ev.failure_class}</Link>
              ) : (
                <span className="text-[#6A6E73] text-xs">--</span>
              )}
            </div>
            {isExpanded && (
              <div className="bg-[#1a1a1a] rounded p-3 mb-1 text-xs space-y-1">
                {ev.message && <div><span className="text-[#6A6E73]">Message: </span><span className="text-[#d2d2d2]">{ev.message}</span></div>}
                <div><span className="text-[#6A6E73]">Run: </span><span className="text-[#d2d2d2]">{ev.run_id}</span></div>
                {ev.cluster_name && <div><span className="text-[#6A6E73]">Cluster: </span><Link to={`/cluster/${encodeURIComponent(ev.cluster_name)}`} className="text-[#73BCF7] hover:underline">{ev.cluster_name}</Link></div>}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function FailureDistribution({ failures }: { failures: Record<string, number> }) {
  const entries = Object.entries(failures).sort(([, a], [, b]) => b - a);
  if (entries.length === 0) return <p className="text-[#6A6E73] text-sm">No failure classes recorded.</p>;
  const maxCount = entries[0]![1];
  return (
    <div className="space-y-2">
      {entries.map(([cls, count]) => (
        <Link key={cls} to={`/failures?selected=${encodeURIComponent(cls)}`} className="flex items-center gap-3 hover:bg-[#1e1e1e] rounded px-1 -mx-1 transition">
          <span className="text-xs text-[#6A6E73] w-40 truncate shrink-0" title={cls}>{cls}</span>
          <div className="flex-1 bg-[#333] h-4 rounded overflow-hidden">
            <div className="h-4 rounded" style={{ width: `${(count / maxCount) * 100}%`, backgroundColor: '#C9190B' }} />
          </div>
          <span className="text-xs text-white font-medium w-8 text-right">{count}</span>
        </Link>
      ))}
    </div>
  );
}

/* ---- main page ---- */

export default function LabDetail() {
  const { code } = useParams<{ code: string }>();
  const [expandedEval, setExpandedEval] = useState<string | null>(null);
  const labDetail = useLabDetail(code ?? '');

  if (labDetail.isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 animate-pulse space-y-6">
        <div className="h-8 bg-[#212121] rounded w-64" />
        <div className="grid grid-cols-4 gap-4">{[1,2,3,4].map(i => <div key={i} className="bg-[#212121] rounded-lg h-20" />)}</div>
      </div>
    );
  }

  if (labDetail.isError) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8">
        <Link to="/" className="text-[#73BCF7] text-sm hover:underline">Back to Health</Link>
        <p className="text-[#C9190B] mt-4">Failed to load lab detail.</p>
      </div>
    );
  }

  const lab = labDetail.data as LabDetailType;
  const labName = lab.labagator?.title || lab.lab_code;
  const labSt = lab.labagator?.status ?? 'unknown';

  const evalCount = lab.stargate.evaluation_count;
  const history = lab.stargate.history ?? [];
  const failures = lab.stargate.failure_classes ?? {};

  const passCount = history.filter((e) => e.outcome === 'pass').length;
  const passRate = pct(passCount, history.length);
  const failureEntries = Object.entries(failures).sort(([, a], [, b]) => b - a);
  const topFailure = failureEntries.length > 0 ? failureEntries[0]![0] : '--';
  const lastEval = history.length > 0 ? history[0]!.evaluated_at : null;

  const provisioning = (lab as any).provisioning;
  const constraints = (lab as any).constraint_violations;
  const instances = provisioning?.instances ?? [];
  const instanceSummary = provisioning?.instance_summary;
  const linkedPools = provisioning?.pools ?? [];
  const launchpadSessions = provisioning?.launchpad_sessions ?? [];

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div>
        <Link to="/" className="text-[#73BCF7] text-sm hover:underline">Health</Link>
        <span className="text-[#6A6E73] text-sm mx-2">/</span>
        <span className="text-[#6A6E73] text-sm">Lab</span>
        <div className="flex items-center gap-3 mt-2">
          <h1 className="text-2xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>{labName}</h1>
          <span className="text-xs font-semibold px-2.5 py-1 rounded-full" style={{ backgroundColor: statusColor(labSt), color: '#fff' }}>{labSt}</span>
        </div>
        <p className="text-[#6A6E73] mt-1">{lab.lab_code}</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Total Evals" value={evalCount} />
        <MetricCard label="Pass Rate" value={passRate} onClick={() => {}} />
        <MetricCard label="Top Failure" value={topFailure} />
        <MetricCard label="Last Evaluated" value={relativeTime(lastEval)} />
      </div>

      {/* Stage Rollup */}
      {history.length > 0 && (
        <section>
          <SectionHeader>Pipeline Stages</SectionHeader>
          <StageRollup history={history} />
        </section>
      )}

      {/* Provisioning */}
      {instances.length > 0 && (
        <section>
          <SectionHeader>Provisioning ({instanceSummary?.total ?? instances.length} instances)</SectionHeader>
          {instanceSummary && (
            <div className="flex flex-wrap gap-2 mb-3">
              {Object.entries(instanceSummary.by_state as Record<string, number>).map(([state, count]) => (
                <div key={state} className="flex items-center gap-1 bg-[#212121] border border-[#2e2e2e] rounded px-2 py-1">
                  <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full" style={{ backgroundColor: statusColor(state), color: '#fff' }}>{state}</span>
                  <span className="text-xs text-white">{count}</span>
                </div>
              ))}
            </div>
          )}
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 space-y-1">
            {instances.slice(0, 20).map((inst: any) => (
              <div key={inst.anarchy_name} className="flex items-center gap-3 text-sm py-1">
                <span className="text-white truncate flex-1" title={inst.anarchy_name}>{inst.anarchy_name}</span>
                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full shrink-0" style={{ backgroundColor: statusColor(inst.state), color: '#fff' }}>{inst.state}</span>
                <span className="text-xs text-[#6A6E73] shrink-0">{inst.namespace}</span>
                {inst.console_url && <a href={inst.console_url} target="_blank" rel="noopener noreferrer" className="text-xs text-[#73BCF7] hover:underline shrink-0">Console</a>}
              </div>
            ))}
            {instances.length > 20 && <p className="text-xs text-[#6A6E73]">+ {instances.length - 20} more</p>}
          </div>
        </section>
      )}

      {/* Linked Pools */}
      {linkedPools.length > 0 && (
        <section>
          <SectionHeader>Linked Pools</SectionHeader>
          <div className="flex flex-wrap gap-3">
            {linkedPools.map((pool: any) => (
              <Link key={pool.name} to={`/pool/${encodeURIComponent(pool.name)}`} className="bg-[#212121] border border-[#2e2e2e] rounded-lg px-4 py-3 flex items-center gap-3 cursor-pointer hover:border-[#555] transition">
                <span className="text-white text-sm">{pool.name}</span>
                <span className="text-xs text-[#6A6E73]">{pool.available} avail / {pool.min} min</span>
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* Launchpad Sessions */}
      {launchpadSessions.length > 0 && (
        <section>
          <SectionHeader>Launchpad Sessions ({launchpadSessions.length})</SectionHeader>
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 space-y-1">
            {launchpadSessions.map((s: any) => (
              <div key={s.session_id} className="flex items-center gap-3 text-sm py-1">
                <span className="text-white text-xs">{s.session_id}</span>
                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full" style={{ backgroundColor: statusColor(s.status), color: '#fff' }}>{s.status}</span>
                <span className="text-xs text-[#6A6E73]">{s.namespace}</span>
                <span className="text-xs text-[#6A6E73]">{s.session_date}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Constraint Violations */}
      {constraints && constraints.length > 0 && (
        <section>
          <SectionHeader>Constraint Violations ({constraints.length})</SectionHeader>
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 space-y-2">
            {constraints.map((cv: any, i: number) => (
              <div key={i} className="flex items-center gap-3 text-sm">
                <span className="text-[#F0AB00] text-xs shrink-0">!</span>
                <span className="text-white text-xs">{cv.constraint || cv.name}</span>
                {cv.actual !== undefined && <span className="text-xs text-[#6A6E73]">actual: {String(cv.actual)}</span>}
                {cv.expected !== undefined && <span className="text-xs text-[#6A6E73]">expected: {String(cv.expected)}</span>}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Evaluation history */}
      <section>
        <SectionHeader>Evaluation History</SectionHeader>
        <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 overflow-x-auto">
          <EvalTimeline history={history} expandedId={expandedEval} setExpandedId={setExpandedEval} />
        </div>
      </section>

      {/* Failure distribution */}
      <section>
        <SectionHeader>Failure Distribution</SectionHeader>
        <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
          <FailureDistribution failures={failures} />
        </div>
      </section>
    </div>
  );
}
