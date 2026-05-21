import { useState, useMemo } from 'react';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
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
import type { PoolsDashboard, PoolEntry } from '../api/types';
import { useStuckInstances } from '../api/hooks';
import { useTableSort } from '../hooks/useTableSort';
import StatusLabel from './StatusLabel';

interface Props {
  data: PoolsDashboard;
  onSelect: (pool: PoolEntry) => void;
  selectedPool: string | null;
}

export default function PoolsView({ data, onSelect, selectedPool }: Props) {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [statusOpen, setStatusOpen] = useState(false);
  const [scopeFilter, setScopeFilter] = useState('all');
  const [scopeOpen, setScopeOpen] = useState(false);
  const [showStuck, setShowStuck] = useState(false);
  const [expandedLab, setExpandedLab] = useState<string | null>(null);
  const { data: stuckData } = useStuckInstances();

  const pools = useMemo(() => {
    const q = search.toLowerCase();
    return [...(data.pools ?? data.summit_pools)]
      .filter(p => {
        if (q && !p.name.toLowerCase().includes(q)) return false;
        if (statusFilter && p.status !== statusFilter) return false;
        if (scopeFilter === 'summit' && !p.is_summit) return false;
        if (scopeFilter === 'platform' && p.is_summit) return false;
        return true;
      })
      .sort((a, b) => {
        const order: Record<string, number> = { exhausted: 0, low: 1, healthy: 2 };
        return (order[a.status] ?? 3) - (order[b.status] ?? 3) || a.name.localeCompare(b.name);
      });
  }, [(data.pools ?? data.summit_pools), search, statusFilter, scopeFilter]);

  const poolCols = useMemo(() => [
    { key: 'name', getter: (p: PoolEntry) => p.name },
    { key: 'status', getter: (p: PoolEntry) => p.status },
    { key: 'available', getter: (p: PoolEntry) => p.available },
    { key: 'ready', getter: (p: PoolEntry) => p.ready },
    { key: 'min', getter: (p: PoolEntry) => p.min },
  ], []);

  const poolSort = useTableSort(pools, poolCols);

  const prov = data.provisioning;
  const provPct = prov.total > 0 ? ((prov.started / prov.total) * 100) : 0;

  return (
    <>
      <Toolbar>
        <ToolbarContent>
          <ToolbarItem>
            <SearchInput
              placeholder="Search pools..."
              value={search}
              onChange={(_e, val) => setSearch(val)}
              onClear={() => setSearch('')}
              style={{ minWidth: '200px' }}
            />
          </ToolbarItem>
          <ToolbarItem>
            <Select
              toggle={(ref) => <MenuToggle ref={ref} onClick={() => setStatusOpen(!statusOpen)} isExpanded={statusOpen}>{statusFilter || 'All statuses'}</MenuToggle>}
              isOpen={statusOpen}
              onSelect={(_e, v) => { setStatusFilter(v as string); setStatusOpen(false); }}
              onOpenChange={setStatusOpen}
              selected={statusFilter}
            >
              <SelectOption value="">All statuses</SelectOption>
              <SelectOption value="exhausted">Exhausted</SelectOption>
              <SelectOption value="low">Low</SelectOption>
              <SelectOption value="healthy">Healthy</SelectOption>
            </Select>
          </ToolbarItem>
          <ToolbarItem>
            <Select
              toggle={(ref) => <MenuToggle ref={ref} onClick={() => setScopeOpen(!scopeOpen)} isExpanded={scopeOpen}>{scopeFilter === 'summit' ? 'Summit Only' : scopeFilter === 'platform' ? 'Platform Only' : 'All Pools'}</MenuToggle>}
              isOpen={scopeOpen}
              onSelect={(_e, v) => { setScopeFilter(v as string); setScopeOpen(false); }}
              onOpenChange={setScopeOpen}
              selected={scopeFilter}
            >
              <SelectOption value="all">All Pools</SelectOption>
              <SelectOption value="summit">Summit Only</SelectOption>
              <SelectOption value="platform">Platform Only</SelectOption>
            </Select>
          </ToolbarItem>
          <ToolbarItem><span style={{ fontSize: '0.9rem', color: 'var(--rh-color--text-secondary)' }}>{pools.length} pools</span></ToolbarItem>
        </ToolbarContent>
      </Toolbar>

      <div style={{ marginBottom: '1rem', display: 'flex', gap: '2rem', flexWrap: 'wrap', fontSize: '0.9rem' }}>
        <div>
          <strong>{data.total_pools}</strong> total pools |{' '}
          <strong>{(data.pools ?? data.summit_pools).length}</strong> displayed |{' '}
          <Label color="red" isCompact>{(data.pools ?? data.summit_pools).filter(p => p.status === 'exhausted').length} exhausted</Label>{' '}
          <Label color="orange" isCompact>{(data.pools ?? data.summit_pools).filter(p => p.status === 'low').length} low</Label>{' '}
          <Label color="green" isCompact>{(data.pools ?? data.summit_pools).filter(p => p.status === 'healthy').length} healthy</Label>
        </div>
        <div style={{ minWidth: '250px' }}>
          Provisioning: <strong>{prov.started}</strong>/{prov.total} started ({provPct.toFixed(0)}%)
          <Progress value={provPct} style={{ marginTop: '4px' }} size="sm" variant={provPct >= 80 ? undefined : 'warning'} />
        </div>
        {((prov.by_state['destroy-failed'] ?? 0) > 0 || (prov.by_state['provision-failed'] ?? 0) > 0 || (prov.by_state['provision-error'] ?? 0) > 0) && (
          <div style={{ padding: '0.5rem 0.75rem', background: 'var(--sg-color--critical-bg)', borderRadius: '4px', borderLeft: '3px solid var(--sg-color--critical)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }} onClick={() => setShowStuck(!showStuck)}>
              <strong style={{ color: 'var(--sg-color--critical)' }}>
                Cleanup Issues {stuckData ? `(${stuckData.total_stuck} instances stuck)` : ''}
              </strong>
              <span style={{ fontSize: '0.85rem', color: 'var(--sg-color--info)' }}>{showStuck ? 'Hide detail ▲' : 'Show detail ▼'}</span>
            </div>
            <div style={{ display: 'flex', gap: '1rem', marginTop: '0.25rem', flexWrap: 'wrap', fontSize: '0.9rem' }}>
              {(prov.by_state['destroy-failed'] ?? 0) > 0 && <span><strong>{prov.by_state['destroy-failed']}</strong> destroy-failed</span>}
              {(prov.by_state['provision-failed'] ?? 0) > 0 && <span><strong>{prov.by_state['provision-failed']}</strong> provision-failed</span>}
              {(prov.by_state['provision-error'] ?? 0) > 0 && <span><strong>{prov.by_state['provision-error']}</strong> provision-error</span>}
              {(prov.by_state['start-error'] ?? 0) > 0 && <span><strong>{prov.by_state['start-error']}</strong> start-error</span>}
              {(prov.by_state['stop-failed'] ?? 0) > 0 && <span><strong>{prov.by_state['stop-failed']}</strong> stop-failed</span>}
              {(prov.by_state['stopped'] ?? 0) > 0 && <span><strong>{prov.by_state['stopped']}</strong> stopped (idle)</span>}
            </div>

            {showStuck && stuckData && Object.keys(stuckData.by_lab).length > 0 && (
              <div style={{ marginTop: '0.75rem' }}>
                {Object.entries(stuckData.by_lab).map(([lab, instances]) => (
                  <div key={lab} style={{ marginBottom: '0.5rem', border: '1px solid var(--rh-color--border, #d2d2d2)', borderRadius: '4px', background: 'var(--rh-color--surface, #fff)' }}>
                    <div
                      style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.5rem 0.75rem', cursor: 'pointer' }}
                      onClick={() => setExpandedLab(expandedLab === lab ? null : lab)}
                    >
                      <span>
                        <strong style={{ color: 'var(--sg-color--info)' }}>{lab}</strong>
                        <span style={{ marginLeft: '0.5rem', color: 'var(--sg-color--critical)' }}>{instances.length} stuck</span>
                      </span>
                      <span style={{ fontSize: '0.8rem' }}>{expandedLab === lab ? '▲' : '▼'}</span>
                    </div>
                    {expandedLab === lab && (
                      <div style={{ padding: '0 0.75rem 0.5rem' }}>
                        {instances.map((inst, i) => (
                          <div key={i} style={{ padding: '0.35rem 0', borderTop: i > 0 ? '1px solid var(--rh-color--border, #d2d2d2)' : undefined, fontSize: '0.85rem' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <span style={{ wordBreak: 'break-all', flex: 1 }}>{inst.name}</span>
                              <Label isCompact color={inst.state.includes('destroy') ? 'red' : 'orange'} style={{ marginLeft: '0.5rem', whiteSpace: 'nowrap' }}>{inst.state}</Label>
                            </div>
                            {inst.console_url && (
                              <a href={inst.console_url} target="_blank" rel="noreferrer" style={{ fontSize: '0.8rem', color: 'var(--sg-color--info)' }}>
                                Open console
                              </a>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="sg-table-wrap">
      <Table aria-label="Pools" variant="compact">
        <Thead>
          <Tr>
            <Th {...poolSort.getSortParams(0)}>Pool Name</Th>
            <Th>Type</Th>
            <Th {...poolSort.getSortParams(1)}>Status</Th>
            <Th {...poolSort.getSortParams(2)}>Available</Th>
            <Th {...poolSort.getSortParams(3)}>Ready</Th>
            <Th {...poolSort.getSortParams(4)}>Min</Th>
            <Th>Capacity</Th>
          </Tr>
        </Thead>
        <Tbody>
          {poolSort.sorted.map(p => {
            const capacityPct = p.min > 0 ? Math.min((p.available / p.min) * 100, 100) : (p.available > 0 ? 100 : 0);
            return (
              <Tr key={p.name} isClickable isRowSelected={p.name === selectedPool} onRowClick={() => onSelect(p)}>
                <Td style={{ fontSize: '0.9rem', maxWidth: '350px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</Td>
                <Td>{p.is_summit ? <Label isCompact color="blue">Event</Label> : <Label isCompact color="grey">Platform</Label>}</Td>
                <Td><StatusLabel status={p.status} isCompact /></Td>
                <Td style={{ fontWeight: 600, color: p.available === 0 && p.min > 0 ? 'var(--sg-color--critical)' : p.available <= 1 && p.min > 0 ? 'var(--sg-color--warning)' : undefined }}>{p.available}</Td>
                <Td>{p.ready}</Td>
                <Td>{p.min}</Td>
                <Td style={{ minWidth: '100px' }}>
                  <Progress value={capacityPct} size="sm" variant={capacityPct <= 0 ? 'danger' : capacityPct < 50 ? 'warning' : undefined} />
                </Td>
              </Tr>
            );
          })}
          {pools.length === 0 && (
            <Tr><Td colSpan={7}><em>No matching pools.</em></Td></Tr>
          )}
        </Tbody>
      </Table>
      </div>
    </>
  );
}
