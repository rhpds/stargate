import {
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Spinner,
} from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import { useClusterSummary, useClusterFailures, useEvents } from '../api/hooks';
import type { ClusterScan } from '../api/types';
import AIAnalysis from './AIAnalysis';
import StatusLabel from './StatusLabel';

interface Props {
  cluster: ClusterScan;
}

export default function ClusterDrawer({ cluster }: Props) {
  const { data: summary, isLoading: loadingSummary } = useClusterSummary(cluster.cluster);
  const { data: failures } = useClusterFailures(cluster.cluster);
  const { data: events } = useEvents({ cluster: cluster.cluster, limit: '10' });

  return (
    <div style={{ padding: '0.5rem' }}>
      <h4 style={{ marginBottom: '0.5rem' }}>Infrastructure</h4>
      <DescriptionList isHorizontal isCompact>
        <DescriptionListGroup><DescriptionListTerm>Status</DescriptionListTerm><DescriptionListDescription><StatusLabel status={cluster.status} isCompact /></DescriptionListDescription></DescriptionListGroup>
        <DescriptionListGroup><DescriptionListTerm>CPU</DescriptionListTerm><DescriptionListDescription><strong>{cluster.avg_cpu_pct.toFixed(1)}%</strong></DescriptionListDescription></DescriptionListGroup>
        <DescriptionListGroup><DescriptionListTerm>Hot Nodes</DescriptionListTerm><DescriptionListDescription>{cluster.hot_nodes}</DescriptionListDescription></DescriptionListGroup>
        <DescriptionListGroup><DescriptionListTerm>Total VMs</DescriptionListTerm><DescriptionListDescription>{cluster.total_vms}</DescriptionListDescription></DescriptionListGroup>
        <DescriptionListGroup><DescriptionListTerm>VMs/Node</DescriptionListTerm><DescriptionListDescription>{cluster.vms_per_node.toFixed(1)}</DescriptionListDescription></DescriptionListGroup>
        <DescriptionListGroup><DescriptionListTerm>Labs Active</DescriptionListTerm><DescriptionListDescription>{cluster.sandbox_active}</DescriptionListDescription></DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Sandbox Failing</DescriptionListTerm>
          <DescriptionListDescription style={{ color: (cluster.sandbox_failing ?? 0) > 0 ? 'var(--sg-color--critical)' : undefined }}>
            <strong>{cluster.sandbox_failing ?? 0}</strong>
          </DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Crashlooping</DescriptionListTerm>
          <DescriptionListDescription style={{ color: (cluster.sandbox_crashloop ?? 0) > 0 ? 'var(--sg-color--critical)' : undefined }}>
            <strong>{cluster.sandbox_crashloop ?? 0}</strong>
          </DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup><DescriptionListTerm>DNS Warnings</DescriptionListTerm><DescriptionListDescription>{cluster.dns_warnings}</DescriptionListDescription></DescriptionListGroup>
      </DescriptionList>

      {cluster.issues.length > 0 && (
        <>
          <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Issues</h4>
          <ul style={{ paddingLeft: '1.2rem', fontSize: '0.9rem' }}>
            {cluster.issues.map((issue, i) => <li key={i} style={{ color: 'var(--sg-color--critical)' }}>{issue}</li>)}
          </ul>
        </>
      )}

      {loadingSummary && <Spinner size="md" style={{ marginTop: '1rem' }} />}

      {summary && (
        <>
          <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Evaluations</h4>
          <DescriptionList isHorizontal isCompact>
            <DescriptionListGroup><DescriptionListTerm>Total</DescriptionListTerm><DescriptionListDescription>{summary.total_evaluations}</DescriptionListDescription></DescriptionListGroup>
            <DescriptionListGroup><DescriptionListTerm>Health Rate</DescriptionListTerm><DescriptionListDescription><strong style={{ color: summary.health_rate >= 80 ? 'var(--sg-color--healthy)' : 'var(--sg-color--warning)' }}>{summary.health_rate.toFixed(1)}%</strong></DescriptionListDescription></DescriptionListGroup>
            <DescriptionListGroup><DescriptionListTerm>Labs Failing</DescriptionListTerm><DescriptionListDescription>{summary.labs_failing}</DescriptionListDescription></DescriptionListGroup>
          </DescriptionList>
        </>
      )}

      {failures && Object.keys(failures).length > 0 && (
        <>
          <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Failure Classes</h4>
          <Table aria-label="Failures" variant="compact">
            <Thead><Tr><Th>Class</Th><Th>Count</Th></Tr></Thead>
            <Tbody>
              {Object.entries(failures).sort(([, a], [, b]) => b - a).map(([cls, count]) => (
                <Tr key={cls}><Td style={{ fontSize: '0.85rem' }}>{cls}</Td><Td>{count}</Td></Tr>
              ))}
            </Tbody>
          </Table>
        </>
      )}

      {events && events.length > 0 && (
        <>
          <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Recent Events</h4>
          <Table aria-label="Events" variant="compact">
            <Thead><Tr><Th>Time</Th><Th>Type</Th><Th>Failure</Th></Tr></Thead>
            <Tbody>
              {events.slice(0, 10).map(evt => (
                <Tr key={evt.event_id}>
                  <Td style={{ fontSize: '0.8rem' }}>{new Date(evt.timestamp).toLocaleString()}</Td>
                  <Td><StatusLabel status={evt.event_type.split('.')[1] ?? evt.event_type} isCompact /></Td>
                  <Td style={{ fontSize: '0.85rem' }}>{evt.failure_class || '-'}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </>
      )}

      <AIAnalysis contextType="cluster" clusterName={cluster.cluster} />
    </div>
  );
}
