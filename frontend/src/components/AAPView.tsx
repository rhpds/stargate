import {
  Card,
  CardBody,
  CardTitle,
  Label,
  Spinner,
} from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

export default function AAPView() {
  const { data, isLoading } = useQuery({
    queryKey: ['aap'],
    queryFn: () => api.getAAP(),
    refetchInterval: 30_000,
  });

  if (isLoading) return <Spinner size="xl" />;
  if (!data) return <em>No AAP data available. Set STARGATE_AAP_EVENT0_URL to enable.</em>;

  const s = data.summary;

  return (
    <div>
      {/* SLI Cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
        <SLICard label="Overall Success" value={`${s.success_rate}%`} color={s.success_rate >= 90 ? 'var(--sg-color--healthy)' : s.success_rate >= 80 ? 'var(--sg-color--warning)' : 'var(--sg-color--critical)'} />
        <SLICard label="Provision SLI" value={`${s.provision_sli}%`} target="93%" color={s.sli_met ? 'var(--sg-color--healthy)' : 'var(--sg-color--critical)'} />
        <SLICard label="Failed (24h)" value={s.failed_24h} color={s.failed_24h > 50 ? 'var(--sg-color--critical)' : s.failed_24h > 10 ? 'var(--sg-color--warning)' : undefined} />
        <SLICard label="Total Jobs" value={s.total_jobs.toLocaleString()} />
        <SLICard label="Running" value={s.running} color="var(--sg-color--info)" />
      </div>

      {!s.sli_met && (
        <div style={{ background: '#fceaea', border: '1px solid var(--sg-color--critical)', borderRadius: '6px', padding: '0.75rem 1rem', marginBottom: '1rem', fontSize: '0.9rem' }}>
          <strong style={{ color: 'var(--sg-color--critical)' }}>SLI Breach:</strong> Provision success rate {s.provision_sli}% is below the {s.provision_sli_target}% target.
        </div>
      )}

      {/* Root Cause Waterfall */}
      {data.top_errors.length > 0 && (
        <Card style={{ marginBottom: '1rem' }}>
          <CardTitle>Root Cause Breakdown</CardTitle>
          <CardBody>
            <div style={{ fontSize: '0.9rem' }}>
              <div style={{ fontWeight: 700, marginBottom: '0.5rem' }}>
                {s.failed_24h} total failures
              </div>
              {data.top_errors.slice(0, 5).map((e: any, i: number) => {
                const pct = Math.round((e.count / Math.max(s.failed_24h, 1)) * 100);
                return (
                  <div key={i} style={{ marginBottom: '0.75rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                      <span style={{ fontSize: '0.8rem', fontWeight: 600, minWidth: '40px' }}>{pct}%</span>
                      <div style={{ flex: 1, height: '20px', background: '#e2e8f0', borderRadius: '4px', overflow: 'hidden' }}>
                        <div style={{
                          width: `${pct}%`, height: '100%',
                          background: e.type === 'provision' ? '#c9190b' : '#6753ac',
                          borderRadius: '4px',
                          display: 'flex', alignItems: 'center', paddingLeft: '6px',
                          fontSize: '0.7rem', color: '#fff', fontWeight: 600,
                        }}>
                          {e.count} {e.type}
                        </div>
                      </div>
                    </div>
                    <div style={{ paddingLeft: '48px', fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>
                      {e.failing_task}
                      {(e.labs || []).length > 0 && (
                        <span style={{ marginLeft: '8px' }}>
                          — {(e.labs as string[]).slice(0, 3).join(', ')}{(e.labs as string[]).length > 3 ? ` +${(e.labs as string[]).length - 3}` : ''}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </CardBody>
        </Card>
      )}

      {/* Top Errors */}
      <Card style={{ marginBottom: '1rem' }}>
        <CardTitle>Top Errors (24h)</CardTitle>
        <CardBody>
          {data.top_errors.length > 0 ? (
            <Table aria-label="Top AAP errors" variant="compact">
              <Thead><Tr><Th>Count</Th><Th>Type</Th><Th>Failing Task</Th><Th>Clusters</Th><Th>Labs</Th></Tr></Thead>
              <Tbody>
                {data.top_errors.slice(0, 15).map((e: any, i: number) => (
                  <Tr key={i}>
                    <Td><strong>{e.count}</strong></Td>
                    <Td><Label isCompact color={e.type === 'provision' ? 'red' : 'purple'}>{e.type}</Label></Td>
                    <Td style={{ fontSize: '0.85rem', maxWidth: '300px' }}>{e.failing_task}</Td>
                    <Td style={{ fontSize: '0.8rem' }}>{(e.clusters || []).join(', ') || '—'}</Td>
                    <Td style={{ fontSize: '0.8rem' }}>{(e.labs || []).join(', ') || '—'}</Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          ) : <em>No failures in last 24 hours.</em>}
        </CardBody>
      </Card>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
        {/* By Cluster */}
        <Card>
          <CardTitle>Failures by Cluster</CardTitle>
          <CardBody>
            {Object.keys(data.by_cluster).length > 0 ? (
              <Table aria-label="AAP by cluster" variant="compact">
                <Thead><Tr><Th>Cluster</Th><Th>Total</Th><Th>Provision</Th><Th>Destroy</Th></Tr></Thead>
                <Tbody>
                  {Object.entries(data.by_cluster)
                    .sort(([, a], [, b]) => (b as any).total - (a as any).total)
                    .map(([cluster, info]) => (
                      <Tr key={cluster}>
                        <Td><strong>{cluster}</strong></Td>
                        <Td>{(info as any).total}</Td>
                        <Td style={{ color: (info as any).provision > 0 ? 'var(--sg-color--critical)' : undefined }}>{(info as any).provision}</Td>
                        <Td>{(info as any).destroy}</Td>
                      </Tr>
                    ))}
                </Tbody>
              </Table>
            ) : <em>No cluster data.</em>}
          </CardBody>
        </Card>

        {/* By Lab */}
        <Card>
          <CardTitle>Failures by Lab</CardTitle>
          <CardBody>
            {Object.keys(data.by_lab).length > 0 ? (
              <Table aria-label="AAP by lab" variant="compact">
                <Thead><Tr><Th>Lab</Th><Th>Total</Th><Th>Prov</Th><Th>Dest</Th><Th>Top Error</Th></Tr></Thead>
                <Tbody>
                  {Object.entries(data.by_lab)
                    .sort(([, a], [, b]) => (b as any).total - (a as any).total)
                    .map(([lab, info]) => (
                      <Tr key={lab}>
                        <Td><strong>{lab}</strong></Td>
                        <Td>{(info as any).total}</Td>
                        <Td style={{ color: (info as any).provision > 0 ? 'var(--sg-color--critical)' : undefined }}>{(info as any).provision}</Td>
                        <Td>{(info as any).destroy}</Td>
                        <Td style={{ fontSize: '0.8rem', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis' }}>{(info as any).top_error || '—'}</Td>
                      </Tr>
                    ))}
                </Tbody>
              </Table>
            ) : <em>No lab data.</em>}
          </CardBody>
        </Card>
      </div>

      {/* Recent Failures */}
      <Card style={{ marginTop: '1rem' }}>
        <CardTitle>Recent Failures</CardTitle>
        <CardBody>
          {data.recent_failures.length > 0 ? (
            <Table aria-label="Recent AAP failures" variant="compact">
              <Thead><Tr><Th>Time</Th><Th>Type</Th><Th>Lab</Th><Th>Cluster</Th><Th>Error</Th><Th>Duration</Th><Th>Job</Th></Tr></Thead>
              <Tbody>
                {data.recent_failures.slice(0, 25).map((f: any, i: number) => (
                  <Tr key={i}>
                    <Td style={{ fontSize: '0.8rem', whiteSpace: 'nowrap' }}>{f.finished ? new Date(f.finished).toLocaleTimeString() : '—'}</Td>
                    <Td><Label isCompact color={f.type === 'provision' ? 'red' : 'purple'}>{f.type}</Label></Td>
                    <Td style={{ fontWeight: 600 }}>{f.lab_code || '—'}</Td>
                    <Td>{f.cluster || '—'}</Td>
                    <Td style={{ fontSize: '0.8rem', maxWidth: '250px', overflow: 'hidden', textOverflow: 'ellipsis' }}>{f.failing_task}</Td>
                    <Td>{f.duration_minutes}m</Td>
                    <Td>
                      {f.job_url ? (
                        <a href={f.job_url} target="_blank" rel="noreferrer" style={{ color: 'var(--sg-color--info)', fontSize: '0.8rem' }}>
                          #{f.job_id}
                        </a>
                      ) : '—'}
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          ) : <em>No recent failures.</em>}
        </CardBody>
      </Card>
    </div>
  );
}

function SLICard({ label, value, target, color }: { label: string; value: string | number; target?: string; color?: string }) {
  return (
    <Card isCompact>
      <CardBody style={{ padding: '1rem', textAlign: 'center' }}>
        <div style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)', marginBottom: '0.25rem' }}>{label}</div>
        <div style={{ fontSize: '1.5rem', fontWeight: 700, color }}>{value}</div>
        {target && <div style={{ fontSize: '0.7rem', color: 'var(--rh-color--text-secondary)' }}>target: {target}</div>}
      </CardBody>
    </Card>
  );
}
