import { useState, useMemo } from 'react';
import {
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
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import type { SummitDashboard, SummitLab } from '../api/types';
import { useLabDeltas } from '../api/hooks';
import { useTableSort } from '../hooks/useTableSort';

interface Props {
  data: SummitDashboard;
  onSelect: (lab: SummitLab) => void;
  selectedCode: string | null;
}

export default function LabsView({ data, onSelect, selectedCode }: Props) {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [statusOpen, setStatusOpen] = useState(false);
  const [readyFilter, setReadyFilter] = useState('');
  const [readyOpen, setReadyOpen] = useState(false);
  const [smokeFilter, setSmokeFilter] = useState('');
  const [smokeOpen, setSmokeOpen] = useState(false);
  const [tagFilter, setTagFilter] = useState('');
  const [tagOpen, setTagOpen] = useState(false);
  const { data: deltaData } = useLabDeltas();

  const allTags = useMemo(() => {
    const tags = new Set<string>();
    for (const lab of data.labs) {
      for (const t of lab.agnosticv_tags ?? []) {
        if (!t.startsWith('lb') && t !== 'demo' && t !== 'workshop') tags.add(t);
      }
    }
    return [...tags].sort();
  }, [data.labs]);

  const [scheduleFilter, setScheduleFilter] = useState('');

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return data.labs.filter(lab => {
      if (q && !lab.lab_code.toLowerCase().includes(q) && !lab.title.toLowerCase().includes(q)) return false;
      if (statusFilter && lab.labagator_status !== statusFilter) return false;
      if (readyFilter === 'provisioned' && lab.provisioned === 0) return false;
      if (readyFilter === 'not_provisioned' && lab.provisioned > 0) return false;
      if (readyFilter === 'has_sessions' && lab.sessions === 0) return false;
      if (readyFilter === 'no_pools' && (lab.provisioned > 0 || lab.capacity > 0)) return false;
      if (smokeFilter && lab.demolition_status !== smokeFilter) return false;
      if (tagFilter && !(lab.agnosticv_tags ?? []).includes(tagFilter)) return false;
      const sched = (lab as any).schedule_status || 'no_sessions';
      if (scheduleFilter === 'active_upcoming' && sched === 'completed') return false;
      if (scheduleFilter === 'completed' && sched !== 'completed') return false;
      return true;
    });
  }, [data.labs, search, statusFilter, readyFilter, smokeFilter, tagFilter, scheduleFilter]);

  const labCols = useMemo(() => [
    { key: 'code', getter: (l: SummitLab) => l.lab_code },
    { key: 'title', getter: (l: SummitLab) => l.title },
    { key: 'stage', getter: (l: SummitLab) => l.labagator_status },
    { key: 'cloud', getter: (l: SummitLab) => l.cloud },
    { key: 'sessions', getter: (l: SummitLab) => l.sessions },
    { key: 'sandboxes', getter: (l: SummitLab) => l.instances_started },
    { key: 'capacity', getter: (l: SummitLab) => l.instances_total > 0 ? l.instances_started : l.provisioned },
    { key: 'smoke', getter: (l: SummitLab) => l.demolition_status },
    { key: 'readiness', getter: (l: SummitLab) => {
      const hasSmoke = l.demolition_status !== 'none';
      const isDeployed = l.instances_started > 0 || l.provisioned > 0 || l.capacity > 0
        || hasSmoke || l.cloud === 'Tenant Namespace';
      const checks = [
        l.labagator_status === 'in_development' || l.labagator_status === 'ready',
        l.sessions > 0,
        isDeployed,
        l.demolition_status === 'pass',
      ];
      return checks.filter(Boolean).length;
    }},
    { key: 'scanned', getter: (l: SummitLab) => l.last_scanned ?? '' },
  ], []);

  const labSort = useTableSort(filtered, labCols, { index: 4, direction: 'desc' });

  return (
    <>
      <Toolbar>
        <ToolbarContent>
          <ToolbarItem>
            <SearchInput
              placeholder="Search labs..."
              value={search}
              onChange={(_e, val) => setSearch(val)}
              onClear={() => setSearch('')}
              style={{ minWidth: '200px' }}
            />
          </ToolbarItem>
          <ToolbarItem>
            <Select
              toggle={(ref) => <MenuToggle ref={ref} onClick={() => setStatusOpen(!statusOpen)} isExpanded={statusOpen}>{statusFilter === 'in_development' ? 'Building' : statusFilter === 'ready' ? 'Ready' : statusFilter === 'planning' ? 'Planning' : 'All statuses'}</MenuToggle>}
              isOpen={statusOpen}
              onSelect={(_e, v) => { setStatusFilter(v as string); setStatusOpen(false); }}
              onOpenChange={setStatusOpen}
              selected={statusFilter}
            >
              <SelectOption value="">All statuses</SelectOption>
              <SelectOption value="in_development">Building</SelectOption>
              <SelectOption value="ready">Ready</SelectOption>
              <SelectOption value="planning">Planning</SelectOption>
            </Select>
          </ToolbarItem>
          <ToolbarItem>
            <Select
              toggle={(ref) => <MenuToggle ref={ref} onClick={() => setReadyOpen(!readyOpen)} isExpanded={readyOpen}>{readyFilter === 'provisioned' ? 'Provisioned' : readyFilter === 'not_provisioned' ? 'Not Provisioned' : readyFilter === 'has_sessions' ? 'Has Sessions' : readyFilter === 'no_pools' ? 'No Pools' : 'All readiness'}</MenuToggle>}
              isOpen={readyOpen}
              onSelect={(_e, v) => { setReadyFilter(v as string); setReadyOpen(false); }}
              onOpenChange={setReadyOpen}
              selected={readyFilter}
            >
              <SelectOption value="">All readiness</SelectOption>
              <SelectOption value="provisioned">Provisioned</SelectOption>
              <SelectOption value="not_provisioned">Not Provisioned</SelectOption>
              <SelectOption value="has_sessions">Has Sessions</SelectOption>
              <SelectOption value="no_pools">No Pools</SelectOption>
            </Select>
          </ToolbarItem>
          <ToolbarItem>
            <Select
              toggle={(ref) => <MenuToggle ref={ref} onClick={() => setSmokeOpen(!smokeOpen)} isExpanded={smokeOpen}>{smokeFilter === 'pass' ? 'Smoke: Pass' : smokeFilter === 'fail' ? 'Smoke: Fail' : smokeFilter === 'none' ? 'Smoke: Not tested' : 'All smoke tests'}</MenuToggle>}
              isOpen={smokeOpen}
              onSelect={(_e, v) => { setSmokeFilter(v as string); setSmokeOpen(false); }}
              onOpenChange={setSmokeOpen}
              selected={smokeFilter}
            >
              <SelectOption value="">All smoke tests</SelectOption>
              <SelectOption value="pass">Pass</SelectOption>
              <SelectOption value="fail">Fail</SelectOption>
              <SelectOption value="none">Not tested</SelectOption>
            </Select>
          </ToolbarItem>
          {allTags.length > 0 && (
            <ToolbarItem>
              <Select
                toggle={(ref) => <MenuToggle ref={ref} onClick={() => setTagOpen(!tagOpen)} isExpanded={tagOpen}>{tagFilter || 'All tags'}</MenuToggle>}
                isOpen={tagOpen}
                onSelect={(_e, v) => { setTagFilter(v as string); setTagOpen(false); }}
                onOpenChange={setTagOpen}
                selected={tagFilter}
              >
                <SelectOption value="">All tags</SelectOption>
                {allTags.map(t => <SelectOption key={t} value={t}>{t}</SelectOption>)}
              </Select>
            </ToolbarItem>
          )}
          <ToolbarItem>
            <div style={{ display: 'flex', gap: '4px' }}>
              {[
                { key: 'active_upcoming', label: 'Active / Upcoming' },
                { key: 'completed', label: 'Completed' },
                { key: '', label: 'All' },
              ].map(opt => (
                <Label
                  key={opt.key}
                  isCompact
                  color={scheduleFilter === opt.key ? 'blue' : 'grey'}
                  onClick={() => setScheduleFilter(opt.key)}
                  style={{ cursor: 'pointer' }}
                >
                  {opt.label}
                </Label>
              ))}
            </div>
          </ToolbarItem>
          <ToolbarItem><span style={{ fontSize: '0.9rem', color: 'var(--rh-color--text-secondary)' }}>{filtered.length} labs</span></ToolbarItem>
        </ToolbarContent>
      </Toolbar>

      <div className="sg-table-wrap">
      <Table aria-label="Labs" variant="compact">
        <Thead>
          <Tr>
            <Th {...labSort.getSortParams(0)}>Lab Code</Th>
            <Th {...labSort.getSortParams(1)}>Title</Th>
            <Th {...labSort.getSortParams(2)}>Stage</Th>
            <Th {...labSort.getSortParams(3)}>Cloud</Th>
            <Th>Tags</Th>
            <Th {...labSort.getSortParams(4)}>Usage</Th>
            <Th {...labSort.getSortParams(5)}>Sandboxes</Th>
            <Th {...labSort.getSortParams(6)}>Capacity</Th>
            <Th {...labSort.getSortParams(7)}>Smoke Test</Th>
            <Th {...labSort.getSortParams(8)}>Readiness</Th>
            <Th {...labSort.getSortParams(9)}>Last Scanned</Th>
            <Th>Change</Th>
            <Th>Next Action</Th>
          </Tr>
        </Thead>
        <Tbody>
          {labSort.sorted.map(lab => {
            const hasSmoke = lab.demolition_status !== 'none';
            const isDeployed = lab.instances_started > 0 || lab.provisioned > 0 || lab.capacity > 0
              || hasSmoke || lab.cloud === 'Tenant Namespace';
            const readyCount = [
              lab.labagator_status === 'in_development' || lab.labagator_status === 'ready',
              lab.sessions > 0,
              isDeployed,
              lab.demolition_status === 'pass',
            ].filter(Boolean).length;
            const isReady = readyCount === 4;
            const isAlmostReady = readyCount === 3;
            const isBlocked = lab.sessions > 0 && !isDeployed && lab.instances_failed === 0;

            const rowStyle: React.CSSProperties = isReady
              ? { background: 'var(--sg-color--healthy-bg)', borderLeft: '4px solid var(--sg-color--healthy)' }
              : lab.instances_failed > 0
              ? { background: 'var(--sg-color--critical-bg)', borderLeft: '4px solid var(--sg-color--critical)' }
              : isBlocked
              ? { borderLeft: '4px solid var(--sg-color--warning)' }
              : isAlmostReady
              ? { borderLeft: '4px solid var(--sg-color--info)' }
              : {};

            return (
              <Tr key={lab.lab_code} isClickable isRowSelected={lab.lab_code === selectedCode} onRowClick={() => onSelect(lab)} style={rowStyle}>
                <Td><strong style={{ color: 'var(--sg-color--info)' }}>{lab.lab_code}</strong></Td>
                <Td style={{ maxWidth: '280px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{lab.title}</Td>
                <Td><StageLabel status={lab.labagator_status} /></Td>
                <Td>{lab.cloud || '-'}</Td>
                <Td style={{ maxWidth: '200px' }}>
                  {(lab.agnosticv_tags ?? [])
                    .filter(t => !t.startsWith('lb') && t !== 'demo' && t !== 'workshop')
                    .slice(0, 3)
                    .map(t => <Label key={t} isCompact color="blue" style={{ marginRight: '2px', marginBottom: '1px', fontSize: '0.7rem' }}>{t}</Label>)}
                </Td>
                <Td>{lab.sessions > 0 ? <strong>{lab.sessions}</strong> : <span style={{ color: 'var(--rh-color--text-secondary)' }}>0</span>}</Td>
                <Td>{lab.instances_started > 0 ? <strong>{lab.instances_started}</strong> : <span style={{ color: 'var(--rh-color--text-secondary)' }}>0</span>}</Td>
                <Td><CapacityCell lab={lab} /></Td>
                <Td><SmokeTestCell lab={lab} /></Td>
                <Td style={{ minWidth: '140px' }}><ReadinessCell lab={lab} readyCount={readyCount} /></Td>
                <Td style={{ fontSize: '0.8rem' }}>
                  {lab.last_scanned
                    ? <span title={new Date(lab.last_scanned).toLocaleString()}>{formatScanTime(lab.last_scanned)}</span>
                    : <span style={{ color: 'var(--sg-color--warning)', fontSize: '0.8rem' }} title="No provisioning, no smoke tests, no instances — nothing to scan">Not deployed</span>}
                </Td>
                <Td><DeltaCell code={lab.lab_code} deltas={deltaData?.deltas} /></Td>
                <Td>
                  {lab.next_action?.action ? (
                    <span style={{
                      fontSize: '0.8rem',
                      fontWeight: 600,
                      color: lab.next_action.urgency === 'critical' ? 'var(--sg-color--critical)'
                        : lab.next_action.urgency === 'high' ? 'var(--sg-color--warning)'
                        : 'var(--rh-color--text-secondary, #6a6e73)',
                    }} title={lab.next_action.detail}>
                      {lab.next_action.action}
                    </span>
                  ) : (
                    <span style={{ fontSize: '0.8rem', color: 'var(--sg-color--healthy)' }}>On track</span>
                  )}
                </Td>
              </Tr>
            );
          })}
        </Tbody>
      </Table>
      </div>
    </>
  );
}

function StageLabel({ status }: { status: string }) {
  if (status === 'in_development') return <Label isCompact color="green">Building</Label>;
  if (status === 'ready') return <Label isCompact color="green">Ready</Label>;
  if (status === 'planning') return <Label isCompact color="blue">Planning</Label>;
  return <Label isCompact color="grey">{status}</Label>;
}

function CapacityCell({ lab }: { lab: SummitLab }) {
  if (lab.instances_total > 0) {
    const color = lab.instances_started === lab.instances_total
      ? 'var(--sg-color--healthy)'
      : lab.instances_started > 0
      ? 'var(--sg-color--warning)'
      : 'var(--sg-color--critical)';
    return (
      <span>
        <strong style={{ color }}>{lab.instances_started}</strong>
        <span style={{ color: 'var(--rh-color--text-secondary)' }}> / {lab.instances_total} up</span>
        {lab.instances_failed > 0 && (
          <span style={{ color: 'var(--sg-color--critical)', marginLeft: '4px', fontSize: '0.8rem' }}>
            ({lab.instances_failed} stuck)
          </span>
        )}
      </span>
    );
  }
  if (lab.provisioned > 0 || lab.capacity > 0) {
    const color = lab.provisioned >= lab.capacity && lab.capacity > 0
      ? 'var(--sg-color--healthy)'
      : lab.provisioned > 0
      ? 'var(--sg-color--warning)'
      : 'var(--sg-color--critical)';
    return (
      <span>
        <strong style={{ color }}>{lab.provisioned}</strong>
        <span style={{ color: 'var(--rh-color--text-secondary)' }}> / {lab.capacity} ready</span>
      </span>
    );
  }
  return <span style={{ color: 'var(--sg-color--warning)', fontSize: '0.85rem' }}>No pools</span>;
}

function SmokeTestCell({ lab }: { lab: SummitLab }) {
  if (lab.demolition_status === 'pass') {
    return (
      <Label isCompact color="green">
        Pass ({lab.demolition_completed}/{lab.demolition_total})
      </Label>
    );
  }
  if (lab.demolition_status === 'fail') {
    return (
      <Label isCompact color="red">
        Fail ({lab.demolition_failed}/{lab.demolition_total})
      </Label>
    );
  }
  return <span style={{ color: 'var(--rh-color--text-secondary)', fontSize: '0.85rem' }}>Not tested</span>;
}

function formatScanTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

const ARROW_UP = '▲';
const ARROW_DOWN = '▼';

function DeltaCell({ code, deltas }: { code: string; deltas?: Record<string, Record<string, string>> }) {
  if (!deltas) return <span style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>-</span>;
  const d = deltas[code];
  if (!d) return <span style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>-</span>;

  const items: { label: string; dir: string }[] = [];
  if (d.instances) items.push({ label: 'Provisioned', dir: d.instances });
  if (d.capacity) items.push({ label: 'Pools', dir: d.capacity });
  if (d.smoke) items.push({ label: 'Smoke Test', dir: d.smoke });
  if (d.status) items.push({ label: 'Dev Stage', dir: d.status });

  if (items.length === 0) return <span style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>-</span>;

  return (
    <span style={{ fontSize: '0.8rem', display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
      {items.map(i => (
        <span
          key={i.label}
          title={`${i.label}: ${i.dir}`}
          style={{
            color: i.dir === 'up' ? 'var(--sg-color--healthy)' : 'var(--sg-color--critical)',
            fontWeight: 600,
          }}
        >
          {i.dir === 'up' ? ARROW_UP : ARROW_DOWN}{i.label}
        </span>
      ))}
    </span>
  );
}

function ReadinessCell({ lab, readyCount }: { lab: SummitLab; readyCount: number }) {
  const hasSmoke = lab.demolition_status !== 'none';
  const isDeployed = lab.instances_started > 0 || lab.provisioned > 0 || lab.capacity > 0
    || hasSmoke || lab.cloud === 'Tenant Namespace';
  const checks = [
    { label: 'Content', done: lab.labagator_status === 'in_development' || lab.labagator_status === 'ready' },
    { label: 'Sessions', done: lab.sessions > 0 },
    { label: 'Deployed', done: isDeployed },
    { label: 'Smoke', done: lab.demolition_status === 'pass' },
  ];
  const pct = (readyCount / 4) * 100;

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
      <Progress value={pct} size="sm" style={{ minWidth: 60 }} variant={pct >= 100 ? undefined : pct >= 50 ? 'warning' : 'danger'} />
      <span style={{ fontSize: '0.75rem', whiteSpace: 'nowrap', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>
        {checks.map(c => (
          <span key={c.label} style={{ color: c.done ? 'var(--sg-color--healthy)' : 'var(--sg-color--critical)', marginRight: '3px' }} title={c.label}>
            {c.label[0]}
          </span>
        ))}
      </span>
    </div>
  );
}
