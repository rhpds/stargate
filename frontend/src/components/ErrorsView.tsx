import { useState, useMemo } from 'react';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import {
  Card,
  CardBody,
  CardTitle,
  Label,
  MenuToggle,
  Progress,
  SearchInput,
  Select,
  SelectOption,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
} from '@patternfly/react-core';
import { useEvents, useTrends } from '../api/hooks';
import type { OverviewData } from '../api/types';
import { useTableSort } from '../hooks/useTableSort';
import TrendChart from './TrendChart';

interface ErrorRow {
  failure_class: string;
  count: number;
  pct: number;
  clusters: string[];
  stages: string[];
  latest_time: string | null;
  max_blast_radius: { failing_labs: number; total_labs: number; failure_rate: number } | null;
  has_escalation: boolean;
}

interface Props {
  data: OverviewData;
  onSelect: (row: ErrorRow) => void;
  selectedClass: string | null;
}

export default function ErrorsView({ data, onSelect, selectedClass }: Props) {
  const [search, setSearch] = useState('');
  const [stageFilter, setStageFilter] = useState('');
  const [stageOpen, setStageOpen] = useState(false);

  const { data: events } = useEvents({ limit: '200' });
  const { data: trends } = useTrends();

  const trendData = useMemo(() => {
    if (!trends?.failure_trend.length) return [];
    const byTime: Record<string, number> = {};
    for (const ft of trends.failure_trend) {
      byTime[ft.timestamp] = (byTime[ft.timestamp] ?? 0) + ft.count;
    }
    return Object.entries(byTime)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([ts, count]) => ({ x: new Date(ts).getTime(), y: count, label: `${count} failures` }));
  }, [trends]);

  const rows: ErrorRow[] = useMemo(() => {
    const failedEvents = (events ?? []).filter(e => e.outcome === 'fail' && e.failure_class);
    const byClass: Record<string, {
      count: number;
      clusters: Set<string>;
      stages: Set<string>;
      latest: string;
      maxBlast: { failing_labs: number; total_labs: number; failure_rate: number } | null;
      escalated: boolean;
    }> = {};

    for (const evt of failedEvents) {
      const fc = evt.failure_class!;
      if (!byClass[fc]) byClass[fc] = { count: 0, clusters: new Set(), stages: new Set(), latest: evt.timestamp, maxBlast: null, escalated: false };
      const entry = byClass[fc]!;
      entry.count++;
      if (evt.cluster_name) entry.clusters.add(evt.cluster_name);
      if (evt.stage_id) entry.stages.add(evt.stage_id);
      if (evt.timestamp > entry.latest) entry.latest = evt.timestamp;
      if (evt.blast_radius) {
        const br = evt.blast_radius as { failing_labs?: number; total_labs?: number; failure_rate?: number };
        if (!entry.maxBlast || (br.failing_labs ?? 0) > entry.maxBlast.failing_labs) {
          entry.maxBlast = { failing_labs: br.failing_labs ?? 0, total_labs: br.total_labs ?? 0, failure_rate: br.failure_rate ?? 0 };
        }
      }
      if (evt.metadata?.escalate) entry.escalated = true;
    }

    const dbClasses = data.errors.failure_classes;
    const allClasses = new Set([...Object.keys(byClass), ...Object.keys(dbClasses)]);

    return [...allClasses].map(fc => ({
      failure_class: fc,
      count: dbClasses[fc] ?? byClass[fc]?.count ?? 0,
      pct: data.errors.total_failures > 0 ? ((dbClasses[fc] ?? 0) / data.errors.total_failures) * 100 : 0,
      clusters: [...(byClass[fc]?.clusters ?? [])],
      stages: [...(byClass[fc]?.stages ?? [])],
      latest_time: byClass[fc]?.latest ?? null,
      max_blast_radius: byClass[fc]?.maxBlast ?? null,
      has_escalation: byClass[fc]?.escalated ?? false,
    })).sort((a, b) => b.count - a.count);
  }, [data.errors, events]);

  const allStages = useMemo(() => {
    const s = new Set<string>();
    for (const r of rows) r.stages.forEach(st => s.add(st));
    return [...s].sort();
  }, [rows]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return rows.filter(r => {
      if (q && !r.failure_class.toLowerCase().includes(q)) return false;
      if (stageFilter && !r.stages.includes(stageFilter)) return false;
      return true;
    });
  }, [rows, search, stageFilter]);

  const errorCols = useMemo(() => [
    { key: 'class', getter: (r: ErrorRow) => r.failure_class },
    { key: 'count', getter: (r: ErrorRow) => r.count },
    { key: 'pct', getter: (r: ErrorRow) => r.pct },
  ], []);

  const errorSort = useTableSort(filtered, errorCols);

  return (
    <div>
      <Toolbar>
        <ToolbarContent>
          <ToolbarItem>
            <SearchInput
              placeholder="Search failure classes..."
              value={search}
              onChange={(_e, val) => setSearch(val)}
              onClear={() => setSearch('')}
              style={{ minWidth: '220px' }}
            />
          </ToolbarItem>
          {allStages.length > 0 && (
            <ToolbarItem>
              <Select
                toggle={(ref) => <MenuToggle ref={ref} onClick={() => setStageOpen(!stageOpen)} isExpanded={stageOpen}>{stageFilter || 'All stages'}</MenuToggle>}
                isOpen={stageOpen}
                onSelect={(_e, v) => { setStageFilter(v as string); setStageOpen(false); }}
                onOpenChange={setStageOpen}
                selected={stageFilter}
              >
                <SelectOption value="">All stages</SelectOption>
                {allStages.map(s => <SelectOption key={s} value={s}>{s}</SelectOption>)}
              </Select>
            </ToolbarItem>
          )}
          <ToolbarItem><span style={{ fontSize: '0.9rem', color: 'var(--rh-color--text-secondary)' }}>{filtered.length} failure classes</span></ToolbarItem>
        </ToolbarContent>
      </Toolbar>

      {trendData.length > 0 && (
        <Card style={{ marginBottom: '1rem' }}>
          <CardTitle>Failure Trend</CardTitle>
          <CardBody>
            <TrendChart data={trendData} color="#C9190B" height={120} width={600} yLabel="Failures" />
          </CardBody>
        </Card>
      )}
      <div className="sg-table-wrap">
      <Table aria-label="Errors" variant="compact">
        <Thead>
          <Tr>
            <Th {...errorSort.getSortParams(0)}>Failure Class</Th>
            <Th {...errorSort.getSortParams(1)}>Count</Th>
            <Th {...errorSort.getSortParams(2)}>% of Total</Th>
            <Th>Blast Radius</Th>
            <Th>Clusters</Th>
            <Th>Stages</Th>
            <Th>Latest</Th>
          </Tr>
        </Thead>
        <Tbody>
          {errorSort.sorted.map(row => (
            <Tr key={row.failure_class} isClickable isRowSelected={row.failure_class === selectedClass} onRowClick={() => onSelect(row)}>
              <Td>
                <strong style={{ color: 'var(--sg-color--critical)' }}>{row.failure_class}</strong>
                {row.has_escalation && <Label isCompact color="red" style={{ marginLeft: '0.5rem' }}>ESCALATED</Label>}
              </Td>
              <Td><strong>{row.count}</strong></Td>
              <Td>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                  <Progress value={row.pct} size="sm" style={{ minWidth: '60px' }} variant={row.pct > 30 ? 'danger' : row.pct > 15 ? 'warning' : undefined} />
                  <span style={{ fontSize: '0.85rem' }}>{row.pct.toFixed(1)}%</span>
                </div>
              </Td>
              <Td>
                {row.max_blast_radius ? (
                  <span style={{ color: row.max_blast_radius.failure_rate > 30 ? 'var(--sg-color--critical)' : undefined, fontWeight: row.max_blast_radius.failure_rate > 30 ? 700 : undefined }}>
                    {row.max_blast_radius.failing_labs}/{row.max_blast_radius.total_labs} labs
                  </span>
                ) : '-'}
              </Td>
              <Td style={{ fontSize: '0.85rem' }}>{row.clusters.length > 0 ? row.clusters.join(', ') : '-'}</Td>
              <Td>{row.stages.map(s => <Label key={s} isCompact color="blue" style={{ marginRight: '4px' }}>{s}</Label>)}</Td>
              <Td style={{ fontSize: '0.8rem' }}>{row.latest_time ? new Date(row.latest_time).toLocaleString() : '-'}</Td>
            </Tr>
          ))}
          {filtered.length === 0 && (
            <Tr><Td colSpan={7}><em>No matching failures.</em></Td></Tr>
          )}
        </Tbody>
      </Table>
      </div>
    </div>
  );
}

export type { ErrorRow };
