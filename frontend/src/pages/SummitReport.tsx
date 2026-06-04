import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useSummitReport } from '../api/hooks';
import SearchBar from '../components/SearchBar';

const STATUS_COLORS: Record<string, string> = {
  started: '#3E8635', healthy: '#3E8635', pass: '#3E8635',
  stopped: '#6A6E73',
  provisioning: '#F0AB00',
};

function statusColor(s: string): string {
  if (s.includes('failed') || s.includes('error')) return '#C9190B';
  return STATUS_COLORS[s?.toLowerCase()] ?? '#6A6E73';
}

function MetricCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
      <div className="text-2xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>{value}</div>
      <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">{label}</div>
      {sub && <div className="text-xs text-[#6A6E73] mt-0.5">{sub}</div>}
    </div>
  );
}

function SectionHeader({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h2 className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold">{children}</h2>
      {right}
    </div>
  );
}

export default function SummitReport() {
  const { data, isLoading, isError } = useSummitReport();
  const [labSearch, setLabSearch] = useState('');
  const [activeTab, setActiveTab] = useState<'overview' | 'labs' | 'stages' | 'failures' | 'provisioning'>('overview');

  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 animate-pulse space-y-6">
        <div className="h-10 bg-[#212121] rounded w-64" />
        <div className="grid grid-cols-4 gap-4">{[1,2,3,4].map(i => <div key={i} className="bg-[#212121] rounded-lg h-20" />)}</div>
      </div>
    );
  }

  if (isError || !data?.has_data) {
    return (
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8">
        <h1 className="text-3xl font-bold text-white mb-4" style={{ fontFamily: 'Red Hat Display' }}>Summit Report</h1>
        <p className="text-[#6A6E73]">No summit data available. Run <code className="text-[#73BCF7]">python3 scripts/load-summit-data.py</code> to extract data from the backup.</p>
      </div>
    );
  }

  const report = data.report;
  const subjects = data.live_subjects;
  const evals = report.evaluations || {};
  const aap = report.aap || {};
  const labs = report.labs?.labs || [];
  const stages = report.stages || [];
  const daily = report.daily || [];
  const clusters = report.clusters || [];
  const failureClasses = evals.failure_classes || {};
  const timeline = report.hourly_timeline || [];
  const clusterMetrics = report.cluster_metrics || {};
  const coverage = report.data_coverage || {};

  const filteredLabs = labSearch
    ? labs.filter((l: any) => l.lab_code.toLowerCase().includes(labSearch.toLowerCase()))
    : labs;

  const failureEntries = Object.entries(failureClasses).sort(([,a]: any, [,b]: any) => b - a);
  const maxFailure = failureEntries.length > 0 ? (failureEntries[0]![1] as number) : 1;

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'labs', label: `Labs (${labs.length})` },
    { id: 'stages', label: 'Pipeline' },
    { id: 'failures', label: `Failures (${evals.total_failure_classes || 0})` },
    { id: 'provisioning', label: `Provisioning (${subjects?.total || 0})` },
  ];

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-3 mb-2">
          <h1 className="text-3xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>Red Hat Summit 2026</h1>
          <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-[#EE0000] text-white">Event Report</span>
        </div>
        <p className="text-[#6A6E73]">May 5-8, 2026 — Platform validation retrospective</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        <MetricCard label="AAP Jobs" value={(aap.total_jobs || 0).toLocaleString()} sub={`${aap.overall_success_rate || 0}% success`} />
        <MetricCard label="AAP Failed" value={(aap.total_failed || 0).toLocaleString()} />
        <MetricCard label="Evaluations" value={evals.total || 0} />
        <MetricCard label="Eval Pass Rate" value={`${evals.pass_rate || 0}%`} />
        <MetricCard label="Labs" value={labs.length} />
        <MetricCard label="Clusters" value={clusters.length} />
        <MetricCard label="Failure Classes" value={evals.total_failure_classes || 0} />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[#2e2e2e] pb-0">
        {tabs.map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id as any)}
            className={`text-xs px-4 py-2 rounded-t transition ${activeTab === tab.id ? 'bg-[#212121] text-white border border-[#2e2e2e] border-b-[#212121] -mb-px' : 'text-[#6A6E73] hover:text-white'}`}>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Overview Tab */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          {/* Daily breakdown */}
          <section>
            <SectionHeader>Daily Breakdown</SectionHeader>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              {daily.map((d: any) => (
                <div key={d.date} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                  <div className="text-white font-bold mb-2">{new Date(d.date + 'T00:00:00').toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })}</div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div><span className="text-[#6A6E73]">Evals: </span><span className="text-white">{d.total}</span></div>
                    <div><span className="text-[#6A6E73]">Pass: </span><span className="text-[#3E8635]">{d.pass_rate}%</span></div>
                    <div><span className="text-[#6A6E73]">Passed: </span><span className="text-white">{d.passed}</span></div>
                    <div><span className="text-[#6A6E73]">Failed: </span><span className="text-[#C9190B]">{d.failed}</span></div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Hourly timeline */}
          {timeline.length > 0 && (
            <section>
              <SectionHeader>Hourly Activity</SectionHeader>
              <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                <div className="flex items-end gap-[2px] h-24">
                  {timeline.map((h: any, i: number) => {
                    const max = Math.max(...timeline.map((t: any) => t.total), 1);
                    const height = (h.total / max) * 100;
                    const failRate = h.total > 0 ? h.failed / h.total : 0;
                    return (
                      <div key={i} className="flex-1 flex flex-col justify-end" title={`${h.hour}: ${h.total} evals, ${h.failed} failed`}>
                        <div className="rounded-t" style={{ height: `${Math.max(height, 2)}%`, backgroundColor: failRate > 0.5 ? '#C9190B' : failRate > 0.2 ? '#F0AB00' : '#3E8635', minHeight: '2px' }} />
                      </div>
                    );
                  })}
                </div>
                <div className="flex justify-between text-[10px] text-[#6A6E73] mt-1">
                  <span>{timeline[0]?.hour}</span>
                  <span>{timeline[timeline.length - 1]?.hour}</span>
                </div>
              </div>
            </section>
          )}

          {/* AAP Provisioning */}
          {aap.by_day && (
            <section>
              <SectionHeader>AAP Provisioning ({aap.total_jobs?.toLocaleString()} jobs)</SectionHeader>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
                {Object.entries(aap.by_day as Record<string, any>).map(([day, stats]: [string, any]) => (
                  <div key={day} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                    <div className="text-white font-bold mb-2">{new Date(day + 'T00:00:00').toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })}</div>
                    <div className="text-2xl font-bold mb-1" style={{ color: stats.success_rate >= 80 ? '#3E8635' : stats.success_rate >= 60 ? '#F0AB00' : '#C9190B', fontFamily: 'Red Hat Display' }}>
                      {stats.success_rate}%
                    </div>
                    <div className="grid grid-cols-2 gap-1 text-xs">
                      <span className="text-[#6A6E73]">Jobs: <span className="text-white">{stats.total?.toLocaleString()}</span></span>
                      <span className="text-[#6A6E73]">Failed: <span className="text-[#C9190B]">{stats.failed?.toLocaleString()}</span></span>
                    </div>
                  </div>
                ))}
              </div>
              {aap.top_errors && Object.keys(aap.top_errors).length > 0 && (
                <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                  <div className="text-xs text-[#6A6E73] uppercase font-bold mb-2">Top Errors</div>
                  <div className="space-y-1">
                    {Object.entries(aap.top_errors as Record<string, number>).slice(0, 5).map(([err, count]) => (
                      <div key={err} className="flex items-center gap-3 text-xs">
                        <span className="text-[#C9190B] w-8 text-right shrink-0">{count}</span>
                        <span className="text-[#d2d2d2] truncate" title={err}>{err || '(empty)'}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>
          )}

          {/* Cluster performance */}
          <section>
            <SectionHeader>Cluster Performance</SectionHeader>
            <div className="space-y-1">
              {clusters.map((c: any) => (
                <Link key={c.cluster} to={`/cluster/${encodeURIComponent(c.cluster)}`} className="flex items-center gap-3 hover:bg-[#1e1e1e] rounded px-2 py-1.5 -mx-2 transition">
                  <span className="text-sm text-[#73BCF7] w-32 shrink-0">{c.cluster}</span>
                  <div className="flex-1 bg-[#333] h-4 rounded overflow-hidden">
                    <div className="h-4 rounded" style={{ width: `${c.pass_rate}%`, backgroundColor: c.pass_rate >= 80 ? '#3E8635' : c.pass_rate >= 50 ? '#F0AB00' : '#C9190B' }} />
                  </div>
                  <span className="text-xs text-white w-16 text-right">{c.pass_rate}%</span>
                  <span className="text-xs text-[#6A6E73] w-16 text-right">{c.total_evals} evals</span>
                </Link>
              ))}
            </div>
          </section>

          {/* infra01 metrics */}
          {clusterMetrics['ocpv-infra01']?.memory_utilization?.length > 0 && (
            <section>
              <SectionHeader>Infrastructure Metrics (ocpv-infra01)</SectionHeader>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {clusterMetrics['ocpv-infra01'].memory_utilization && (
                  <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                    <div className="text-xs text-[#6A6E73] uppercase font-bold mb-2">Memory Utilization</div>
                    <div className="flex items-end gap-[1px] h-16">
                      {(clusterMetrics['ocpv-infra01'].memory_utilization as any[]).map((p: any, i: number) => {
                        const val = p.value ?? 0;
                        return (
                          <div key={i} className="flex-1 flex flex-col justify-end" title={`${p.timestamp}: ${(val * 100).toFixed(1)}%`}>
                            <div className="rounded-t" style={{ height: `${val * 100}%`, backgroundColor: val > 0.8 ? '#C9190B' : val > 0.6 ? '#F0AB00' : '#3E8635', minHeight: '1px' }} />
                          </div>
                        );
                      })}
                    </div>
                    <div className="flex justify-between text-[10px] text-[#6A6E73] mt-1"><span>May 5</span><span>May 8</span></div>
                  </div>
                )}
                {clusterMetrics['ocpv-infra01'].pod_restarts && (
                  <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                    <div className="text-xs text-[#6A6E73] uppercase font-bold mb-2">Pod Restarts / Hour</div>
                    <div className="flex items-end gap-[1px] h-16">
                      {(clusterMetrics['ocpv-infra01'].pod_restarts as any[]).map((p: any, i: number) => {
                        const val = p.value ?? 0;
                        const max = Math.max(...(clusterMetrics['ocpv-infra01'].pod_restarts as any[]).map((x: any) => x.value ?? 0), 1);
                        return (
                          <div key={i} className="flex-1 flex flex-col justify-end" title={`${p.timestamp}: ${val.toFixed(1)} restarts`}>
                            <div className="rounded-t" style={{ height: `${(val / max) * 100}%`, backgroundColor: val > 10 ? '#C9190B' : val > 3 ? '#F0AB00' : '#3E8635', minHeight: '1px' }} />
                          </div>
                        );
                      })}
                    </div>
                    <div className="flex justify-between text-[10px] text-[#6A6E73] mt-1"><span>May 5</span><span>May 8</span></div>
                  </div>
                )}
              </div>
            </section>
          )}

          {/* Data coverage */}
          {coverage && (
            <section>
              <SectionHeader>Data Coverage</SectionHeader>
              <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 text-xs space-y-2">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#3E8635]" />
                  <span className="text-[#d2d2d2]">Evaluations: {coverage.evaluations?.days?.join(', ') || 'none'} — {coverage.evaluations?.note || ''}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#3E8635]" />
                  <span className="text-[#d2d2d2]">Cluster metrics (infra01): May 5-8 — memory, pod restarts, node count (hourly)</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#F0AB00]" />
                  <span className="text-[#d2d2d2]">Lab cluster metrics (ocpv05-09): Limited — only keycloak/gitops metrics retained</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#F0AB00]" />
                  <span className="text-[#d2d2d2]">Babylon subjects: {subjects?.total || 0} live summit subjects — created post-summit (May 25+), not from event week</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#6A6E73]" />
                  <span className="text-[#d2d2d2]">AAP job history: Not yet queried — 30-day retention may still have data</span>
                </div>
              </div>
            </section>
          )}
        </div>
      )}

      {/* Labs Tab */}
      {activeTab === 'labs' && (
        <div className="space-y-4">
          <SearchBar placeholder="Search labs..." value={labSearch} onChange={setLabSearch} className="w-72" />
          <div className="space-y-0.5">
            <div className="grid grid-cols-[1fr_80px_80px_80px_80px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
              <span>Lab</span><span className="text-right">Evals</span><span className="text-right">Passed</span><span className="text-right">Failed</span><span className="text-right">Pass Rate</span>
            </div>
            {filteredLabs.map((lab: any) => (
              <Link key={lab.lab_code} to={`/lab/${encodeURIComponent(lab.lab_code)}`}
                className="grid grid-cols-[1fr_80px_80px_80px_80px] gap-3 items-center py-1.5 hover:bg-[#1e1e1e] rounded transition">
                <span className="text-sm text-[#73BCF7] truncate">{lab.lab_code}</span>
                <span className="text-sm text-white text-right">{lab.total_evals}</span>
                <span className="text-sm text-[#3E8635] text-right">{lab.passed}</span>
                <span className={`text-sm text-right ${lab.failed > 0 ? 'text-[#C9190B] font-bold' : 'text-[#6A6E73]'}`}>{lab.failed}</span>
                <span className="text-sm text-right" style={{ color: lab.pass_rate >= 80 ? '#3E8635' : lab.pass_rate >= 50 ? '#F0AB00' : '#C9190B' }}>{lab.pass_rate}%</span>
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* Stages Tab */}
      {activeTab === 'stages' && (
        <div className="space-y-4">
          <div className="space-y-2">
            {stages.map((s: any) => (
              <div key={s.stage_id} className="flex items-center gap-3">
                <span className="text-xs text-[#6A6E73] w-40 truncate shrink-0">{s.stage_id}</span>
                <div className="flex-1 bg-[#333] h-5 rounded overflow-hidden flex">
                  <div style={{ width: `${s.pass_rate}%`, backgroundColor: '#3E8635' }} className="h-5" />
                  <div style={{ width: `${100 - s.pass_rate}%`, backgroundColor: '#C9190B' }} className="h-5" />
                </div>
                <span className="text-xs text-white w-12 text-right">{s.pass_rate}%</span>
                <span className="text-xs text-[#6A6E73] w-20 text-right">{s.failed} / {s.total}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Failures Tab */}
      {activeTab === 'failures' && (
        <div className="space-y-2">
          {failureEntries.map(([cls, count]) => (
            <Link key={cls} to={`/failures?selected=${encodeURIComponent(cls)}`} className="flex items-center gap-3 hover:bg-[#1e1e1e] rounded px-1 -mx-1 transition">
              <span className="text-xs text-[#6A6E73] w-48 truncate shrink-0">{cls}</span>
              <div className="flex-1 bg-[#333] h-4 rounded overflow-hidden">
                <div className="h-4 rounded" style={{ width: `${((count as number) / maxFailure) * 100}%`, backgroundColor: '#C9190B' }} />
              </div>
              <span className="text-xs text-white font-medium w-8 text-right">{count as number}</span>
            </Link>
          ))}
        </div>
      )}

      {/* Provisioning Tab */}
      {activeTab === 'provisioning' && subjects && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <MetricCard label="Total Subjects" value={subjects.total || 0} />
            <MetricCard label="Started" value={subjects.by_state?.started || 0} />
            <MetricCard label="Stopped" value={subjects.by_state?.stopped || 0} />
            <MetricCard label="Failed" value={(subjects.by_state?.['provision-failed'] || 0) + (subjects.by_state?.['destroy-failed'] || 0)} />
          </div>

          {/* State distribution */}
          {subjects.by_state && (
            <section>
              <SectionHeader>Subject States</SectionHeader>
              <div className="flex flex-wrap gap-3">
                {Object.entries(subjects.by_state as Record<string, number>).map(([state, count]) => (
                  <div key={state} className="bg-[#212121] border border-[#2e2e2e] rounded-lg px-4 py-2 flex items-center gap-2">
                    <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{ backgroundColor: statusColor(state), color: '#fff' }}>{state}</span>
                    <span className="text-white text-sm font-medium">{count}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Labs */}
          {subjects.by_lab && (
            <section>
              <SectionHeader>Summit Labs</SectionHeader>
              <div className="space-y-2">
                {Object.entries(subjects.by_lab as Record<string, any>).map(([lab, stats]: [string, any]) => (
                  <div key={lab} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-white font-medium">{lab}</span>
                      <span className="text-xs text-[#6A6E73]">{stats.total} instances</span>
                    </div>
                    <div className="flex gap-3 text-xs">
                      <span className="text-[#3E8635]">{stats.started} started</span>
                      {stats.failed > 0 && <span className="text-[#C9190B]">{stats.failed} failed</span>}
                      {stats.stopped > 0 && <span className="text-[#6A6E73]">{stats.stopped} stopped</span>}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
