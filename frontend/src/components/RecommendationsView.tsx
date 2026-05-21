import { useState, useMemo } from 'react';
import {
  Card,
  CardBody,
  CardTitle,
  Label,
  SearchInput,
  Select,
  SelectOption,
  MenuToggle,
  Spinner,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
} from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import { useRecommendations, useEvaluationMatrix, usePipeline } from '../api/hooks';
import type { Recommendation, PipelineStage } from '../api/types';
import StagePipeline from './StagePipeline';

const TYPE_LABELS: Record<string, string> = {
  provision_blocked_lab: 'Blocked Lab',
  cleanup_stuck: 'Stuck Instances',
  pool_exhaustion: 'Pool Exhaustion',
  cluster_capacity: 'Cluster Capacity',
  smoke_test_failing: 'Smoke Test Failing',
};

const URGENCY_COLORS: Record<string, 'red' | 'orange' | 'yellow' | 'grey'> = {
  critical: 'red',
  high: 'orange',
  medium: 'yellow',
  low: 'grey',
};

const STAGE_LABELS: Record<string, string> = {
  'cluster-health': 'Cluster',
  'run-created': 'Run',
  'provision-complete': 'Provision',
  'namespace-ready': 'NS',
  'deployment-ready': 'Deploy',
  'storage-clone-ready': 'Storage',
  'route-ready': 'Route',
  'vm-runtime-ready': 'VM',
  'smoke-test-ready': 'Smoke',
  'showroom-healthy': 'Showroom',
  'model-endpoint-ready': 'Model',
};

const OUTCOME_COLORS: Record<string, string> = {
  pass: 'var(--sg-color--healthy, #3e8635)',
  warn: 'var(--sg-color--warning, #f0ab00)',
  fail: 'var(--sg-color--critical, #c9190b)',
};

function getTarget(r: Recommendation): string {
  if (r.lab_code) return r.lab_code;
  if (r.cluster) return r.cluster;
  if (r.pool_name) return r.pool_name;
  return '';
}

interface Props {
  onSelectPipelineStage?: (stage: PipelineStage) => void;
  onSelectRecommendation?: (rec: Recommendation) => void;
  selectedStage?: string | null;
  selectedRecommendation?: Recommendation | null;
}

