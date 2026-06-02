import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useOverview, useRemediation } from '../api/hooks';
import { useTimeRange } from '../components/TimeRangeContext';
import { api } from '../api/client';
import FormattedAnalysis from '../components/FormattedAnalysis';
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
  const { range, cluster } = useTimeRange();
  const sinceMinutes = Math.round(range.ms / 60000);
  const [selectedClass, setSelectedClass] = useState<string | null>(null);
  const [selectedNs, setSelectedNs] = useState<string | null>(null);
  const [aiAnalysis, setAiAnalysis] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const remediation = useRemediation();

  const failureDetail = useQuery({
    queryKey: ['failure-detail', selectedClass, sinceMinutes, cluster],
    queryFn: () => selectedClass ? api.getFailureDetail(selectedClass, sinceMinutes, cluster || undefined) : null,
    enabled: !!selectedClass,
    refetchInterval: 30_000,
  });

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
                <div
                  key={cls}
                  className={`grid grid-cols-[200px_1fr_60px] gap-3 items-center py-1 cursor-pointer rounded px-1 ${selectedClass === cls ? 'bg-[#2e2e2e]' : 'hover:bg-[#2a2a2a]'}`}
                  onClick={() => { setSelectedClass(selectedClass === cls ? null : cls); setAiAnalysis(null); }}
                >
                  <span className="text-sm text-white truncate" title={cls}>
                    {cls}
                  </span>
                  <div className="bg-[#333] h-5 rounded overflow-hidden">
                    <div
                      className="h-5 rounded"
                      style={{
                        width: `${(count / maxCount) * 100}%`,
                        backgroundColor: selectedClass === cls ? '#EE0000' : '#C9190B',
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

      {/* Detail panel for selected failure class */}
      {selectedClass && (
        <section>
          <SectionHeader>{selectedClass}</SectionHeader>
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 space-y-4">
            <div>
              <span className="text-white font-bold text-lg">{failureClasses[selectedClass]}</span>
              <span className="text-[#6A6E73] ml-2">occurrences</span>
              {failureDetail.data?.namespaces && (
                <span className="text-[#6A6E73] ml-2">across {failureDetail.data.namespaces.length} namespaces</span>
              )}
            </div>

            {/* Namespace breakdown — click to analyze */}
            {failureDetail.data?.namespaces && failureDetail.data.namespaces.length > 0 && (
              <div>
                <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-2">Affected Namespaces — click to analyze</div>
                <div className="space-y-1">
                  {failureDetail.data.namespaces.map((ns: any) => (
                    <div key={ns.namespace}>
                      <div
                        className={`flex items-center justify-between py-1.5 px-2 rounded cursor-pointer transition ${
                          selectedNs === ns.namespace ? 'bg-[#2a2a2a] ring-1 ring-[#EE0000]' : 'hover:bg-[#252525]'
                        } ${ns.is_ecosystem ? 'border-l-2 border-l-[#EE0000]' : 'opacity-60'}`}
                        onClick={() => {
                          if (selectedNs === ns.namespace) {
                            setSelectedNs(null);
                            setAiAnalysis(null);
                          } else {
                            setSelectedNs(ns.namespace);
                            setAiAnalysis(null);
                          }
                        }}
                      >
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-white font-medium">{ns.namespace}</span>
                          {ns.is_ecosystem && <span className="text-[10px] text-[#EE0000] font-bold uppercase">eco</span>}
                          <span className="text-xs text-[#6A6E73]">on {ns.cluster}</span>
                        </div>
                        <div className="flex items-center gap-3">
                          <span className="text-sm text-white font-bold">{ns.count}</span>
                          <span className="text-xs text-[#6A6E73]">{ns.last_seen ? new Date(ns.last_seen).toLocaleString(undefined, { month: 'numeric', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '--'}</span>
                        </div>
                      </div>

                      {/* Per-namespace detail + analysis */}
                      {selectedNs === ns.namespace && (
                        <div className="bg-[#1a1a1a] border border-[#333] rounded-lg p-4 ml-3 mt-1 mb-2 space-y-3">
                          {ns.messages && ns.messages.length > 0 && (
                            <div>
                              <div className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-1">Error Messages</div>
                              {ns.messages.map((msg: string, i: number) => (
                                <div key={i} className="text-xs text-[#C9C9C9] bg-[#151515] rounded px-2 py-1 mb-1 font-mono">{msg}</div>
                              ))}
                            </div>
                          )}
                          <button
                            className="bg-[#EE0000] hover:bg-[#A30000] text-white text-sm px-4 py-2 rounded disabled:opacity-50"
                            disabled={aiLoading}
                            onClick={() => {
                              setAiLoading(true);
                              setAiAnalysis(null);
                              remediation.mutate(
                                { failure_class: selectedClass!, lab_code: ns.namespace, cluster: ns.cluster, context_type: 'lab' },
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
                            {aiLoading ? 'Analyzing...' : `Analyze ${ns.namespace}`}
                          </button>
                          {aiAnalysis && (
                            <div className="bg-[#151515] border border-[#2e2e2e] rounded p-4">
                              <FormattedAnalysis text={aiAnalysis} />
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
