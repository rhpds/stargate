import { useState } from 'react';
import { useSummitReport } from '../api/hooks';
import SearchBar from '../components/SearchBar';

function MetricCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
      <div className="text-2xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>{value}</div>
      <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">{label}</div>
      {sub && <div className="text-xs text-[#6A6E73] mt-0.5">{sub}</div>}
    </div>
  );
}

function SectionHeader({ children }: { children: React.ReactNode }) {
  return <h2 className="text-xs text-[#6A6E73] uppercase tracking-wider font-bold mb-3">{children}</h2>;
}

export default function SummitReport() {
  const { data, isLoading, isError } = useSummitReport();
  const [labSearch, setLabSearch] = useState('');
  const [activeTab, setActiveTab] = useState<'overview' | 'labs' | 'failures' | 'reclamation'>('overview');

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
        <p className="text-[#6A6E73]">No summit data available.</p>
      </div>
    );
  }

  const report = data.report;
  const reclamation = data.reclamation || {};
  const labagator = data.labagator || {};
  const aap = report.aap || {};
  const failureByType = aap.failure_breakdown?.by_type || {};
  const topFailingLabs = aap.top_failing_labs || {};
  const coverage = report.data_coverage || {};

  const labagatorEntries = Object.entries(labagator.labs_by_code || {} as Record<string, any>);
  const filteredLabs = labSearch
    ? labagatorEntries.filter(([code]) => code.toLowerCase().includes(labSearch.toLowerCase()) || (labagator.labs_by_code?.[code]?.title || '').toLowerCase().includes(labSearch.toLowerCase()))
    : labagatorEntries;

  const failureEntries = Object.entries(failureByType).sort(([,a]: any, [,b]: any) => (b as number) - (a as number));
  const maxFailure = failureEntries.length > 0 ? (failureEntries[0]![1] as number) : 1;

  const tabs = [
    { id: 'overview', label: 'Overview' },
    { id: 'labs', label: `Labs (${labagator.total_labs || 0})` },
    { id: 'failures', label: `Failures (${aap.total_failed || 0})` },
    ...(reclamation.total_destroy_jobs ? [{ id: 'reclamation', label: `Reclamation (${reclamation.never_reclaimed || 0} orphaned)` }] : []),
  ];

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-8 space-y-6">
      <div>
        <div className="flex items-center gap-3 mb-2">
          <h1 className="text-3xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>Red Hat Summit 2026</h1>
          <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-[#EE0000] text-white">Event Report</span>
        </div>
        <p className="text-[#6A6E73]">{report.dates ? `${report.dates.start} to ${report.dates.end}` : 'May 11-14, 2026'} — Platform validation retrospective</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        <MetricCard label="AAP Jobs" value={(aap.total_jobs || 0).toLocaleString()} sub={`${aap.overall_success_rate || 0}% success`} />
        <MetricCard label="AAP Failed" value={(aap.total_failed || 0).toLocaleString()} />
        <MetricCard label="Success Rate" value={`${aap.overall_success_rate || 0}%`} />
        <MetricCard label="Labs" value={labagator.total_labs || 0} sub="from Labagator" />
        <MetricCard label="Destroy Failures" value={(failureByType.destroy || 0).toLocaleString()} />
        <MetricCard label="Provision Failures" value={(failureByType.provision || 0).toLocaleString()} />
        <MetricCard label="Sessions" value={labagator.total_sessions || 0} />
      </div>

      <div className="flex gap-1 border-b border-[#2e2e2e] pb-0">
        {tabs.map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id as any)}
            className={`text-xs px-4 py-2 rounded-t transition ${activeTab === tab.id ? 'bg-[#212121] text-white border border-[#2e2e2e] border-b-[#212121] -mb-px' : 'text-[#6A6E73] hover:text-white'}`}>
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'overview' && (
        <div className="space-y-6">
          {aap.by_day && (
            <section>
              <SectionHeader>AAP Jobs by Day ({aap.total_jobs?.toLocaleString()} total)</SectionHeader>
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

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {aap.top_playbooks && Object.keys(aap.top_playbooks).length > 0 && (
                  <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                    <div className="text-xs text-[#6A6E73] uppercase font-bold mb-2">Failing Playbooks</div>
                    <div className="space-y-1">
                      {Object.entries(aap.top_playbooks as Record<string, number>).map(([pb, count]) => (
                        <div key={pb} className="flex items-center gap-3 text-xs">
                          <span className="text-[#C9190B] w-8 text-right shrink-0">{count as number}</span>
                          <span className="text-[#d2d2d2] truncate" title={pb}>{pb}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {aap.failure_breakdown && (
                  <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                    <div className="text-xs text-[#6A6E73] uppercase font-bold mb-2">Failure Breakdown</div>
                    <div className="space-y-1 text-xs">
                      {Object.entries(failureByType).map(([t, c]) => (
                        <div key={t} className="flex items-center justify-between">
                          <span className={t === 'destroy' ? 'text-[#C9190B]' : t === 'provision' ? 'text-[#F0AB00]' : 'text-[#d2d2d2]'}>{t}</span>
                          <span className="text-white font-bold">{(c as number).toLocaleString()}</span>
                        </div>
                      ))}
                      <div className="border-t border-[#333] pt-1 mt-1 flex items-center justify-between">
                        <span className="text-[#6A6E73]">Avg duration</span>
                        <span className="text-white">{aap.failure_breakdown.avg_duration_minutes}min</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-[#6A6E73]">Max duration</span>
                        <span className="text-white">{aap.failure_breakdown.max_duration_minutes}min</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {Object.keys(topFailingLabs).length > 0 && (
                <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 mt-4">
                  <div className="text-xs text-[#6A6E73] uppercase font-bold mb-2">Top Failing Labs (AAP)</div>
                  <div className="space-y-1">
                    {Object.entries(topFailingLabs as Record<string, any>).slice(0, 10).map(([lab, stats]: [string, any]) => (
                      <div key={lab} className="flex items-center gap-3 text-xs">
                        <span className="text-[#C9190B] w-8 text-right shrink-0">{stats.failed}</span>
                        <span className="text-white w-40 truncate shrink-0">{lab}</span>
                        {stats.provision_failures > 0 && <span className="text-[#F0AB00]">{stats.provision_failures} provision</span>}
                        {stats.destroy_failures > 0 && <span className="text-[#C9190B]">{stats.destroy_failures} destroy</span>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>
          )}

          {labagator.status_counts && (
            <section>
              <SectionHeader>Lab Readiness ({labagator.total_labs} labs from Labagator)</SectionHeader>
              <div className="flex flex-wrap gap-3">
                {Object.entries(labagator.status_counts as Record<string, number>).map(([status, count]) => (
                  <div key={status} className="bg-[#212121] border border-[#2e2e2e] rounded-lg px-4 py-2 flex items-center gap-2">
                    <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={{
                      backgroundColor: status === 'ready' ? '#3E8635' : status === 'in_development' ? '#0066CC' : '#F0AB00',
                      color: '#fff'
                    }}>{status}</span>
                    <span className="text-white text-sm font-medium">{count as number}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {coverage && (
            <section>
              <SectionHeader>Data Coverage</SectionHeader>
              <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 text-xs space-y-2">
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#3E8635]" />
                  <span className="text-[#d2d2d2]">AAP job history: {coverage.aap_jobs?.note || 'Available'}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#3E8635]" />
                  <span className="text-[#d2d2d2]">Lab inventory: {labagator.total_labs || 0} labs, {labagator.total_sessions || 0} sessions from Labagator</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#6A6E73]" />
                  <span className="text-[#d2d2d2]">Evaluations: {coverage.evaluations?.note || 'Not available'}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-[#6A6E73]" />
                  <span className="text-[#d2d2d2]">Cluster metrics: {coverage.cluster_metrics?.note || 'Not available'}</span>
                </div>
              </div>
            </section>
          )}
        </div>
      )}

      {activeTab === 'labs' && (
        <div className="space-y-4">
          <SearchBar placeholder="Search labs..." value={labSearch} onChange={setLabSearch} className="w-72" />
          <div className="space-y-0.5">
            <div className="grid grid-cols-[1fr_200px_100px_80px_80px_80px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
              <span>Code</span><span>Title</span><span>Status</span><span className="text-right">AAP Fails</span><span className="text-right">Destroy</span><span className="text-right">Provision</span>
            </div>
            {filteredLabs.map(([code, info]: [string, any]) => {
              const aapStats = topFailingLabs[code.toLowerCase()] || topFailingLabs[code] || {};
              return (
                <div key={code} className="grid grid-cols-[1fr_200px_100px_80px_80px_80px] gap-3 items-center py-1.5 hover:bg-[#1e1e1e] rounded transition">
                  <span className="text-sm text-[#73BCF7] font-mono truncate">{code}</span>
                  <span className="text-sm text-white truncate" title={info.title}>{info.title || ''}</span>
                  <span className="text-xs">
                    <span className="px-1.5 py-0.5 rounded" style={{
                      backgroundColor: info.status === 'ready' ? '#3E863520' : info.status === 'in_development' ? '#0066CC20' : '#F0AB0020',
                      color: info.status === 'ready' ? '#3E8635' : info.status === 'in_development' ? '#73BCF7' : '#F0AB00',
                    }}>{info.status || ''}</span>
                  </span>
                  <span className={`text-sm text-right ${aapStats.failed > 0 ? 'text-[#C9190B] font-bold' : 'text-[#6A6E73]'}`}>{aapStats.failed || 0}</span>
                  <span className={`text-sm text-right ${aapStats.destroy_failures > 0 ? 'text-[#C9190B]' : 'text-[#6A6E73]'}`}>{aapStats.destroy_failures || 0}</span>
                  <span className={`text-sm text-right ${aapStats.provision_failures > 0 ? 'text-[#F0AB00]' : 'text-[#6A6E73]'}`}>{aapStats.provision_failures || 0}</span>
                </div>
              );
            })}
          </div>
          {labagator.cloud_counts && (
            <div className="flex flex-wrap gap-3 mt-4">
              {Object.entries(labagator.cloud_counts as Record<string, number>).map(([cloud, count]) => (
                <div key={cloud} className="bg-[#212121] border border-[#2e2e2e] rounded-lg px-3 py-1.5 text-xs">
                  <span className="text-white">{cloud}</span>
                  <span className="text-[#6A6E73] ml-2">{count as number}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {activeTab === 'failures' && (
        <div className="space-y-6">
          <section>
            <SectionHeader>AAP Failure Types</SectionHeader>
            <div className="space-y-2">
              {failureEntries.map(([cls, count]) => (
                <div key={cls} className="flex items-center gap-3">
                  <span className="text-xs w-32 shrink-0" style={{ color: cls === 'destroy' ? '#C9190B' : cls === 'provision' ? '#F0AB00' : '#6A6E73' }}>{cls}</span>
                  <div className="flex-1 bg-[#333] h-4 rounded overflow-hidden">
                    <div className="h-4 rounded" style={{ width: `${((count as number) / maxFailure) * 100}%`, backgroundColor: cls === 'destroy' ? '#C9190B' : cls === 'provision' ? '#F0AB00' : '#6A6E73' }} />
                  </div>
                  <span className="text-xs text-white font-medium w-12 text-right">{(count as number).toLocaleString()}</span>
                </div>
              ))}
            </div>
          </section>

          <section>
            <SectionHeader>Top Failing Labs</SectionHeader>
            <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 overflow-x-auto">
              <div className="grid grid-cols-[1fr_80px_80px_80px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
                <span>Lab</span><span className="text-right">Total</span><span className="text-right">Destroy</span><span className="text-right">Provision</span>
              </div>
              {Object.entries(topFailingLabs as Record<string, any>).map(([lab, stats]: [string, any]) => (
                <div key={lab} className="grid grid-cols-[1fr_80px_80px_80px] gap-3 items-center py-1.5">
                  <span className="text-sm text-white font-mono truncate">{lab}</span>
                  <span className="text-sm text-[#C9190B] text-right font-bold">{stats.failed}</span>
                  <span className={`text-sm text-right ${stats.destroy_failures > 0 ? 'text-[#C9190B]' : 'text-[#6A6E73]'}`}>{stats.destroy_failures}</span>
                  <span className={`text-sm text-right ${stats.provision_failures > 0 ? 'text-[#F0AB00]' : 'text-[#6A6E73]'}`}>{stats.provision_failures}</span>
                </div>
              ))}
            </div>
          </section>
        </div>
      )}

      {activeTab === 'reclamation' && reclamation.total_destroy_jobs && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <MetricCard label="Destroy Jobs" value={(reclamation.total_destroy_jobs || 0).toLocaleString()} />
            <MetricCard label="Successful" value={(reclamation.successful || 0).toLocaleString()} />
            <MetricCard label="Failed" value={(reclamation.failed || 0).toLocaleString()} />
            <MetricCard label="Retried + Recovered" value={reclamation.retried_and_recovered || 0} sub="Failed then succeeded via AAP retry" />
            <MetricCard label="Never Reclaimed" value={reclamation.never_reclaimed || 0} sub="No successful AAP destroy ever" />
          </div>

          <section>
            <SectionHeader>Proven Outcomes</SectionHeader>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                <div className="text-2xl font-bold text-[#3E8635]" style={{ fontFamily: 'Red Hat Display' }}>{(reclamation.success_only || 0).toLocaleString()}</div>
                <div className="text-xs text-[#6A6E73] uppercase mt-1">Clean Destroys</div>
                <div className="text-xs text-[#6A6E73] mt-2">Destroyed on first attempt. Standard ansible/destroy.yml completed normally.</div>
              </div>
              <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                <div className="text-2xl font-bold text-[#F0AB00]" style={{ fontFamily: 'Red Hat Display' }}>{reclamation.retried_and_recovered || 0}</div>
                <div className="text-xs text-[#6A6E73] uppercase mt-1">Recovered via Retry</div>
                <div className="text-xs text-[#6A6E73] mt-2">Failed then succeeded on a later AAP retry. Proven by matching resource IDs across jobs.</div>
              </div>
              <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                <div className="text-2xl font-bold text-[#C9190B]" style={{ fontFamily: 'Red Hat Display' }}>{reclamation.never_reclaimed || 0}</div>
                <div className="text-xs text-[#6A6E73] uppercase mt-1">Never Reclaimed via AAP</div>
                <div className="text-xs text-[#6A6E73] mt-2">No successful AAP destroy job exists. Reclaimed outside AAP with no auditable record.</div>
              </div>
            </div>
          </section>

          {reclamation.error_patterns?.length > 0 && (
            <section>
              <SectionHeader>Root Cause Patterns</SectionHeader>
              <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 space-y-3">
                {(reclamation.error_patterns as any[]).map((p: any, i: number) => (
                  <div key={i} className="flex items-start gap-3">
                    <span className="text-[#C9190B] text-sm font-bold w-10 text-right shrink-0">{p.count}x</span>
                    <div>
                      <div className="text-sm text-white font-mono">{p.pattern}</div>
                      <div className="text-xs text-[#6A6E73] mt-0.5">
                        {p.pattern.includes('ArgoCD') && 'Kubeconfig expired before destroy ran. Cluster session token was already revoked.'}
                        {p.pattern.includes('Log in') && 'Cluster DNS already gone. Cluster torn down before tenant namespace destroy.'}
                        {p.pattern.includes('ocp_console_embed') && 'Required variable not preserved from provision phase.'}
                        {p.pattern.includes('workload_destroyer') && 'Template variables not resolved for destroy context.'}
                        {p.pattern.includes('dns') && 'DNS record cleanup failed during assisted-installer teardown.'}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {reclamation.orphan_by_catalog_prefix && Object.keys(reclamation.orphan_by_catalog_prefix).length > 0 && (
            <section>
              <SectionHeader>Orphaned by Catalog ({reclamation.never_reclaimed} total)</SectionHeader>
              <div className="flex flex-wrap gap-3">
                {Object.entries(reclamation.orphan_by_catalog_prefix as Record<string, number>).map(([prefix, count]) => (
                  <div key={prefix} className="bg-[#212121] border border-[#C9190B]/30 rounded-lg px-4 py-3 text-center">
                    <div className="text-xl font-bold text-[#C9190B]" style={{ fontFamily: 'Red Hat Display' }}>{count as number}</div>
                    <div className="text-xs text-[#6A6E73] uppercase mt-1">{prefix}</div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {reclamation.retry_examples?.length > 0 && (
            <section>
              <SectionHeader>Retry Evidence</SectionHeader>
              <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 overflow-x-auto">
                <div className="grid grid-cols-[1fr_120px_60px_140px_140px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
                  <span>Resource</span><span>Lab</span><span className="text-right">Fails</span><span>First Fail</span><span>Recovered</span>
                </div>
                {(reclamation.retry_examples as any[]).slice(0, 15).map((r: any) => (
                  <div key={r.resource_id} className="grid grid-cols-[1fr_120px_60px_140px_140px] gap-3 items-center py-1.5">
                    <span className="text-xs text-[#6A6E73] font-mono truncate">{r.resource_id}</span>
                    <span className="text-xs text-white">{r.lab}</span>
                    <span className="text-xs text-[#C9190B] text-right">{r.fail_count}</span>
                    <span className="text-xs text-[#6A6E73]">{r.first_fail?.slice(5, 16)}</span>
                    <span className="text-xs text-[#3E8635]">{r.final_success?.slice(5, 16)}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {reclamation.orphaned_resources?.length > 0 && (
            <section>
              <SectionHeader>Orphaned Resources</SectionHeader>
              <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 overflow-x-auto">
                <div className="grid grid-cols-[1fr_1fr_80px_140px] gap-3 text-xs text-[#6A6E73] uppercase tracking-wider font-bold pb-2 border-b border-[#2e2e2e]">
                  <span>Resource</span><span>Catalog</span><span className="text-right">Attempts</span><span>Last Attempt</span>
                </div>
                {(reclamation.orphaned_resources as any[]).map((o: any) => (
                  <div key={o.resource_id} className="grid grid-cols-[1fr_1fr_80px_140px] gap-3 items-center py-1.5">
                    <span className="text-xs text-[#C9190B] font-mono truncate">{o.resource_id}</span>
                    <span className="text-xs text-white truncate">{o.catalog}</span>
                    <span className="text-xs text-[#6A6E73] text-right">{o.attempts}</span>
                    <span className="text-xs text-[#6A6E73]">{o.last_attempt?.slice(5, 16)}</span>
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
