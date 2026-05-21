import { Label, Progress } from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import type { PipelineStage } from '../api/types';

const STAGE_LABELS: Record<string, string> = {
  'cluster-health': 'Cluster Health',
  'run-created': 'Run Created',
  'provision-complete': 'Provision Complete',
  'namespace-ready': 'Namespace Ready',
  'deployment-ready': 'Deployment Ready',
  'storage-clone-ready': 'Storage Clone',
  'route-ready': 'Route Ready',
  'vm-runtime-ready': 'VM Runtime',
  'smoke-test-ready': 'Smoke Test',
  'showroom-healthy': 'Showroom Health',
  'model-endpoint-ready': 'Model Endpoint',
};

const STAGE_ORDER = [
  'cluster-health', 'run-created', 'provision-complete', 'namespace-ready',
  'deployment-ready', 'storage-clone-ready', 'route-ready', 'vm-runtime-ready',
  'smoke-test-ready', 'showroom-healthy', 'model-endpoint-ready',
];

interface Props {
  stages: PipelineStage[];
  compact?: boolean;
  onSelect?: (stage: PipelineStage) => void;
  selectedStage?: string | null;
}

export default function StagePipeline({ stages, compact = false, onSelect, selectedStage }: Props) {
  const ordered = STAGE_ORDER.map(id => stages.find(s => s.stage_id === id)).filter(Boolean) as PipelineStage[];

  if (ordered.length === 0) {
    return <em style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>No pipeline data available.</em>;
  }

  if (compact) {
    const active = ordered.filter(s => s.total > 0);
    if (active.length === 0) return <em style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>No evaluations yet.</em>;
    return (
      <div>
        {active.map(s => {
          const pct = s.total > 0 ? Math.round((s.pass + s.warn) / s.total * 100) : 0;
          return (
            <div key={s.stage_id} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.4rem', fontSize: '0.85rem' }}>
              <span style={{ minWidth: 90, fontWeight: 600 }}>{STAGE_LABELS[s.stage_id] ?? s.stage_id}</span>
              <Progress
                value={pct}
                size="sm"
                style={{ flex: 1, minWidth: 80 }}
                variant={pct === 100 ? undefined : pct >= 80 ? 'warning' : 'danger'}
              />
              <span style={{ minWidth: 60, textAlign: 'right', fontSize: '0.8rem' }}>
                {s.pass}/{s.total}
              </span>
            </div>
          );
        })}
      </div>
    );
  }

  const totalEvals = ordered.reduce((sum, s) => sum + s.total, 0);

  return (
    <div>
      <div style={{ display: 'flex', gap: '2rem', marginBottom: '1rem', fontSize: '0.9rem' }}>
        <span><strong>{totalEvals}</strong> total evaluations</span>
        <span><Label isCompact color="green">{ordered.reduce((s, x) => s + x.pass, 0)} passed</Label></span>
        <span><Label isCompact color="orange">{ordered.reduce((s, x) => s + x.warn, 0)} warned</Label></span>
        <span><Label isCompact color="red">{ordered.reduce((s, x) => s + x.fail, 0)} failed</Label></span>
      </div>

      <Table aria-label="Pipeline stages" variant="compact">
        <Thead>
          <Tr>
            <Th>Stage</Th>
            <Th>Order</Th>
            <Th>Pass</Th>
            <Th>Warn</Th>
            <Th>Fail</Th>
            <Th>Total</Th>
            <Th>Health</Th>
            <Th>Pass Rate</Th>
          </Tr>
        </Thead>
        <Tbody>
          {ordered.map((s, i) => {
            const pct = s.total > 0 ? Math.round((s.pass + s.warn) / s.total * 100) : null;
            return (
              <Tr key={s.stage_id} isClickable={!!onSelect} isRowSelected={s.stage_id === selectedStage} onRowClick={onSelect ? () => onSelect(s) : undefined}>
                <Td><strong>{STAGE_LABELS[s.stage_id] ?? s.stage_id}</strong></Td>
                <Td>{i + 1}</Td>
                <Td style={{ color: s.pass > 0 ? 'var(--sg-color--healthy)' : undefined }}><strong>{s.pass}</strong></Td>
                <Td style={{ color: s.warn > 0 ? 'var(--sg-color--warning)' : undefined }}>{s.warn}</Td>
                <Td style={{ color: s.fail > 0 ? 'var(--sg-color--critical)' : undefined }}><strong>{s.fail}</strong></Td>
                <Td>{s.total || <span style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>-</span>}</Td>
                <Td>
                  {s.health_rate != null ? (
                    <strong style={{ color: s.health_rate >= 95 ? 'var(--sg-color--healthy)' : s.health_rate >= 80 ? 'var(--sg-color--warning)' : 'var(--sg-color--critical)' }}>
                      {s.health_rate}%
                    </strong>
                  ) : <span style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>-</span>}
                </Td>
                <Td style={{ minWidth: 120 }}>
                  {pct != null ? (
                    <Progress value={pct} size="sm" variant={pct >= 95 ? undefined : pct >= 80 ? 'warning' : 'danger'} />
                  ) : <span style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>No data</span>}
                </Td>
              </Tr>
            );
          })}
        </Tbody>
      </Table>
    </div>
  );
}
