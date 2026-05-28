import {
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
} from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import { useDeploymentsDashboard } from '../api/hooks';
import type { PoolEntry, PoolsDashboard } from '../api/types';
import StatusLabel from './StatusLabel';
import AIAnalysis from './AIAnalysis';

interface Props {
  pool: PoolEntry;
  dashboard: PoolsDashboard;
}

export default function PoolDrawer({ pool, dashboard }: Props) {
  const prov = dashboard.provisioning;
  const byState = prov.by_state;
  const { data: summit } = useDeploymentsDashboard();

  const dependentLabs = (summit?.labs ?? []).filter(l => {
    const poolName = pool.name.toLowerCase();
    const labCode = l.lab_code.toLowerCase();
    return poolName.includes(labCode.replace('lb', 'lb'));
  });

  return (
    <div style={{ padding: '0.5rem' }}>
      <h4 style={{ marginBottom: '0.5rem' }}>Pool: {pool.name}</h4>
      <DescriptionList isHorizontal isCompact>
        <DescriptionListGroup>
          <DescriptionListTerm>Status</DescriptionListTerm>
          <DescriptionListDescription><StatusLabel status={pool.status} isCompact /></DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Available</DescriptionListTerm>
          <DescriptionListDescription><strong>{pool.available}</strong></DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Ready</DescriptionListTerm>
          <DescriptionListDescription>{pool.ready}</DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Minimum Required</DescriptionListTerm>
          <DescriptionListDescription>{pool.min}</DescriptionListDescription>
        </DescriptionListGroup>
      </DescriptionList>

      <h4 style={{ marginTop: '1.5rem', marginBottom: '0.5rem' }}>Platform Provisioning</h4>
      <DescriptionList isHorizontal isCompact>
        <DescriptionListGroup>
          <DescriptionListTerm>Total</DescriptionListTerm>
          <DescriptionListDescription>{prov.total}</DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Started</DescriptionListTerm>
          <DescriptionListDescription><strong style={{ color: 'var(--sg-color--healthy)' }}>{prov.started}</strong></DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Failed</DescriptionListTerm>
          <DescriptionListDescription><strong style={{ color: prov.failed > 0 ? 'var(--sg-color--critical)' : undefined }}>{prov.failed}</strong></DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Failure Rate</DescriptionListTerm>
          <DescriptionListDescription>{prov.failure_rate.toFixed(1)}%</DescriptionListDescription>
        </DescriptionListGroup>
      </DescriptionList>

      {Object.keys(byState).length > 0 && (
        <>
          <h4 style={{ marginTop: '1.5rem', marginBottom: '0.5rem' }}>State Distribution</h4>
          <div style={{ fontSize: '0.9rem' }}>
            {Object.entries(byState)
              .sort(([, a], [, b]) => b - a)
              .map(([state, count]) => (
                <div key={state} style={{ display: 'flex', justifyContent: 'space-between', padding: '0.15rem 0' }}>
                  <span>{state}</span>
                  <strong>{count}</strong>
                </div>
              ))}
          </div>
        </>
      )}

      {dependentLabs.length > 0 && (
        <>
          <h4 style={{ marginTop: '1.5rem', marginBottom: '0.5rem' }}>Dependent Labs ({dependentLabs.length})</h4>
          <Table aria-label="Dependent labs" variant="compact">
            <Thead><Tr><Th>Lab</Th><Th>Title</Th><Th>Sessions</Th></Tr></Thead>
            <Tbody>
              {dependentLabs.map(l => (
                <Tr key={l.lab_code}>
                  <Td><strong style={{ color: 'var(--sg-color--info)' }}>{l.lab_code}</strong></Td>
                  <Td style={{ maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{l.title}</Td>
                  <Td>{l.sessions}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </>
      )}

      <AIAnalysis contextType="pool" poolName={pool.name} />
    </div>
  );
}