export default function RecommendationsView({ onSelectPipelineStage, onSelectRecommendation, selectedStage, selectedRecommendation }: Props) {
  const { data: recs, isLoading: loadingRecs } = useRecommendations();
  const { data: matrix, isLoading: loadingMatrix } = useEvaluationMatrix();
  const { data: pipeline, isLoading: loadingPipeline } = usePipeline();

  const [search, setSearch] = useState('');
  const [urgencyFilter, setUrgencyFilter] = useState<string>('all');
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [urgencyOpen, setUrgencyOpen] = useState(false);
  const [typeOpen, setTypeOpen] = useState(false);

  const filtered = useMemo(() => {
    if (!recs) return [];
    return recs.recommendations.filter(r => {
      if (urgencyFilter !== 'all' && r.urgency !== urgencyFilter) return false;
      if (typeFilter !== 'all' && r.type !== typeFilter) return false;
      if (search) {
        const s = search.toLowerCase();
        return r.recommendation.toLowerCase().includes(s)
          || getTarget(r).toLowerCase().includes(s)
          || (r.title || '').toLowerCase().includes(s);
      }
      return true;
    });
  }, [recs, search, urgencyFilter, typeFilter]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

      {/* Section 1: Policy Recommendations */}
      <Card>
        <CardTitle>
          Policy Recommendations
          {recs && (
            <span style={{ marginLeft: '1rem', fontWeight: 400, fontSize: '0.9rem' }}>
              <Label isCompact color="red" style={{ marginRight: 6 }}>{recs.critical} critical</Label>
              <Label isCompact color="orange" style={{ marginRight: 6 }}>{recs.high} high</Label>
              <Label isCompact color="grey" style={{ marginRight: 6 }}>{recs.medium} medium</Label>
              {(recs as any).escalated_count > 0 && <Label isCompact color="purple" style={{ marginRight: 6 }}>{(recs as any).escalated_count} escalated</Label>}
              <span style={{ color: 'var(--rh-color--text-secondary, #6a6e73)', fontSize: '0.8rem' }}>
                Generated {new Date(recs.generated_at).toLocaleString()}
              </span>
            </span>
          )}
        </CardTitle>
        <CardBody>
          {loadingRecs ? <Spinner size="lg" /> : (
            <>
              {/* Top Recommendation Cards */}
              {filtered.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginBottom: '1.5rem' }}>
                  {filtered.slice(0, 3).map((r, i) => {
                    const evidence = r.evidence || {};
                    const sources = Object.keys(evidence).filter(k => k.startsWith('source_'));
                    void (r as any).aap_provision_failures;
                    return (
                      <div key={i} style={{
                        padding: '1rem', borderRadius: '8px',
                        border: `2px solid ${r.urgency === 'critical' ? '#c9190b' : r.urgency === 'high' ? '#f0ab00' : '#d2d2d2'}`,
                        background: r.urgency === 'critical' ? '#fceaea' : r.urgency === 'high' ? '#fff4e6' : '#f8f9fa',
                        cursor: onSelectRecommendation ? 'pointer' : undefined,
                      }} onClick={onSelectRecommendation ? () => onSelectRecommendation(r) : undefined}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem' }}>
                          <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                            <Label isCompact color={URGENCY_COLORS[r.urgency]}>{r.urgency}</Label>
                            {(r as any).escalated && <Label isCompact color="purple">Escalated</Label>}
                            <span style={{ fontWeight: 700, fontSize: '0.95rem' }}>{TYPE_LABELS[r.type] || r.type}</span>
                            <span style={{ color: 'var(--sg-color--info)', fontWeight: 600 }}>{getTarget(r)}</span>
                          </div>
                          {r.confidence_score != null && (
                            <span style={{ fontSize: '0.8rem', color: r.confidence_score >= 0.9 ? 'var(--sg-color--healthy)' : 'var(--sg-color--warning)' }}>
                              {Math.round(r.confidence_score * 100)}% confidence
                            </span>
                          )}
                        </div>
                        <div style={{ fontSize: '0.9rem', marginBottom: '0.5rem' }}>{r.recommendation}</div>
                        {sources.length > 0 && (
                          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', fontSize: '0.75rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>
                            <span style={{ fontWeight: 600 }}>Evidence:</span>
                            {sources.map(s => {
                              const src = s.replace('source_', '');
                              const data = evidence[s] || {};
                              const detail = Object.entries(data).filter(([, v]) => v != null && v !== 0 && v !== '').slice(0, 2).map(([k, v]) => `${k}=${typeof v === 'number' ? v : '...'}`).join(', ');
                              return <Label key={s} isCompact color="grey">{src}{detail ? `: ${detail}` : ''}</Label>;
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
              <Toolbar>
                <ToolbarContent>
                  <ToolbarItem>
                    <SearchInput
                      placeholder="Filter recommendations..."
                      value={search}
                      onChange={(_e, v) => setSearch(v)}
                      onClear={() => setSearch('')}
                      style={{ minWidth: 250 }}
                    />
                  </ToolbarItem>
                  <ToolbarItem>
                    <Select
                      isOpen={urgencyOpen}
                      onOpenChange={setUrgencyOpen}
                      onSelect={(_e, v) => { setUrgencyFilter(v as string); setUrgencyOpen(false); }}
                      selected={urgencyFilter}
                      toggle={(ref) => (
                        <MenuToggle ref={ref} onClick={() => setUrgencyOpen(!urgencyOpen)} isExpanded={urgencyOpen} style={{ minWidth: 140 }}>
                          {urgencyFilter === 'all' ? 'All urgencies' : urgencyFilter}
                        </MenuToggle>
                      )}
                    >
                      <SelectOption value="all">All urgencies</SelectOption>
                      <SelectOption value="critical">Critical</SelectOption>
                      <SelectOption value="high">High</SelectOption>
                      <SelectOption value="medium">Medium</SelectOption>
                    </Select>
                  </ToolbarItem>
                  <ToolbarItem>
                    <Select
                      isOpen={typeOpen}
                      onOpenChange={setTypeOpen}
                      onSelect={(_e, v) => { setTypeFilter(v as string); setTypeOpen(false); }}
                      selected={typeFilter}
                      toggle={(ref) => (
                        <MenuToggle ref={ref} onClick={() => setTypeOpen(!typeOpen)} isExpanded={typeOpen} style={{ minWidth: 170 }}>
                          {typeFilter === 'all' ? 'All types' : TYPE_LABELS[typeFilter] || typeFilter}
                        </MenuToggle>
                      )}
                    >
                      <SelectOption value="all">All types</SelectOption>
                      {Object.entries(TYPE_LABELS).map(([k, v]) => (
                        <SelectOption key={k} value={k}>{v}</SelectOption>
                      ))}
                    </Select>
                  </ToolbarItem>
                  <ToolbarItem>
                    <span style={{ fontSize: '0.85rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>
                      {filtered.length} of {recs?.total ?? 0}
                    </span>
                  </ToolbarItem>
                </ToolbarContent>
              </Toolbar>

              <Table aria-label="Recommendations" variant="compact">
                <Thead>
                  <Tr>
                    <Th width={10}>Urgency</Th>
                    <Th width={15}>Type</Th>
                    <Th width={10}>Target</Th>
                    <Th>Recommendation</Th>
                    <Th width={10}>Action</Th>
                    <Th width={10}>Confidence</Th>
                    <Th width={10}>Generated</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {filtered.slice(0, 50).map((r, i) => (
                    <Tr key={i} isClickable={!!onSelectRecommendation} isRowSelected={selectedRecommendation === r} onRowClick={onSelectRecommendation ? () => onSelectRecommendation(r) : undefined}>
                      <Td>
                        <Label isCompact color={URGENCY_COLORS[r.urgency]}>{r.urgency}</Label>
                        {(r as any).escalated && <Label isCompact color="purple" style={{ marginLeft: 4 }}>Escalated</Label>}
                      </Td>
                      <Td>{TYPE_LABELS[r.type] || r.type}</Td>
                      <Td><strong>{getTarget(r)}</strong></Td>
                      <Td style={{ fontSize: '0.85rem' }}>{r.recommendation}</Td>
                      <Td style={{ fontSize: '0.85rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>{r.action || '—'}</Td>
                      <Td>
                        {r.confidence_score != null ? (
                          <Label isCompact color={r.confidence_score >= 0.9 ? 'green' : r.confidence_score >= 0.75 ? 'yellow' : 'orange'}>
                            {(r.confidence_score * 100).toFixed(0)}%
                          </Label>
                        ) : '—'}
                      </Td>
                      <Td style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)', whiteSpace: 'nowrap' }}>
                        {r.generated_at ? new Date(r.generated_at).toLocaleString() : '—'}
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </>
          )}
        </CardBody>
      </Card>

      {/* Section 2: Pipeline Rubric */}
      <Card>
        <CardTitle>Pipeline Rubric — Stage Health</CardTitle>
        <CardBody>
          {loadingPipeline ? <Spinner size="lg" /> : pipeline ? (
            <StagePipeline stages={pipeline.stages} onSelect={onSelectPipelineStage} selectedStage={selectedStage} />
          ) : <em>No pipeline data.</em>}
        </CardBody>
      </Card>

      {/* Section 3: Lab × Stage Evaluation Matrix */}
      <Card>
        <CardTitle>Evaluation Matrix — Lab × Stage</CardTitle>
        <CardBody>
          {loadingMatrix ? <Spinner size="lg" /> : matrix && matrix.labs.length > 0 ? (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ borderCollapse: 'collapse', fontSize: '0.8rem', width: '100%' }}>
                <thead>
                  <tr>
                    <th style={{ padding: '4px 8px', textAlign: 'left', borderBottom: '2px solid var(--rh-color--border, #d2d2d2)', position: 'sticky', left: 0, background: 'var(--rh-color--surface, #fff)', zIndex: 1 }}>Lab</th>
                    {matrix.stages.map(s => (
                      <th key={s} style={{ padding: '4px 6px', textAlign: 'center', borderBottom: '2px solid var(--rh-color--border, #d2d2d2)', whiteSpace: 'nowrap', fontSize: '0.75rem' }}>
                        {STAGE_LABELS[s] || s}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {matrix.labs.map(lab => (
                    <tr key={lab}>
                      <td style={{ padding: '3px 8px', fontWeight: 600, borderBottom: '1px solid var(--rh-color--border, #d2d2d2)', position: 'sticky', left: 0, background: 'var(--rh-color--surface, #fff)', zIndex: 1 }}>{lab}</td>
                      {matrix.stages.map(stage => {
                        const outcome = matrix.matrix[lab]?.[stage];
                        const bg = outcome ? OUTCOME_COLORS[outcome] || '#e0e0e0' : '#e0e0e0';
                        return (
                          <td
                            key={stage}
                            title={`${lab} / ${stage}: ${outcome || 'no data'}`}
                            style={{
                              padding: '3px 6px',
                              textAlign: 'center',
                              borderBottom: '1px solid var(--rh-color--border, #d2d2d2)',
                              backgroundColor: outcome ? `${bg}22` : 'transparent',
                              color: outcome ? bg : '#aaa',
                              fontWeight: outcome ? 700 : 400,
                              fontSize: '0.75rem',
                            }}
                          >
                            {outcome === 'pass' ? '✓' : outcome === 'fail' ? '✗' : outcome === 'warn' ? '!' : '·'}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <em style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>No evaluation data yet — matrix populates as pipeline evaluations run.</em>}
        </CardBody>
      </Card>
    </div>
  );
}
