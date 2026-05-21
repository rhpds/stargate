import { useState } from 'react';
import {
  Card,
  CardBody,
  CardTitle,
  Label,
  PageSection,
  Spinner,
  TextInput,
} from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import { useLabsPipeline } from '../api/hooks';
import type { LabPipelineEntry, LabPipelineStageStatus } from '../api/types';

const STAGE_SHORT: Record<string, string> = {
  'cluster-health': 'Cluster',
  'run-created': 'Run',
  'provision-complete': 'Provision',
  'namespace-ready': 'NS',
  'deployment-ready': 'Deploy',
  'storage-clone-ready': 'Storage',
  'route-ready': 'Route',
  'vm-runtime-ready': 'VM',
  'smoke-test-ready': 'Smoke',
  'showroom-healthy': 'Show',
  'model-endpoint-ready': 'Model',
};

function outcomeColor(outcome: string | null | undefined): string {
  if (!outcome) return 'var(--rh-color--border, #d2d2d2)';
  switch (outcome) {
    case 'pass': return 'var(--sg-color--healthy, #3e8635)';
    case 'fail': return 'var(--sg-color--critical, #c9190b)';
    case 'warn': return 'var(--sg-color--warning, #f0ab00)';
    default: return 'var(--rh-color--border, #d2d2d2)';
  }
}

function outcomeBg(outcome: string | null | undefined): string {
  if (!outcome) return '#f0f0f0';
  switch (outcome) {
    case 'pass': return '#f3faf2';
    case 'fail': return '#fceaea';
    case 'warn': return '#fff4e6';
    default: return '#f0f0f0';
  }
}

function outcomeIcon(outcome: string | null | undefined): string {
  if (!outcome) return '—';
  switch (outcome) {
    case 'pass': return '✓';
    case 'fail': return '✗';
    case 'warn': return '⚠';
    default: return '—';
  }
}

type SortKey = 'lab_code' | 'fail_count' | 'pass_count' | 'health';

export default function LabPipelineMatrix() {
  const { data, isLoading } = useLabsPipeline();
  const [expandedLab, setExpandedLab] = useState<string | null>(null);
  const [filter, setFilter] = useState('');
  const [sortBy, setSortBy] = useState<SortKey>('fail_count');
  const [sortAsc, setSortAsc] = useState(false);

  if (isLoading) return <PageSection><Spinner size="xl" /></PageSection>;
  if (!data || data.labs.length === 0) {
    return (
      <PageSection>
        <Card><CardBody><em style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>No lab pipeline data. Evaluations populate as scanners collect namespace evidence.</em></CardBody></Card>
      </PageSection>
    );
  }

  const stages = data.stage_order;

  let labs = [...data.labs];
  if (filter) {
    const f = filter.toLowerCase();
    labs = labs.filter(l =>
      l.lab_code.toLowerCase().includes(f) ||
      l.title.toLowerCase().includes(f) ||
      (l.cluster || '').toLowerCase().includes(f)
    );
  }

  labs.sort((a, b) => {
    let cmp = 0;
    switch (sortBy) {
      case 'lab_code': cmp = a.lab_code.localeCompare(b.lab_code); break;
      case 'fail_count': cmp = a.fail_count - b.fail_count; break;
      case 'pass_count': cmp = a.pass_count - b.pass_count; break;
      case 'health': cmp = a.health_pct - b.health_pct; break;
    }
    return sortAsc ? cmp : -cmp;
  });

  const handleSort = (key: SortKey) => {
    if (sortBy === key) setSortAsc(!sortAsc);
    else { setSortBy(key); setSortAsc(false); }
  };

  const totalPass = data.labs.reduce((s, l) => s + l.pass_count, 0);
  const totalFail = data.labs.reduce((s, l) => s + l.fail_count, 0);

  return (
    <>
      {/* Summary bar */}
      <PageSection style={{ paddingBottom: 0 }}>
        <div style={{ display: 'flex', gap: '2rem', alignItems: 'center', flexWrap: 'wrap', marginBottom: '1rem' }}>
          <div style={{ display: 'flex', gap: '1rem' }}>
            <Label color="green" isCompact>{totalPass} passing stages</Label>
            <Label color="red" isCompact>{totalFail} failing stages</Label>
            <Label color="grey" isCompact>{data.total_labs} labs with evaluations</Label>
          </div>
          <TextInput
            type="text"
            placeholder="Filter by lab, title, or cluster..."
            value={filter}
            onChange={(_e, val) => setFilter(val)}
            style={{ maxWidth: '300px' }}
          />
        </div>
      </PageSection>

      {/* Heatmap matrix */}
      <PageSection style={{ paddingTop: 0 }}>
        <Card>
          <CardTitle>Lab Pipeline Matrix</CardTitle>
          <CardBody>
            <div className="sg-table-wrap">
              <Table aria-label="Lab pipeline matrix" variant="compact">
                <Thead>
                  <Tr>
                    <Th sort={{ sortBy: { index: 0, direction: sortBy === 'lab_code' ? (sortAsc ? 'asc' : 'desc') : 'asc' }, onSort: () => handleSort('lab_code'), columnIndex: 0 }}>Lab</Th>
                    {stages.map(s => (
                      <Th key={s} style={{ textAlign: 'center', fontSize: '0.75rem', padding: '6px 4px', whiteSpace: 'nowrap' }}>
                        {STAGE_SHORT[s] || s}
                      </Th>
                    ))}
                    <Th sort={{ sortBy: { index: 12, direction: sortBy === 'health' ? (sortAsc ? 'asc' : 'desc') : 'asc' }, onSort: () => handleSort('health'), columnIndex: 12 }} style={{ textAlign: 'center' }}>Health</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {labs.map(lab => {
                    const isExpanded = expandedLab === lab.lab_code;
                    return (
                      <>
                        <Tr
                          key={lab.lab_code}
                          isClickable
                          onRowClick={() => setExpandedLab(isExpanded ? null : lab.lab_code)}
                          style={{ cursor: 'pointer', borderLeft: lab.fail_count > 0 ? '3px solid var(--sg-color--critical)' : lab.warn_count > 0 ? '3px solid var(--sg-color--warning)' : undefined }}
                        >
                          <Td style={{ whiteSpace: 'nowrap', maxWidth: '200px' }}>
                            <div style={{ fontWeight: 600, fontSize: '0.85rem' }}>{lab.lab_code}</div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--rh-color--text-secondary, #6a6e73)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {lab.title || '—'}
                            </div>
                          </Td>
                          {stages.map(stageId => {
                            const stage = lab.stages[stageId] as LabPipelineStageStatus | null | undefined;
                            const outcome = stage?.outcome || null;
                            return (
                              <Td key={stageId} style={{
                                textAlign: 'center',
                                padding: '4px',
                                backgroundColor: outcomeBg(outcome),
                                borderLeft: '1px solid #fff',
                              }}>
                                <span style={{
                                  color: outcomeColor(outcome),
                                  fontWeight: outcome === 'fail' ? 700 : 400,
                                  fontSize: '0.9rem',
                                }}>
                                  {outcomeIcon(outcome)}
                                </span>
                              </Td>
                            );
                          })}
                          <Td style={{ textAlign: 'center', fontWeight: 600, color: lab.health_pct >= 80 ? 'var(--sg-color--healthy)' : lab.health_pct >= 50 ? 'var(--sg-color--warning)' : 'var(--sg-color--critical)' }}>
                            {(lab.pass_count + lab.warn_count + lab.fail_count) > 0 ? `${lab.health_pct}%` : '—'}
                          </Td>
                        </Tr>
                        {isExpanded && (
                          <Tr key={`${lab.lab_code}-expanded`}>
                            <Td colSpan={stages.length + 2} style={{ padding: '1rem', backgroundColor: '#f8f9fa' }}>
                              <PipelineFlowDiagram lab={lab} stages={stages} />
                            </Td>
                          </Tr>
                        )}
                      </>
                    );
                  })}
                </Tbody>
              </Table>
            </div>
          </CardBody>
        </Card>
      </PageSection>
    </>
  );
}

