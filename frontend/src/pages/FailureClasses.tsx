import { useOverview } from '../api/hooks';
import type { OverviewData } from '../api/types';

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

/* ---- main page ---- */

export default function FailureClasses() {
  const overview = useOverview();

  if (overview.isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8">
        <p className="text-[#6A6E73]">Loading...</p>
      </div>
    );
  }

  if (overview.isError) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8">
        <p className="text-[#C9190B]">Failed to load failure class data.</p>
      </div>
    );
  }

  const ov = overview.data as OverviewData;
  const failureClasses = ov.errors.failure_classes ?? {};
  const entries = Object.entries(failureClasses).sort(([, a], [, b]) => b - a);
  const totalClasses = entries.length;
  const totalFailures = entries.reduce((sum, [, count]) => sum + count, 0);
  const maxCount = entries.length > 0 ? entries[0]![1] : 1;

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-white mb-2" style={{ fontFamily: 'Red Hat Display' }}>
          Failure Classes
        </h1>
        <p className="text-[#6A6E73]">Classification patterns across the ecosystem</p>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard label="Total Classes" value={totalClasses} />
        <MetricCard label="Total Failures" value={totalFailures} />
        <MetricCard label="Top Class" value={entries.length > 0 ? entries[0]![0] : '--'} />
        <MetricCard label="Systemic Failures" value={ov.errors.systemic} />
      </div>

      {/* Sorted table */}
      <section>
        <SectionHeader>Failure Class Distribution</SectionHeader>
        <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
          {entries.length === 0 ? (
            <p className="text-[#6A6E73] text-sm">No failure classes recorded.</p>
          ) : (
            <div className="space-y-2">
              {/* Table header */}
              <div className="grid grid-cols-[200px_1fr_60px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-1 border-b border-[#2e2e2e]">
                <span>Class</span>
                <span>Distribution</span>
                <span className="text-right">Count</span>
              </div>
              {/* Table rows */}
              {entries.map(([cls, count]) => (
                <div key={cls} className="grid grid-cols-[200px_1fr_60px] gap-3 items-center py-1">
                  <span className="text-sm text-white truncate" title={cls}>
                    {cls}
                  </span>
                  <div className="bg-[#333] h-5 rounded overflow-hidden">
                    <div
                      className="h-5 rounded"
                      style={{
                        width: `${(count / maxCount) * 100}%`,
                        backgroundColor: '#C9190B',
                      }}
                    />
                  </div>
                  <span className="text-sm text-white font-medium text-right">{count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
