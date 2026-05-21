import { useState, useMemo } from 'react';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import {
  MenuToggle,
  SearchInput,
  Select,
  SelectOption,
  Skeleton,
  Toolbar,
  ToolbarContent,
  ToolbarItem,
} from '@patternfly/react-core';
import type { OverviewData, ClusterScan } from '../api/types';
import { useTableSort } from '../hooks/useTableSort';
import { useTrends } from '../api/hooks';
import StatusLabel from './StatusLabel';
import TrendChart from './TrendChart';

interface Props {
  data: OverviewData;
  onSelect: (cluster: ClusterScan) => void;
  selectedCluster: string | null;
}

export default function ClustersView({ data, onSelect, selectedCluster }: Props) {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [statusOpen, setStatusOpen] = useState(false);

  const { data: trends, isLoading: trendsLoading } = useTrends();

  const clusterTrends = useMemo(() => {
    if (!trends) return {} as Record<string, { x: number; y: number }[]>;
    const map: Record<string, { x: number; y: number }[]> = {};
    for (const pt of trends.cluster_health_trend) {
      if (!map[pt.cluster]) map[pt.cluster] = [];
      map[pt.cluster]!.push({ x: new Date(pt.timestamp).getTime(), y: pt.health_rate });
    }
    return map;
  }, [trends]);

  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return [...data.clusters.scans]
      .filter(s => {
        if (q && !s.cluster.toLowerCase().includes(q)) return false;
        if (statusFilter && s.status !== statusFilter) return false;
        return true;
      })
      .sort((a, b) => a.cluster.localeCompare(b.cluster));
  }, [data.clusters.scans, search, statusFilter]);

  const clusterCols = useMemo(() => [
    { key: 'cluster', getter: (s: ClusterScan) => s.cluster },
    { key: 'status', getter: (s: ClusterScan) => s.status },
    { key: 'cpu', getter: (s: ClusterScan) => s.avg_cpu_pct },
    { key: 'hot', getter: (s: ClusterScan) => s.hot_nodes },
    { key: 'vmsNode', getter: (s: ClusterScan) => s.vms_per_node },
    { key: 'labs', getter: (s: ClusterScan) => s.sandbox_active },
    { key: 'failing', getter: (s: ClusterScan) => s.sandbox_failing },
    { key: 'crash', getter: (s: ClusterScan) => s.sandbox_crashloop },
    { key: 'health', getter: (s: ClusterScan) => s.health_rate },
  ], []);

  const clusterSort = useTableSort(filtered, clusterCols);

  return (
    <>
      <Toolbar>
        <ToolbarContent>
          <ToolbarItem>
            <SearchInput
              placeholder="Search clusters..."
              value={search}
              onChange={(_e, val) => setSearch(val)}
              onClear={() => setSearch('')}
              style={{ minWidth: '180px' }}
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
              <SelectOption value="healthy">Healthy</SelectOption>
              <SelectOption value="warning">Warning</SelectOption>
              <SelectOption value="critical">Critical</SelectOption>
            </Select>
          </ToolbarItem>
          <ToolbarItem><span style={{ fontSize: '0.9rem', color: 'var(--rh-color--text-secondary)' }}>{filtered.length} clusters</span></ToolbarItem>
        </ToolbarContent>
      </Toolbar>

      <div className="sg-table-wrap">
      <Table aria-label="Clusters" variant="compact">
        <Thead>
          <Tr>
            <Th {...clusterSort.getSortParams(0)}>Cluster</Th>
            <Th {...clusterSort.getSortParams(1)}>Status</Th>
            <Th {...clusterSort.getSortParams(2)}>CPU %</Th>
            <Th {...clusterSort.getSortParams(3)}>Hot Nodes</Th>
            <Th {...clusterSort.getSortParams(4)}>VMs/Node</Th>
            <Th {...clusterSort.getSortParams(5)}>Labs Active</Th>
            <Th {...clusterSort.getSortParams(6)}>Failing</Th>
            <Th {...clusterSort.getSortParams(7)}>Crashloop</Th>
            <Th {...clusterSort.getSortParams(8)}>Health %</Th>
            <Th>Trend</Th>
            <Th>DNS</Th>
            <Th>Issues</Th>
          </Tr>
        </Thead>
        <Tbody>
          {clusterSort.sorted.map(s => (
            <Tr key={s.cluster} isClickable isRowSelected={s.cluster === selectedCluster} onRowClick={() => onSelect(s)}>
              <Td><a href={`https://console-openshift-console.apps.${s.cluster}.dal10.infra.demo.redhat.com`} target="_blank" rel="noreferrer" style={{ color: 'var(--sg-color--info)', fontWeight: 600, textDecoration: 'none' }} onClick={e => e.stopPropagation()}>{s.cluster}</a></Td>
              <Td><StatusLabel status={s.status} isCompact /></Td>
              <Td><CpuCell value={s.avg_cpu_pct} /></Td>
              <Td style={{ color: (s.hot_nodes ?? 0) > 0 ? 'var(--sg-color--critical)' : undefined }}>{s.hot_nodes ?? '-'}</Td>
              <Td style={{ color: (s.vms_per_node ?? 0) > 50 ? 'var(--sg-color--critical)' : (s.vms_per_node ?? 0) > 30 ? 'var(--sg-color--warning)' : undefined }}>{s.vms_per_node != null ? s.vms_per_node.toFixed(1) : '-'}</Td>
              <Td>{s.sandbox_active ?? 0}</Td>
              <Td style={{ color: (s.sandbox_failing ?? 0) > 0 ? 'var(--sg-color--critical)' : undefined }}>{s.sandbox_failing ?? 0}</Td>
              <Td style={{ color: (s.sandbox_crashloop ?? 0) > 0 ? 'var(--sg-color--critical)' : undefined }}>{s.sandbox_crashloop ?? 0}</Td>
              <Td>{s.health_rate != null && s.health_rate > 0 ? <strong style={{ color: s.health_rate >= 95 ? 'var(--sg-color--healthy)' : s.health_rate >= 80 ? 'var(--sg-color--warning)' : 'var(--sg-color--critical)' }}>{s.health_rate.toFixed(1)}%</strong> : '-'}</Td>
              <Td>
                {trendsLoading ? (
                  <Skeleton width="80px" height="30px" />
                ) : clusterTrends[s.cluster]?.length ? (
                  <TrendChart data={clusterTrends[s.cluster]!} sparkline width={80} height={30} color="#0066CC" />
                ) : (
                  <span style={{ color: 'var(--rh-color--text-secondary, #6a6e73)', fontSize: '0.8rem' }}>-</span>
                )}
              </Td>
              <Td style={{ color: (s.dns_warnings ?? 0) > 0 ? 'var(--sg-color--critical)' : undefined }}>{s.dns_warnings ?? 0}</Td>
              <Td style={{ maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.85rem' }}>{s.issues.length > 0 ? s.issues.join('; ') : '-'}</Td>
            </Tr>
          ))}
        </Tbody>
      </Table>
      </div>
    </>
  );
}

function CpuCell({ value }: { value: number | null }) {
  if (value == null) return <span style={{ color: 'var(--rh-color--text-secondary)' }}>-</span>;
  const color = value >= 80 ? 'var(--sg-color--critical)' : value >= 60 ? 'var(--sg-color--warning)' : 'var(--sg-color--healthy)';
  return <strong style={{ color }}>{value.toFixed(1)}%</strong>;
}
