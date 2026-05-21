import { useState } from 'react';
import {
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Label,
  Spinner,
} from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import { usePipelineStage } from '../api/hooks';
import type { PipelineStage } from '../api/types';
import StatusLabel from './StatusLabel';
import AIAnalysis from './AIAnalysis';

const STAGE_LABELS: Record<string, string> = {
  'cluster-health': 'Cluster Health',
  'run-created': 'Run Created',
  'provision-complete': 'Provision Complete',
  'namespace-ready': 'Namespace Ready',
  'deployment-ready': 'Deployment Ready',
  'storage-clone-ready': 'Storage Clone Ready',
  'route-ready': 'Route Ready',
  'vm-runtime-ready': 'VM Runtime Ready',
  'smoke-test-ready': 'Smoke Test Ready',
  'showroom-healthy': 'Showroom Healthy',
  'model-endpoint-ready': 'Model Endpoint Ready',
};

interface Props {
  stage: PipelineStage;
}

export default function PipelineDrawer({ stage }: Props) {
  const { data, isLoading } = usePipelineStage(stage.stage_id);
  const [expandedRow, setExpandedRow] = useState<number | null>(null);

  return (
    <div style={{ padding: '0.5rem' }}>
      <h4 style={{ marginBottom: '0.5rem' }}>{STAGE_LABELS[stage.stage_id] ?? stage.stage_id}</h4>
      <DescriptionList isHorizontal isCompact>
        <DescriptionListGroup>
          <DescriptionListTerm>Health</DescriptionListTerm>
          <DescriptionListDescription>
            <strong style={{ color: (stage.health_rate ?? 0) >= 95 ? 'var(--sg-color--healthy)' : (stage.health_rate ?? 0) >= 80 ? 'var(--sg-color--warning)' : 'var(--sg-color--critical)' }}>
              {stage.health_rate != null ? `${stage.health_rate}%` : '-'}
            </strong>
          </DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>Evaluations</DescriptionListTerm>
          <DescriptionListDescription>
            <Label isCompact color="green">{stage.pass} pass</Label>{' '}
            <Label isCompact color="orange">{stage.warn} warn</Label>{' '}
            <Label isCompact color="red">{stage.fail} fail</Label>{' '}
            of {stage.total}
          </DescriptionListDescription>
        </DescriptionListGroup>
      </DescriptionList>

      {isLoading && <Spinner size="md" style={{ marginTop: '1rem' }} />}

      {data && Object.keys(data.failure_classes).length > 0 && (
        <>
          <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Failure Classes</h4>
          <Table aria-label="Failure classes" variant="compact">
            <Thead><Tr><Th>Class</Th><Th>Count</Th><Th>% of Failures</Th></Tr></Thead>
            <Tbody>
              {Object.entries(data.failure_classes).map(([fc, count]) => (
                <Tr key={fc}>
                  <Td><strong style={{ color: 'var(--sg-color--critical)' }}>{fc}</strong></Td>
                  <Td>{count}</Td>
                  <Td>{data.failed > 0 ? `${Math.round(count / data.failed * 100)}%` : '-'}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </>
      )}

      {data && Object.keys(data.clusters_affected).length > 0 && (
        <>
          <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Clusters</h4>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {Object.entries(data.clusters_affected).map(([cluster, count]) => (
              <Label key={cluster} isCompact color="blue">{cluster} ({count})</Label>
            ))}
          </div>
        </>
      )}

      {data && data.recent_evaluations.length > 0 && (
        <>
          <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Recent Evaluations</h4>
          <p style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)', marginBottom: '0.5rem' }}>Click a row to expand details</p>
          <Table aria-label="Recent evaluations" variant="compact">
            <Thead><Tr><Th>Time</Th><Th>Outcome</Th><Th>Failure</Th><Th>Cluster</Th><Th>Sandbox</Th></Tr></Thead>
            <Tbody>
              {data.recent_evaluations.map((e, i) => (
                <>
                  <Tr key={i} isClickable onRowClick={() => setExpandedRow(expandedRow === i ? null : i)} style={{ cursor: 'pointer' }}>
                    <Td style={{ fontSize: '0.8rem' }}>{e.evaluated_at ? new Date(e.evaluated_at).toLocaleString() : '-'}</Td>
                    <Td><StatusLabel status={e.outcome} isCompact /></Td>
                    <Td style={{ fontSize: '0.85rem' }}>{e.failure_class || '-'}</Td>
                    <Td style={{ fontSize: '0.85rem' }}>{e.cluster_name || '-'}</Td>
                    <Td style={{ fontSize: '0.8rem' }}>{e.lab_code || '-'}</Td>
                  </Tr>
                  {expandedRow === i && (
                    <Tr key={`${i}-detail`}>
                      <Td colSpan={5} style={{ background: 'var(--rh-color--surface-secondary, #f0f0f0)', padding: '0.75rem' }}>
                        <div style={{ fontSize: '0.85rem' }}>
                          <DescriptionList isHorizontal isCompact>
                            <DescriptionListGroup>
                              <DescriptionListTerm>Run ID</DescriptionListTerm>
                              <DescriptionListDescription style={{ fontSize: '0.8rem', wordBreak: 'break-all' }}>{e.run_id}</DescriptionListDescription>
                            </DescriptionListGroup>
                            <DescriptionListGroup>
                              <DescriptionListTerm>Sandbox</DescriptionListTerm>
                              <DescriptionListDescription>{e.lab_code || '-'}</DescriptionListDescription>
                            </DescriptionListGroup>
                            <DescriptionListGroup>
                              <DescriptionListTerm>Cluster</DescriptionListTerm>
                              <DescriptionListDescription>{e.cluster_name || '-'}</DescriptionListDescription>
                            </DescriptionListGroup>
                            <DescriptionListGroup>
                              <DescriptionListTerm>Outcome</DescriptionListTerm>
                              <DescriptionListDescription><StatusLabel status={e.outcome} /></DescriptionListDescription>
                            </DescriptionListGroup>
                            {e.failure_class && (
                              <DescriptionListGroup>
                                <DescriptionListTerm>Failure Class</DescriptionListTerm>
                                <DescriptionListDescription><Label color="red">{e.failure_class}</Label></DescriptionListDescription>
                              </DescriptionListGroup>
                            )}
                            <DescriptionListGroup>
                              <DescriptionListTerm>Message</DescriptionListTerm>
                              <DescriptionListDescription style={{ fontSize: '0.85rem' }}>{e.message || '-'}</DescriptionListDescription>
                            </DescriptionListGroup>
                          </DescriptionList>
                        </div>
                      </Td>
                    </Tr>
                  )}
                </>
              ))}
            </Tbody>
          </Table>
        </>
      )}

      <AIAnalysis contextType="error" failureClass={stage.stage_id} />
    </div>
  );
}
