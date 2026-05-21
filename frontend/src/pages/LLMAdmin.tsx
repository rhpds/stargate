import { useState } from 'react';
import {
  Button,
  Card,
  CardBody,
  CardTitle,
  Label,
  PageSection,
  Content,
  Spinner,
  Progress,
} from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import { useLLMMetrics, useLLMTimeline, useLLMRecent, useLLMEvaluation, useLLMDrift, useLLMConfig, useLLMABTest, useLLMGroundTruth, useLLMAccuracy, useLLMFeedback } from '../api/hooks';
import { Alert } from '@patternfly/react-core';

export default function LLMAdmin() {
  const { data: metrics, isLoading: loadingMetrics } = useLLMMetrics();
  const { data: timeline, isLoading: loadingTimeline } = useLLMTimeline(24);
  const { data: recent, isLoading: loadingRecent } = useLLMRecent(50);
  const { data: evaluation, isLoading: loadingEval } = useLLMEvaluation();
  const { data: drift } = useLLMDrift();
  const { data: config } = useLLMConfig();
  const { data: abTest } = useLLMABTest();
  const { data: groundTruth } = useLLMGroundTruth();
  const { data: accuracy } = useLLMAccuracy();
  const feedback = useLLMFeedback();

  if (loadingMetrics) return <PageSection><Spinner size="xl" /></PageSection>;

  return (
    <>
      <PageSection>
        <Content><h1>LLM Observability</h1></Content>
      </PageSection>

      {/* Summary Cards */}
      <PageSection style={{ paddingTop: 0 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem' }}>
          <MetricCard label="Total Calls" value={metrics?.total_calls ?? 0} />
          <MetricCard label="Total Tokens" value={(metrics?.total_tokens ?? 0).toLocaleString()} />
          <MetricCard label="Est. Cost" value={`$${(metrics?.total_cost_estimate ?? 0).toFixed(4)}`} />
          <MetricCard label="Error Rate" value={`${((metrics?.error_rate ?? 0) * 100).toFixed(1)}%`} color={metrics && metrics.error_rate > 0.05 ? 'var(--sg-color--critical)' : undefined} />
          <MetricCard label="Calls (1h)" value={metrics?.calls_last_hour ?? 0} />
          <MetricCard label="Calls (24h)" value={metrics?.calls_last_24h ?? 0} />
          <MetricCard label="Avg Confidence" value={metrics?.avg_confidence != null ? `${(metrics.avg_confidence * 100).toFixed(0)}%` : '—'} />
        </div>
      </PageSection>

      {/* Drift Detection */}
      {drift && (
        <PageSection style={{ paddingTop: 0 }}>
          {drift.alerts.length > 0 && drift.alerts.map((a, i) => (
            <Alert key={i} variant={a.severity === 'critical' ? 'danger' : 'warning'} title={a.message} isInline style={{ marginBottom: '0.5rem' }} />
          ))}
          <Card>
            <CardTitle>
              Quality Trend:
              <Label
                isCompact
                color={drift.status === 'stable' ? 'green' : drift.status === 'drifting' ? 'orange' : 'red'}
                style={{ marginLeft: '0.5rem' }}
              >
                {drift.status}
              </Label>
            </CardTitle>
            <CardBody>
              <Table aria-label="Drift comparison" variant="compact">
                <Thead><Tr><Th>Metric</Th><Th>Last 7 days</Th><Th>Prior 7 days</Th><Th>Change</Th></Tr></Thead>
                <Tbody>
                  <Tr>
                    <Td><strong>Calls</strong></Td>
                    <Td>{drift.recent.calls}</Td>
                    <Td>{drift.prior.calls}</Td>
                    <Td>{drift.prior.calls > 0 ? `${((drift.recent.calls - drift.prior.calls) / drift.prior.calls * 100).toFixed(0)}%` : '—'}</Td>
                  </Tr>
                  <Tr>
                    <Td><strong>Avg Latency</strong></Td>
                    <Td>{drift.recent.avg_latency}ms</Td>
                    <Td>{drift.prior.avg_latency}ms</Td>
                    <Td style={{ color: drift.recent.avg_latency > drift.prior.avg_latency * 1.5 ? 'var(--sg-color--critical)' : undefined }}>
                      {drift.prior.avg_latency > 0 ? `${((drift.recent.avg_latency - drift.prior.avg_latency) / drift.prior.avg_latency * 100).toFixed(0)}%` : '—'}
                    </Td>
                  </Tr>
                  <Tr>
                    <Td><strong>Error Rate</strong></Td>
                    <Td>{(drift.recent.error_rate * 100).toFixed(1)}%</Td>
                    <Td>{(drift.prior.error_rate * 100).toFixed(1)}%</Td>
                    <Td style={{ color: drift.recent.error_rate > 0.05 ? 'var(--sg-color--critical)' : undefined }}>
                      {drift.recent.error_rate > drift.prior.error_rate ? '↑' : drift.recent.error_rate < drift.prior.error_rate ? '↓' : '—'}
                    </Td>
                  </Tr>
                  <Tr>
                    <Td><strong>Approval Rate</strong></Td>
                    <Td>{drift.recent.approval_rate != null ? `${drift.recent.approval_rate}%` : '—'}</Td>
                    <Td>{drift.prior.approval_rate != null ? `${drift.prior.approval_rate}%` : '—'}</Td>
                    <Td>{drift.recent.approval_rate != null && drift.prior.approval_rate != null
                      ? `${(drift.recent.approval_rate - drift.prior.approval_rate).toFixed(1)}pp`
                      : '—'}</Td>
                  </Tr>
                  <Tr>
                    <Td><strong>Cost</strong></Td>
                    <Td>${drift.recent.total_cost.toFixed(4)}</Td>
                    <Td>${drift.prior.total_cost.toFixed(4)}</Td>
                    <Td>{drift.prior.total_cost > 0 ? `${((drift.recent.total_cost - drift.prior.total_cost) / drift.prior.total_cost * 100).toFixed(0)}%` : '—'}</Td>
                  </Tr>
                </Tbody>
              </Table>
            </CardBody>
          </Card>
        </PageSection>
      )}

      {/* Latency by Endpoint + Errors */}
      <PageSection style={{ paddingTop: 0 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
          <Card>
            <CardTitle>Latency by Endpoint</CardTitle>
            <CardBody>
              {metrics && Object.keys(metrics.avg_latency_ms).length > 0 ? (
                <Table aria-label="Latency" variant="compact">
                  <Thead><Tr><Th>Endpoint</Th><Th>Calls</Th><Th>Avg (ms)</Th><Th>P95 (ms)</Th><Th>Tokens</Th></Tr></Thead>
                  <Tbody>
                    {Object.keys(metrics.calls_by_endpoint).map(ep => (
                      <Tr key={ep}>
                        <Td><strong>{ep}</strong></Td>
                        <Td>{metrics.calls_by_endpoint[ep]}</Td>
                        <Td>{metrics.avg_latency_ms[ep]?.toLocaleString() ?? '—'}</Td>
                        <Td style={{ color: (metrics.p95_latency_ms[ep] ?? 0) > 10000 ? 'var(--sg-color--critical)' : undefined }}>
                          {metrics.p95_latency_ms[ep]?.toLocaleString() ?? '—'}
                        </Td>
                        <Td>{(metrics.tokens_by_endpoint[ep] ?? 0).toLocaleString()}</Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              ) : <em style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>No calls recorded yet.</em>}
            </CardBody>
          </Card>

          <Card>
            <CardTitle>Errors</CardTitle>
            <CardBody>
              {metrics && Object.keys(metrics.errors_by_type).length > 0 ? (
                <Table aria-label="Errors" variant="compact">
                  <Thead><Tr><Th>Error Type</Th><Th>Count</Th></Tr></Thead>
                  <Tbody>
                    {Object.entries(metrics.errors_by_type).map(([type, count]) => (
                      <Tr key={type}>
                        <Td><Label isCompact color="red">{type}</Label></Td>
                        <Td><strong>{count as number}</strong></Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              ) : <em style={{ color: 'var(--sg-color--healthy, #3e8635)' }}>No errors recorded.</em>}
            </CardBody>
          </Card>
        </div>
      </PageSection>

      {/* Activity Timeline */}
      <PageSection style={{ paddingTop: 0 }}>
        <Card>
          <CardTitle>Activity (Last 24h)</CardTitle>
          <CardBody>
            {loadingTimeline ? <Spinner size="lg" /> : timeline && timeline.calls.some(c => c > 0) ? (
              <div style={{ display: 'flex', gap: '2px', alignItems: 'flex-end', height: 80 }}>
                {timeline.hours.map((h, i) => {
                  const maxCalls = Math.max(...timeline.calls, 1);
                  const height = ((timeline.calls?.[i] ?? 0) / maxCalls) * 100;
                  const hasError = (timeline.errors?.[i] ?? 0) > 0;
                  return (
                    <div
                      key={h}
                      title={`${h}: ${timeline.calls[i]} calls, ${timeline.latency_avg[i]}ms avg, ${timeline.tokens[i]} tokens${hasError ? `, ${timeline.errors[i]} errors` : ''}`}
                      style={{
                        flex: 1,
                        height: `${Math.max(height, 2)}%`,
                        backgroundColor: hasError ? 'var(--sg-color--critical, #c9190b)' : 'var(--sg-color--info, #06c)',
                        borderRadius: '2px 2px 0 0',
                        minWidth: 4,
                      }}
                    />
                  );
                })}
              </div>
            ) : <em style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>No activity in the last 24 hours.</em>}
          </CardBody>
        </Card>
      </PageSection>

      {/* A/B Testing */}
      <PageSection style={{ paddingTop: 0 }}>
        <Card>
          <CardTitle>Prompt A/B Testing</CardTitle>
          <CardBody>
            {abTest && Object.keys(abTest.versions).length > 0 ? (
              <Table aria-label="A/B test results" variant="compact">
                <Thead><Tr><Th>Version</Th><Th>Calls</Th><Th>Success Rate</Th><Th>Avg Latency</Th><Th>P95 Latency</Th><Th>Avg Tokens</Th><Th>Cost</Th></Tr></Thead>
                <Tbody>
                  {Object.entries(abTest.versions).map(([version, stats]) => (
                    <Tr key={version}>
                      <Td><Label isCompact color="blue">v{version}</Label></Td>
                      <Td>{stats.calls}</Td>
                      <Td><strong style={{ color: stats.success_rate >= 0.95 ? 'var(--sg-color--healthy)' : stats.success_rate >= 0.8 ? 'var(--sg-color--warning)' : 'var(--sg-color--critical)' }}>{(stats.success_rate * 100).toFixed(1)}%</strong></Td>
                      <Td>{stats.avg_latency_ms.toLocaleString()}ms</Td>
                      <Td>{stats.p95_latency_ms.toLocaleString()}ms</Td>
                      <Td>{stats.avg_tokens}</Td>
                      <Td>${stats.total_cost.toFixed(4)}</Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            ) : <em style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>No versioned prompt data yet. Set STARGATE_PROMPT_VARIANTS_CLASSIFY to enable A/B testing.</em>}
          </CardBody>
        </Card>
      </PageSection>

      {/* Evaluation + Ground Truth */}
      <PageSection style={{ paddingTop: 0 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
          <Card>
            <CardTitle>Evaluation — Feedback Loop</CardTitle>
            <CardBody>
              {loadingEval ? <Spinner size="lg" /> : evaluation && evaluation.total_proposals > 0 ? (
                <div>
                  <div style={{ display: 'flex', gap: '2rem', marginBottom: '1rem', fontSize: '0.9rem', flexWrap: 'wrap' }}>
                    <span><strong>{evaluation.total_proposals}</strong> proposals</span>
                    <span><Label isCompact color="green">{evaluation.approved} approved</Label></span>
                    <span><Label isCompact color="red">{evaluation.rejected} rejected</Label></span>
                    <span><Label isCompact color="orange">{evaluation.pending_review} pending</Label></span>
                    <span>Approval rate: <strong style={{ color: evaluation.approval_rate >= 80 ? 'var(--sg-color--healthy)' : evaluation.approval_rate >= 60 ? 'var(--sg-color--warning)' : 'var(--sg-color--critical)' }}>
                      {evaluation.approval_rate}%
                    </strong></span>
                  </div>

                  {evaluation.confidence_calibration.length > 0 && (
                    <>
                      <h4 style={{ marginBottom: '0.5rem' }}>Confidence Calibration</h4>
                      <Table aria-label="Calibration" variant="compact">
                        <Thead><Tr><Th>Confidence Bucket</Th><Th>Total</Th><Th>Approved</Th><Th>Actual Rate</Th><Th>Calibration</Th></Tr></Thead>
                        <Tbody>
                          {evaluation.confidence_calibration.map(c => (
                            <Tr key={c.bucket}>
                              <Td>{c.bucket}</Td>
                              <Td>{c.total}</Td>
                              <Td>{c.approved}</Td>
                              <Td><strong>{c.rate}%</strong></Td>
                              <Td style={{ minWidth: 120 }}>
                                <Progress value={c.rate} size="sm" variant={c.rate >= 80 ? undefined : c.rate >= 60 ? 'warning' : 'danger'} />
                              </Td>
                            </Tr>
                          ))}
                        </Tbody>
                      </Table>
                    </>
                  )}
                </div>
              ) : <em style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>No proposals yet. Classify a failure to start building evaluation data.</em>}
            </CardBody>
          </Card>

          <Card>
            <CardTitle>Ground Truth & Accuracy</CardTitle>
            <CardBody>
              <div style={{ display: 'flex', gap: '2rem', marginBottom: '1rem' }}>
                <div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>Ground Truth Entries</div>
                  <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{groundTruth?.total ?? 0}</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>Accuracy</div>
                  <div style={{ fontSize: '1.5rem', fontWeight: 700, color: (accuracy?.accuracy ?? 0) >= 0.8 ? 'var(--sg-color--healthy)' : (accuracy?.accuracy ?? 0) >= 0.6 ? 'var(--sg-color--warning)' : 'var(--sg-color--critical)' }}>
                    {accuracy && accuracy.total > 0 ? `${(accuracy.accuracy * 100).toFixed(1)}%` : '—'}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>Reviewed</div>
                  <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{accuracy?.total ?? 0}</div>
                </div>
              </div>
              {accuracy && accuracy.total > 0 && Object.keys(accuracy.by_class).length > 0 && (
                <Table aria-label="Accuracy by class" variant="compact">
                  <Thead><Tr><Th>Failure Class</Th><Th>Correct</Th><Th>Total</Th><Th>Rate</Th></Tr></Thead>
                  <Tbody>
                    {Object.entries(accuracy.by_class).map(([cls, stats]) => (
                      <Tr key={cls}>
                        <Td><strong>{cls}</strong></Td>
                        <Td>{stats.correct}</Td>
                        <Td>{stats.total}</Td>
                        <Td>{(stats.correct / Math.max(stats.total, 1) * 100).toFixed(0)}%</Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              )}
              {(!accuracy || accuracy.total === 0) && (
                <em style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>
                  Review LLM proposals to build ground truth data.
                </em>
              )}
            </CardBody>
          </Card>
        </div>
      </PageSection>

      {/* Recent Calls with Feedback */}
      <PageSection style={{ paddingTop: 0 }}>
        <Card>
          <CardTitle>Recent LLM Calls</CardTitle>
          <CardBody>
            {loadingRecent ? <Spinner size="lg" /> : recent && recent.length > 0 ? (
              <Table aria-label="Recent calls" variant="compact">
                <Thead>
                  <Tr>
                    <Th>Endpoint</Th>
                    <Th>Tokens</Th>
                    <Th>Latency</Th>
                    <Th>Cost</Th>
                    <Th>Status</Th>
                    <Th>Confidence</Th>
                    <Th>Context</Th>
                    <Th>Time</Th>
                    <Th>Feedback</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {recent.map(r => (
                    <Tr key={r.id}>
                      <Td><strong>{r.endpoint}</strong></Td>
                      <Td>{r.total_tokens ?? '—'}</Td>
                      <Td style={{ color: r.latency_ms > 10000 ? 'var(--sg-color--critical)' : undefined }}>
                        {(r.latency_ms / 1000).toFixed(1)}s
                      </Td>
                      <Td>{r.cost_estimate != null ? `$${r.cost_estimate.toFixed(4)}` : '—'}</Td>
                      <Td>
                        {r.success
                          ? <Label isCompact color="green">OK</Label>
                          : <Label isCompact color="red">{r.error_type || 'error'}</Label>
                        }
                      </Td>
                      <Td>{r.confidence != null ? `${(r.confidence * 100).toFixed(0)}%` : '—'}</Td>
                      <Td style={{ fontSize: '0.8rem' }}>{r.lab_code || r.cluster_name || r.failure_class || '—'}</Td>
                      <Td style={{ fontSize: '0.8rem', whiteSpace: 'nowrap' }}>{new Date(r.called_at).toLocaleString()}</Td>
                      <Td>
                        <FeedbackButtons metricId={r.id} endpoint={r.endpoint} onSubmit={feedback.mutate} />
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            ) : <em style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>No LLM calls recorded. Trigger a classification or remediation to start tracking.</em>}
          </CardBody>
        </Card>
      </PageSection>

      {/* Config — dynamic */}
      <PageSection style={{ paddingTop: 0 }}>
        <Card>
          <CardTitle>Configuration</CardTitle>
          <CardBody>
            <Table aria-label="Config" variant="compact">
              <Tbody>
                <Tr><Td><strong>Model</strong></Td><Td>{config?.model ?? '—'}</Td></Tr>
                <Tr><Td><strong>API Endpoint</strong></Td><Td>{config?.api_endpoint ?? '—'}</Td></Tr>
                <Tr><Td><strong>Max Tokens</strong></Td><Td>
                  {config?.prompts ? Object.entries(config.prompts).map(([ep, p]) => `${ep}: ${p.max_tokens}`).join(' | ') : '—'}
                </Td></Tr>
                <Tr><Td><strong>Temperature</strong></Td><Td>
                  {config?.prompts ? Object.entries(config.prompts).map(([ep, p]) => `${ep}: ${p.temperature}`).join(' | ') : '—'}
                </Td></Tr>
                <Tr><Td><strong>Timeouts</strong></Td><Td>
                  {config?.prompts ? Object.entries(config.prompts).map(([ep, p]) => `${ep}: ${p.timeout}s`).join(' | ') : '—'}
                </Td></Tr>
                <Tr><Td><strong>Prompt Versions</strong></Td><Td>
                  {config?.prompts ? Object.entries(config.prompts).map(([ep, p]) => `${ep}: v${p.version ?? '?'}`).join(' | ') : '—'}
                </Td></Tr>
              </Tbody>
            </Table>
          </CardBody>
        </Card>
      </PageSection>
    </>
  );
}

function MetricCard({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <Card isCompact>
      <CardBody style={{ padding: '1rem', textAlign: 'center' }}>
        <div style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)', marginBottom: '0.25rem' }}>{label}</div>
        <div style={{ fontSize: '1.5rem', fontWeight: 700, color }}>{value}</div>
      </CardBody>
    </Card>
  );
}

function FeedbackButtons({ metricId, endpoint, onSubmit }: { metricId: number; endpoint: string; onSubmit: (body: import('../api/types').LLMFeedbackRequest) => void }) {
  const [submitted, setSubmitted] = useState<boolean | null>(null);

  if (submitted !== null) {
    return <Label isCompact color={submitted ? 'green' : 'red'}>{submitted ? 'Helpful' : 'Not helpful'}</Label>;
  }

  return (
    <div style={{ display: 'flex', gap: '4px' }}>
      <Button variant="plain" size="sm" style={{ padding: '2px 6px', fontSize: '0.75rem' }} onClick={() => { onSubmit({ llm_metric_id: metricId, endpoint, helpful: true }); setSubmitted(true); }}>
        👍
      </Button>
      <Button variant="plain" size="sm" style={{ padding: '2px 6px', fontSize: '0.75rem' }} onClick={() => { onSubmit({ llm_metric_id: metricId, endpoint, helpful: false }); setSubmitted(false); }}>
        👎
      </Button>
    </div>
  );
}
