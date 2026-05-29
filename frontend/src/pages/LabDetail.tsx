import { useParams, NavLink } from 'react-router-dom';
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
  pass: '#3E8635',
  healthy: '#3E8635',
  active: '#3E8635',
  fail: '#C9190B',
  critical: '#C9190B',
  warn: '#F0AB00',
  warning: '#F0AB00',
  degraded: '#F0AB00',
};

function statusColor(status: string): string {
  return STATUS_COLORS[status?.toLowerCase()] ?? '#6A6E73';
}

function outcomeBadge(outcome: string) {
  const color = statusColor(outcome);
  return (
    <span
      className="text-xs font-semibold px-2 py-0.5 rounded-full"
      style={{ backgroundColor: color, color: '#fff' }}
    >
      {outcome}
    </span>
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

function SectionHeader({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">{children}</h2>
  );
}

function EvalTimeline({ history }: { history: EvaluationHistory[] }) {
  if (history.length === 0) {
    return <p className="text-[#6A6E73] text-sm">No evaluation history.</p>;
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-[140px_1fr_80px_1fr] gap-2 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-1 border-b border-[#2e2e2e]">
        <span>Timestamp</span>
        <span>Stage</span>
        <span>Outcome</span>
        <span>Failure Class</span>
      </div>
      {history.map((ev, i) => (
        <div
          key={ev.run_id + ev.stage_id + i}
          className="grid grid-cols-[140px_1fr_80px_1fr] gap-2 items-center text-sm py-1.5 border-b border-[#1a1a1a]"
        >
          <span className="text-[#6A6E73] text-xs">
            {ev.evaluated_at ? relativeTime(ev.evaluated_at) : '--'}
          </span>
          <span className="text-white text-xs truncate">{ev.stage_id}</span>
          <span>{outcomeBadge(ev.outcome)}</span>
          <span className="text-[#6A6E73] text-xs truncate">
            {ev.failure_class ?? '--'}
          </span>
        </div>
      ))}
    </div>
  );
}

function FailureDistribution({ failures }: { failures: Record<string, number> }) {
  const entries = Object.entries(failures).sort(([, a], [, b]) => b - a);
  if (entries.length === 0) {
    return <p className="text-[#6A6E73] text-sm">No failure classes recorded.</p>;
  }
  const maxCount = entries[0]![1];

  return (
    <div className="space-y-2">
      {entries.map(([cls, count]) => (
        <div key={cls} className="flex items-center gap-3">
          <span className="text-xs text-[#6A6E73] w-40 truncate shrink-0" title={cls}>
            {cls}
          </span>
          <div className="flex-1 bg-[#333] h-4 rounded overflow-hidden">
            <div
              className="h-4 rounded"
              style={{
                width: `${(count / maxCount) * 100}%`,
                backgroundColor: '#C9190B',
              }}
            />
          </div>
          <span className="text-xs text-white font-medium w-8 text-right">{count}</span>
        </div>
      ))}
    </div>
  );
}

/* ---- main page ---- */

export default function LabDetail() {
  const { code } = useParams<{ code: string }>();
  const labDetail = useLabDetail(code ?? '');

  if (labDetail.isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8">
        <p className="text-[#6A6E73]">Loading...</p>
      </div>
    );
  }

  if (labDetail.isError) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8">
        <p className="text-[#C9190B]">Failed to load lab detail.</p>
      </div>
    );
  }

  const lab = labDetail.data as LabDetailType;
  const labName = lab.labagator?.title || lab.lab_code;
  const labStatus = lab.labagator?.status ?? 'unknown';

  const evalCount = lab.stargate.evaluation_count;
  const history = lab.stargate.history ?? [];
  const failures = lab.stargate.failure_classes ?? {};

  const passCount = history.filter((e) => e.outcome === 'pass').length;
  const passRate = pct(passCount, history.length);

  const failureEntries = Object.entries(failures).sort(([, a], [, b]) => b - a);
  const topFailure = failureEntries.length > 0 ? failureEntries[0]![0] : '--';

  const lastEval = history.length > 0 ? history[0]!.evaluated_at : null;

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      {/* Back link + header */}
      <div>
        <NavLink to="/" className="text-sm text-[#6A6E73] hover:text-white transition mb-2 inline-block">
          &larr; Back to Ecosystem
        </NavLink>
        <div className="flex items-center gap-3 mt-1">
          <h1 className="text-3xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>
            {labName}
          </h1>
          <span
            className="text-xs font-semibold px-2.5 py-1 rounded-full"
            style={{ backgroundColor: statusColor(labStatus), color: '#fff' }}
          >
            {labStatus}
          </span>
        </div>
        <p className="text-[#6A6E73] mt-1">Lab: {lab.lab_code}</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Total Evals" value={evalCount} />
        <MetricCard label="Pass Rate" value={passRate} />
        <MetricCard label="Top Failure" value={topFailure} />
        <MetricCard label="Last Evaluated" value={relativeTime(lastEval)} />
      </div>

      {/* Evaluation history */}
      <section>
        <SectionHeader>Evaluation History</SectionHeader>
        <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 overflow-x-auto">
          <EvalTimeline history={history} />
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