function PipelineFlowDiagram({ lab, stages }: { lab: LabPipelineEntry; stages: string[] }) {
  let hitFirstFail = false;

  return (
    <div>
      <div style={{ marginBottom: '0.75rem', fontSize: '0.9rem' }}>
        <strong>{lab.lab_code}</strong> — {lab.title || 'Untitled'}
        {lab.cluster && <span style={{ marginLeft: '1rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>Cluster: {lab.cluster}</span>}
        {lab.sessions > 0 && <span style={{ marginLeft: '1rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>{lab.sessions} session(s)</span>}
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0', overflowX: 'auto', paddingBottom: '0.5rem' }}>
        {stages.map((stageId, i) => {
          const stage = lab.stages[stageId] as LabPipelineStageStatus | null | undefined;
          const outcome = stage?.outcome || null;
          const isBlocked = outcome === 'fail' && !hitFirstFail;
          if (outcome === 'fail') hitFirstFail = true;
          const isAfterBlock = hitFirstFail && outcome !== 'fail';
          const opacity = (!outcome || isAfterBlock) ? 0.4 : 1;

          return (
            <div key={stageId} style={{ display: 'flex', alignItems: 'center' }}>
              {/* Stage node */}
              <div style={{
                display: 'flex', flexDirection: 'column', alignItems: 'center',
                minWidth: '80px', opacity,
              }}>
                <div style={{
                  width: '70px', height: '36px',
                  borderRadius: '6px',
                  border: `2px solid ${isBlocked ? '#c9190b' : outcomeColor(outcome)}`,
                  backgroundColor: isBlocked ? '#fceaea' : outcomeBg(outcome),
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: '0.7rem', fontWeight: 600, textAlign: 'center',
                  padding: '2px 4px',
                  boxShadow: isBlocked ? '0 0 6px rgba(201,25,11,0.3)' : undefined,
                }}>
                  {STAGE_SHORT[stageId] || stageId}
                </div>
                <div style={{ fontSize: '0.75rem', marginTop: '4px', color: outcomeColor(outcome), fontWeight: outcome === 'fail' ? 700 : 400 }}>
                  {outcomeIcon(outcome)} {outcome || 'none'}
                </div>
                {stage?.failure_class && (
                  <div style={{ fontSize: '0.65rem', color: 'var(--sg-color--critical)', marginTop: '2px', maxWidth: '80px', textAlign: 'center', wordBreak: 'break-all' }}>
                    {stage.failure_class}
                  </div>
                )}
                {stage?.evaluated_at && (
                  <div style={{ fontSize: '0.6rem', color: 'var(--rh-color--text-secondary, #6a6e73)', marginTop: '2px' }}>
                    {new Date(stage.evaluated_at).toLocaleTimeString()}
                  </div>
                )}
              </div>
              {/* Arrow connector */}
              {i < stages.length - 1 && (
                <div style={{ display: 'flex', alignItems: 'center', padding: '0 2px', opacity: 0.4 }}>
                  <svg width="20" height="12" viewBox="0 0 20 12">
                    <line x1="0" y1="6" x2="14" y2="6" stroke="#6a6e73" strokeWidth="1.5" />
                    <polygon points="14,2 20,6 14,10" fill="#6a6e73" />
                  </svg>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
