import { useState } from 'react';
import { Button, Card, CardBody, CardTitle, Label, Spinner } from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import { useForecast, useCapacityAnalysis } from '../api/hooks';
import type { CapacityAnalysisData } from '../api/types';

export default function ForecastView() {
  const { data, isLoading } = useForecast();
  const capacityMutation = useCapacityAnalysis();
  const [capacityData, setCapacityData] = useState<CapacityAnalysisData | null>(null);

  if (isLoading) return <Spinner size="lg" />;
  if (!data) return <em>No forecast data available.</em>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {data.summary && (
        <Card>
          <CardTitle>Forecast Summary</CardTitle>
          <CardBody>
            <div style={{ display: 'flex', gap: '2rem', fontSize: '0.95rem' }}>
              <div>Peak hour: <strong>{data.summary.peak_hour || '—'}</strong></div>
              <div>Peak attendees: <strong>{data.summary.peak_instances}</strong></div>
              <div>High-risk hours: <strong style={{ color: data.summary.high_risk_hours > 0 ? 'var(--sg-color--critical)' : undefined }}>{data.summary.high_risk_hours}</strong></div>
            </div>
          </CardBody>
        </Card>
      )}

      <Card>
        <CardTitle>Hourly Forecast (Next 7 Hours)</CardTitle>
        <CardBody>
          <Table aria-label="Forecast" variant="compact">
            <Thead><Tr><Th>Hour</Th><Th>Sessions</Th><Th>Labs</Th><Th>Instances</Th><Th>New Workloads</Th><Th>Pools Available</Th><Th>Risk</Th></Tr></Thead>
            <Tbody>
              {data.forecast_hours.map(h => (
                <Tr key={h.hour}>
                  <Td><strong>{h.hour}</strong></Td>
                  <Td>{h.deployments_starting}</Td>
                  <Td style={{ fontSize: '0.8rem' }}>{h.labs.join(', ') || '—'}</Td>
                  <Td>{h.total_instances}</Td>
                  <Td>{h.estimated_new_workloads}</Td>
                  <Td>{h.pools_available_now}</Td>
                  <Td><Label isCompact color={h.risk === 'high' ? 'red' : h.risk === 'medium' ? 'orange' : 'green'}>{h.risk}</Label></Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </CardBody>
      </Card>

      <Card>
        <CardTitle>Cluster Load Projections</CardTitle>
        <CardBody>
          <Table aria-label="Cluster projections" variant="compact">
            <Thead><Tr><Th>Cluster</Th><Th>CPU</Th><Th>VMs</Th><Th>Sandboxes</Th><Th>Capacity Warning</Th></Tr></Thead>
            <Tbody>
              {data.cluster_projections.map(c => (
                <Tr key={c.cluster}>
                  <Td><strong>{c.cluster}</strong></Td>
                  <Td style={{ color: c.current_cpu > 70 ? 'var(--sg-color--critical)' : undefined }}>{c.current_cpu.toFixed(1)}%</Td>
                  <Td>{c.current_vms}</Td>
                  <Td>{c.current_sandboxes}</Td>
                  <Td>{c.capacity_warning ? <Label isCompact color="red">Warning</Label> : <Label isCompact color="green">OK</Label>}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </CardBody>
      </Card>

      <Card>
        <CardTitle style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          Pool Velocity & Workload Complexity
          <Button variant="secondary" size="sm" isLoading={capacityMutation.isPending}
            onClick={() => capacityMutation.mutate(undefined, { onSuccess: (d) => setCapacityData(d) })}>
            {capacityData ? 'Refresh Analysis' : 'Run Capacity Analysis'}
          </Button>
        </CardTitle>
        <CardBody>
          {capacityData ? (
            <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap' }}>
              <div style={{ flex: 1, minWidth: '300px' }}>
                <strong>Pool Velocity</strong>
                <Table aria-label="Pool velocity" variant="compact">
                  <Thead><Tr><Th>Pool</Th><Th>Available</Th><Th>Velocity</Th><Th>Trend</Th><Th>Exhaustion</Th></Tr></Thead>
                  <Tbody>
                    {Object.entries(capacityData.pool_velocities).map(([name, v]) => (
                      <Tr key={name}>
                        <Td>{name}</Td>
                        <Td>{v.available}</Td>
                        <Td>{v.handles_per_hour.toFixed(1)}/hr</Td>
                        <Td><Label isCompact color={v.trend === 'depleting' ? 'red' : v.trend === 'recovering' ? 'green' : 'grey'}>{v.trend}</Label></Td>
                        <Td>{v.exhaustion_hours != null ? `${v.exhaustion_hours}h` : '—'}</Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              </div>
              <div style={{ flex: 1, minWidth: '300px' }}>
                <strong>Workload Complexity (Top Labs)</strong>
                <Table aria-label="Complexity" variant="compact">
                  <Thead><Tr><Th>Lab</Th><Th>Score</Th><Th>Est. Minutes</Th></Tr></Thead>
                  <Tbody>
                    {Object.entries(capacityData.workload_complexities)
                      .sort(([, a], [, b]) => b.score - a.score)
                      .slice(0, 10)
                      .map(([name, c]) => (
                        <Tr key={name}>
                          <Td>{name}</Td>
                          <Td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                              <div style={{ width: '60px', height: '8px', background: '#f0f0f0', borderRadius: '4px', overflow: 'hidden' }}>
                                <div style={{ width: `${c.score * 100}%`, height: '100%', background: c.score > 0.7 ? '#c9190b' : c.score > 0.4 ? '#f0ab00' : '#3e8635' }} />
                              </div>
                              {c.score.toFixed(2)}
                            </div>
                          </Td>
                          <Td>{c.estimated_minutes}m</Td>
                        </Tr>
                      ))}
                  </Tbody>
                </Table>
              </div>
            </div>
          ) : (
            <em>Click "Run Capacity Analysis" to load pool velocity and workload complexity data.</em>
          )}
          {capacityData?.llm_analysis?.summary && (
            <Card style={{ marginTop: '1rem', background: '#f9f9f9' }}>
              <CardBody>
                <strong>AI Capacity Assessment:</strong> {capacityData.llm_analysis.summary}
              </CardBody>
            </Card>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
