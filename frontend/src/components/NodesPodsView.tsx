import { useState } from 'react';
import { Gallery, GalleryItem, Card, CardBody, CardTitle, Label, Spinner } from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import { useNodesPods } from '../api/hooks';
import StatusLabel from './StatusLabel';

export default function NodesPodsView() {
  const { data, isLoading } = useNodesPods();
  const [expanded, setExpanded] = useState<string | null>(null);

  if (isLoading) return <Spinner size="lg" />;
  if (!data || data.clusters.length === 0) return <div>No node/pod data — scanner not running</div>;

  const t = data.totals;

  return (
    <div>
      <Gallery hasGutter minWidths={{ default: '130px' }} style={{ marginBottom: '1rem' }}>
        <GalleryItem>
          <Card isCompact isFullHeight>
            <CardTitle style={{ fontSize: '0.85rem' }}>Total Nodes</CardTitle>
            <CardBody style={{ paddingTop: 0 }}>
              <span style={{ fontSize: '1.5rem', fontWeight: 700 }}>{t.nodes}</span>
              <div style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>{t.compute_nodes} compute</div>
            </CardBody>
          </Card>
        </GalleryItem>
        <GalleryItem>
          <Card isCompact isFullHeight>
            <CardTitle style={{ fontSize: '0.85rem' }}>Total VMs</CardTitle>
            <CardBody style={{ paddingTop: 0 }}>
              <span style={{ fontSize: '1.5rem', fontWeight: 700 }}>{t.total_vms}</span>
            </CardBody>
          </Card>
        </GalleryItem>
        <GalleryItem>
          <Card isCompact isFullHeight>
            <CardTitle style={{ fontSize: '0.85rem' }}>Sandboxes</CardTitle>
            <CardBody style={{ paddingTop: 0 }}>
              <span style={{ fontSize: '1.5rem', fontWeight: 700 }}>{t.sandboxes}</span>
              <div style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>active namespaces</div>
            </CardBody>
          </Card>
        </GalleryItem>
        <GalleryItem>
          <Card isCompact isFullHeight>
            <CardTitle style={{ fontSize: '0.85rem' }}>Failing</CardTitle>
            <CardBody style={{ paddingTop: 0 }}>
              <span style={{ fontSize: '1.5rem', fontWeight: 700, color: t.failing > 0 ? 'var(--sg-color--critical)' : undefined }}>{t.failing}</span>
              <div style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>sandboxes</div>
            </CardBody>
          </Card>
        </GalleryItem>
        <GalleryItem>
          <Card isCompact isFullHeight>
            <CardTitle style={{ fontSize: '0.85rem' }}>Crashlooping</CardTitle>
            <CardBody style={{ paddingTop: 0 }}>
              <span style={{ fontSize: '1.5rem', fontWeight: 700, color: t.crashloops > 0 ? 'var(--sg-color--critical)' : undefined }}>{t.crashloops}</span>
              <div style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>pods</div>
            </CardBody>
          </Card>
        </GalleryItem>
      </Gallery>

      <p style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)', marginBottom: '0.5rem' }}>Click a row to see recent pod failures</p>

      <div className="sg-table-wrap">
        <Table aria-label="Nodes and Pods" variant="compact">
          <Thead>
            <Tr>
              <Th>Cluster</Th>
              <Th>Status</Th>
              <Th>Nodes</Th>
              <Th>Compute</Th>
              <Th>CPU %</Th>
              <Th>Hot</Th>
              <Th>VMs</Th>
              <Th>VM/Node</Th>
              <Th>Sandboxes</Th>
              <Th>Failing</Th>
              <Th>Crashloop</Th>
              <Th>OCP4 Labs</Th>
              <Th>New Fail</Th>
              <Th>Recovered</Th>
            </Tr>
          </Thead>
          <Tbody>
            {data.clusters.map(c => (
              <>
                <Tr
                  key={c.cluster}
                  isClickable
                  isRowSelected={expanded === c.cluster}
                  onRowClick={() => setExpanded(expanded === c.cluster ? null : c.cluster)}
                >
                  <Td><strong style={{ color: 'var(--sg-color--info)' }}>{c.cluster}</strong></Td>
                  <Td><StatusLabel status={c.status} isCompact /></Td>
                  <Td>{c.nodes}</Td>
                  <Td>{c.compute_nodes}</Td>
                  <Td style={{ color: c.avg_cpu > 80 ? 'var(--sg-color--critical)' : c.avg_cpu > 60 ? 'var(--sg-color--warning)' : undefined }}>
                    <strong>{c.avg_cpu.toFixed(1)}%</strong>
                  </Td>
                  <Td style={{ color: c.hot_nodes > 0 ? 'var(--sg-color--critical)' : undefined }}>{c.hot_nodes}</Td>
                  <Td><strong>{c.total_vms}</strong></Td>
                  <Td style={{ color: c.vms_per_node > 100 ? 'var(--sg-color--critical)' : c.vms_per_node > 50 ? 'var(--sg-color--warning)' : undefined }}>
                    {c.vms_per_node.toFixed(1)}
                  </Td>
                  <Td>{c.sandbox_active}</Td>
                  <Td style={{ color: c.sandbox_failing > 0 ? 'var(--sg-color--critical)' : undefined }}>
                    <strong>{c.sandbox_failing}</strong>
                  </Td>
                  <Td style={{ color: c.crashloops > 0 ? 'var(--sg-color--critical)' : undefined }}>
                    <strong>{c.crashloops}</strong>
                  </Td>
                  <Td>{c.ocp4_labs}</Td>
                  <Td style={{ color: c.new_failures > 0 ? 'var(--sg-color--critical)' : undefined }}>
                    {c.new_failures > 0 ? <strong>{c.new_failures}</strong> : 0}
                  </Td>
                  <Td style={{ color: c.recovered > 0 ? 'var(--sg-color--healthy)' : undefined }}>
                    {c.recovered > 0 ? <strong>{c.recovered}</strong> : 0}
                  </Td>
                </Tr>
                {expanded === c.cluster && (
                  <Tr key={`${c.cluster}-detail`}>
                    <Td colSpan={14} style={{ background: 'var(--rh-color--surface-secondary, #f0f0f0)', padding: '0.75rem' }}>
                      <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap' }}>

                        {Object.keys(c.sandbox_by_type).length > 0 && (
                          <div>
                            <strong style={{ fontSize: '0.85rem' }}>Sandbox Types</strong>
                            <div style={{ marginTop: '0.25rem' }}>
                              {Object.entries(c.sandbox_by_type).sort(([,a],[,b]) => b - a).map(([type, count]) => (
                                <div key={type} style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', padding: '0.15rem 0', fontSize: '0.85rem' }}>
                                  <Label isCompact color="blue">{type}</Label>
                                  <strong>{count}</strong>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        <div>
                          <strong style={{ fontSize: '0.85rem' }}>Evaluations</strong>
                          <div style={{ marginTop: '0.25rem', fontSize: '0.85rem' }}>
                            <div>Total: <strong>{c.evaluations.total}</strong> ({c.evaluations.passed} pass, {c.evaluations.failed} fail)</div>
                            <div>Health: <strong style={{ color: c.evaluations.health_rate >= 90 ? 'var(--sg-color--healthy)' : c.evaluations.health_rate >= 70 ? 'var(--sg-color--warning)' : 'var(--sg-color--critical)' }}>{c.evaluations.health_rate}%</strong></div>
                            <div>Labs seen: {c.evaluations.labs_seen}, failing: <strong style={{ color: c.evaluations.labs_failing > 0 ? 'var(--sg-color--critical)' : undefined }}>{c.evaluations.labs_failing}</strong></div>
                          </div>
                        </div>

                        {Object.keys(c.evaluations.top_failures).length > 0 && (
                          <div>
                            <strong style={{ fontSize: '0.85rem' }}>Top Failures</strong>
                            <div style={{ marginTop: '0.25rem' }}>
                              {Object.entries(c.evaluations.top_failures).map(([fc, count]) => (
                                <div key={fc} style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', padding: '0.15rem 0', fontSize: '0.85rem' }}>
                                  <span style={{ color: 'var(--sg-color--critical)' }}>{fc}</span>
                                  <strong>{count}</strong>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {c.recent_failures.length > 0 && (
                          <div>
                            <strong style={{ fontSize: '0.85rem' }}>Recent Pod Failures</strong>
                            <div style={{ marginTop: '0.25rem' }}>
                              {c.recent_failures.map((f, i) => (
                                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem', padding: '0.15rem 0', fontSize: '0.8rem' }}>
                                  <span style={{ wordBreak: 'break-all' }}>{f.pod.split('/').pop()}</span>
                                  <Label isCompact color="red">{f.status}</Label>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </Td>
                  </Tr>
                )}
              </>
            ))}
          </Tbody>
        </Table>
      </div>
    </div>
  );
}
