import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

const STATE_COLORS: Record<string, string> = {
  stable_pass: '#3E8635', unstable_pass: '#F0AB00', stable_fail: '#C9190B', unstable_fail: '#A30000',
};

function MetricCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-[#1e1e1e] rounded-lg p-3 border border-[#2e2e2e]">
      <div className="text-[10px] uppercase tracking-wider text-[#6A6E73] font-semibold mb-1">{label}</div>
      <div className="text-2xl font-bold text-white">{value}</div>
      {sub && <div className="text-[10px] text-[#6A6E73] mt-0.5">{sub}</div>}
    </div>
  );
}

function PipelineStage({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex flex-col items-center">
      <div className="text-2xl font-bold" style={{ color }}>{value.toLocaleString()}</div>
      <div className="text-[10px] text-[#8A8D90] uppercase tracking-wider">{label}</div>
    </div>
  );
}

export default function GeoluxOverview() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['geolux-overview'],
    queryFn: () => api.getGeoluxOverview(),
    refetchInterval: 15000,
  });

  const SANDBOX_CLUSTERS = new Set(['ocpv05', 'ocpv06', 'ocpv07', 'ocpv08', 'ocpv09']);
  const isSandbox = (name: string) => SANDBOX_CLUSTERS.has(name);

  const pipeline = data?.pipeline || {};
  const scores: any[] = data?.stability_scores || [];
  const threshold = data?.stability_threshold || 0.7;
  const hypStats = data?.hypothesis_stats || {};
  const learnedPatterns: any[] = data?.learned_patterns || [];
  const mpcStats = data?.mpc_stats || {};

  const filteredMpcClusters = (mpcStats.clusters || []).filter((c: any) => c.cluster && isSandbox(c.cluster));
  const filteredHypClusters = (hypStats.clusters || []).filter((c: any) => c.name && isSandbox(c.name));

  const cls = pipeline.classifications || {};
  const hyp = pipeline.hypotheses || {};
  const topFailures: any[] = pipeline.top_failure_classes || [];
  const recentHypotheses: any[] = data?.recent_hypotheses || [];
  const recentRouting: any[] = data?.recent_routing || [];
  const constraintsCount = data?.constraints_count || 0;

  const avgStability = scores.length > 0
    ? scores.reduce((sum: number, s: any) => sum + (s.stability_score || 0), 0) / scores.length
    : 0;

  const stateDist: Record<string, number> = {};
  scores.forEach((s: any) => { stateDist[s.stability_state] = (stateDist[s.stability_state] || 0) + 1; });

  return (
    <div className="max-w-7xl mx-auto px-6 lg:px-8 py-4">
      <div className="mb-4">
        <h1 className="text-xl font-bold text-white" style={{ fontFamily: 'Red Hat Display' }}>GeoLux</h1>
        <p className="text-[#6A6E73] text-xs">Governance brain — hypothesis engine, constraint classification, MPC controller, geometric stability</p>
      </div>

      {isLoading && <div className="text-[#6A6E73] py-12 text-center">Loading...</div>}
      {error && <div className="text-[#C9190B] py-12 text-center">Error: {(error as Error).message}</div>}
      {pipeline.error && <div className="text-[#F0AB00] py-4 text-center text-sm">GeoLux unavailable: {pipeline.error}</div>}

      {data && !pipeline.error && (
        <>
          {/* Stats Bar */}
          <div className="grid grid-cols-4 gap-3 mb-4">
            <MetricCard label="Hypotheses" value={filteredHypClusters.reduce((s: number, c: any) => s + c.count, 0).toLocaleString()}
              sub={`${hypStats.pending || 0} pending · ${filteredHypClusters.length} clusters`} />
            <MetricCard label="Classifications" value={cls.total || 0}
              sub={`${cls.pass || 0} pass · ${cls.fail || 0} fail · ${cls.inconclusive || 0} inconclusive`} />
            <MetricCard label="MPC Cycles" value={filteredMpcClusters.reduce((s: number, c: any) => s + c.cycles, 0)}
              sub={`${filteredMpcClusters.length} clusters · ${mpcStats.suspended || 0} suspended`} />
            <MetricCard label="Stability" value={avgStability > 0 ? avgStability.toFixed(2) : '--'}
              sub={`threshold: ${threshold} · ${scores.length} recent calls`} />
          </div>

          {/* Stability Monitor + Pipeline */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            {/* Geometric Stability */}
            <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] p-4">
              <h3 className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider mb-3">Geometric Stability</h3>
              {scores.length === 0 ? (
                <div className="text-[#555] text-xs text-center py-4">No stability data</div>
              ) : (
                <>
                  <div className="flex items-center gap-4 mb-3">
                    <div>
                      <div className="text-3xl font-bold" style={{ color: avgStability >= threshold ? '#3E8635' : '#C9190B' }}>
                        {avgStability.toFixed(3)}
                      </div>
                      <div className="text-[10px] text-[#6A6E73]">avg score</div>
                    </div>
                    <div className="flex gap-1.5 flex-wrap">
                      {Object.entries(stateDist).map(([state, count]) => (
                        <span key={state} className="text-[10px] px-1.5 py-0.5 rounded" style={{
                          backgroundColor: `${STATE_COLORS[state] || '#555'}30`,
                          color: STATE_COLORS[state] || '#8A8D90',
                        }}>{state.replace(/_/g, ' ')} ({count})</span>
                      ))}
                    </div>
                  </div>
                  {/* Mini sparkline */}
                  <div className="flex items-end gap-px h-8">
                    {scores.map((s: any, i: number) => (
                      <div key={i} className="flex-1 rounded-sm min-w-[3px]"
                        style={{
                          height: `${Math.max((s.stability_score || 0) * 100, 5)}%`,
                          backgroundColor: (s.stability_score || 0) >= threshold ? '#3E8635' : '#C9190B',
                          opacity: 0.8,
                        }}
                        title={`${s.endpoint || ''}: ${s.stability_score?.toFixed(3)}`} />
                    ))}
                  </div>
                  <div className="flex justify-between mt-1">
                    <span className="text-[9px] text-[#555]">oldest</span>
                    <span className="text-[9px] text-[#555]">threshold {threshold} ─</span>
                    <span className="text-[9px] text-[#555]">newest</span>
                  </div>
                </>
              )}
            </div>

            {/* Governance Pipeline */}
            <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] p-4">
              <h3 className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider mb-3">Governance Pipeline</h3>
              {(() => {
                const hypTotal = filteredHypClusters.reduce((s: number, c: any) => s + c.count, 0);
                const mpcTotal = filteredMpcClusters.reduce((s: number, c: any) => s + c.cycles, 0);
                return (
                  <>
                    <div className="flex items-center justify-between gap-2">
                      <PipelineStage label="Constraints" value={constraintsCount} color="#4394E5" />
                      <span className="text-[#555]">→</span>
                      <PipelineStage label="Classify" value={cls.total || 0} color="#4EC9B0" />
                      <span className="text-[#555]">→</span>
                      <PipelineStage label="Hypotheses" value={hypTotal} color="#DCDCAA" />
                      <span className="text-[#555]">→</span>
                      <PipelineStage label="Validated" value={hyp.validated || 0} color="#3E8635" />
                      <span className="text-[#555]">→</span>
                      <PipelineStage label="MPC" value={mpcTotal} color="#F0AB00" />
                    </div>
                    <div className="mt-2 flex gap-3 text-[10px] text-[#6A6E73]">
                      <span>{hypStats.pending || 0} pending</span>
                      <span className="text-[#C9190B]">{hyp.falsified || 0} falsified</span>
                      <span>{mpcStats.horizon_adjusted || 0} horizon-adjusted</span>
                    </div>
                  </>
                );
              })()}
            </div>
          </div>

          {/* Top Failure Classes + Cluster Health */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] p-4">
              <h3 className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider mb-3">Top Failure Classes</h3>
              {topFailures.length === 0 ? (
                <div className="text-[#555] text-xs text-center py-4">No data</div>
              ) : (
                <div className="space-y-1.5">
                  {topFailures.slice(0, 10).map((fc: any, i: number) => {
                    const total = topFailures.reduce((s: number, f: any) => s + (f.count || 0), 0);
                    const pct = total > 0 ? ((fc.count || 0) / total * 100).toFixed(1) : '0';
                    return (
                      <div key={i} className="flex items-center justify-between bg-[#1a1a1a] rounded px-2.5 py-1.5 border border-[#2a2a2a]">
                        <span className="text-xs text-[#C9190B] font-mono truncate flex-1">{fc.name || fc.class || fc.failure_class}</span>
                        <div className="flex items-center gap-2 text-[10px] text-[#8A8D90] shrink-0">
                          <span>{(fc.count || 0).toLocaleString()} hypotheses</span>
                          <span>{pct}%</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] p-4">
              <h3 className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider mb-3">MPC by Cluster</h3>
              {filteredMpcClusters.length === 0 ? (
                <div className="text-[#555] text-xs text-center py-4">No data</div>
              ) : (
                <div className="space-y-1.5">
                  {filteredMpcClusters.map((c: any, i: number) => (
                    <div key={i} className="flex items-center justify-between bg-[#1a1a1a] rounded px-2.5 py-1.5 border border-[#2a2a2a]">
                      <span className="text-xs text-[#4394E5] font-mono">{c.cluster}</span>
                      <div className="flex items-center gap-3 text-[10px] text-[#8A8D90]">
                        <span>{c.cycles} cycles</span>
                        <span>H={c.avg_horizon}</span>
                        {c.suspended > 0 && <span className="text-[#C9190B]">{c.suspended} suspended</span>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Recent Hypotheses + Routing */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] p-4">
              <h3 className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider mb-3">Recent Hypotheses</h3>
              {recentHypotheses.length === 0 ? (
                <div className="text-[#555] text-xs text-center py-4">No hypotheses</div>
              ) : (
                <div className="space-y-1.5">
                  {recentHypotheses.slice(0, 8).map((h: any, i: number) => (
                    <div key={i} className="bg-[#1a1a1a] rounded px-2.5 py-1.5 border border-[#2a2a2a]">
                      <p className="text-[11px] text-[#ccc] line-clamp-2">{h.claim || h.description || '(no claim)'}</p>
                      <div className="flex items-center gap-2 mt-1 text-[9px] text-[#6A6E73]">
                        {h.geometric_stability_score != null && (
                          <span style={{ color: h.geometric_stability_score >= threshold ? '#3E8635' : '#C9190B' }}>
                            stability: {h.geometric_stability_score.toFixed(2)}
                          </span>
                        )}
                        {h.validation_outcome && <span>{h.validation_outcome}</span>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] p-4">
              <h3 className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider mb-3">Hardware Routing</h3>
              {recentRouting.length === 0 ? (
                <div className="text-[#555] text-xs text-center py-4">No routing decisions</div>
              ) : (
                <div className="space-y-1.5">
                  {recentRouting.slice(0, 8).map((r: any, i: number) => {
                    const tierColor = r.tier_assignment === 'macro' ? '#F0AB00' : r.tier_assignment === 'micro' ? '#4EC9B0' : '#8A8D90';
                    return (
                      <div key={i} className="flex items-center justify-between bg-[#1a1a1a] rounded px-2.5 py-1.5 border border-[#2a2a2a]">
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] px-1.5 py-0.5 rounded font-medium" style={{ backgroundColor: `${tierColor}30`, color: tierColor }}>{r.tier_assignment}</span>
                          <span className="text-[10px] text-[#8A8D90]">{r.substrate}</span>
                        </div>
                        <span className="text-[10px] text-[#ccc]">{r.confidence_score != null ? `${(r.confidence_score * 100).toFixed(0)}%` : ''}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          {/* Hypothesis Stats breakdown */}
          {(hypStats.clusters?.length > 0 || hypStats.failure_classes?.length > 0) && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {filteredHypClusters.length > 0 && (
                <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] p-4">
                  <h3 className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider mb-3">Hypotheses by Cluster</h3>
                  <div className="space-y-1">
                    {filteredHypClusters.map((c: any) => (
                      <div key={c.name} className="flex items-center justify-between text-xs">
                        <span className="text-[#4394E5] font-mono">{c.name}</span>
                        <span className="text-[#ccc]">{c.count.toLocaleString()}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {hypStats.failure_classes?.length > 0 && (
                <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] p-4">
                  <h3 className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider mb-3">Hypotheses by Failure Class</h3>
                  <div className="space-y-1">
                    {hypStats.failure_classes.slice(0, 10).map((fc: any) => (
                      <div key={fc.name} className="flex items-center justify-between text-xs">
                        <span className="text-[#C9190B] font-mono truncate flex-1">{fc.name}</span>
                        <span className="text-[#ccc] shrink-0">{fc.count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* What We've Learned */}
          {learnedPatterns.length > 0 && (
            <div className="bg-[#151515] rounded-lg border border-[#2e2e2e] p-4 mt-4">
              <h3 className="text-xs font-semibold text-[#8A8D90] uppercase tracking-wider mb-3">What We've Learned ({learnedPatterns.length} patterns)</h3>
              <div className="space-y-1.5">
                {learnedPatterns.slice(0, 15).map((p: any, i: number) => {
                  const valColor = p.validation_rate >= 0.7 ? '#3E8635' : p.validation_rate >= 0.4 ? '#F0AB00' : '#C9190B';
                  const profileColor = p.resolution_profile === 'candidate_for_auto_remediation' ? '#3E8635' : p.resolution_profile === 'watch_and_wait' ? '#4394E5' : '#F0AB00';
                  return (
                    <div key={i} className="bg-[#1a1a1a] rounded px-3 py-2 border border-[#2a2a2a]">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs text-[#C9190B] font-mono">{p.failure_class}</span>
                        <div className="flex items-center gap-2">
                          <span className="text-[10px]" style={{ color: valColor }}>{(p.validation_rate * 100).toFixed(0)}% validated</span>
                          <span className="text-[10px] text-[#6A6E73]">{p.observation_count} obs</span>
                        </div>
                      </div>
                      {p.claim_pattern && (
                        <p className="text-[10px] text-[#8A8D90] line-clamp-1 mb-1">{p.claim_pattern}</p>
                      )}
                      <div className="flex items-center gap-2 text-[9px]">
                        {p.resolution_profile && (
                          <span className="px-1.5 py-0.5 rounded" style={{ backgroundColor: `${profileColor}20`, color: profileColor }}>{p.resolution_profile.replace(/_/g, ' ')}</span>
                        )}
                        {p.avg_time_to_resolve_min != null && (
                          <span className="text-[#6A6E73]">{p.avg_time_to_resolve_min.toFixed(0)} min avg resolution</span>
                        )}
                        {p.action_effectiveness != null && (
                          <span className="text-[#4EC9B0]">{(p.action_effectiveness * 100).toFixed(0)}% effective</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
