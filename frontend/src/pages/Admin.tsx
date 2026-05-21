import { useState } from 'react';
import {
  Alert,
  Button,
  Card,
  CardBody,
  CardTitle,
  Content,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Label,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  PageSection,
  Spinner,
  Tab,
  Tabs,
  TabTitleText,
  TextInput,
} from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import { Select, SelectOption, SelectList, MenuToggle } from '@patternfly/react-core';
import {
  useSchedulerStatus,
  useSchedulerAction,
  useScanHistory,
  useRemediationConfigs,
  useRemediationActivity,
  useRemediationConfigMutation,
  useRemediationConfigDelete,
} from '../api/hooks';
import { useQueryClient } from '@tanstack/react-query';
import type { ExecutionMode } from '../api/types';
import StatusLabel from '../components/StatusLabel';
import TrendChart from '../components/TrendChart';
import ApprovalQueue from '../components/ApprovalQueue';

const CLUSTER_DOMAINS: Record<string, string> = {};

function clusterConsoleUrl(cluster: string): string {
  const domain = CLUSTER_DOMAINS[cluster] ?? '';
  return `https://console-openshift-console.apps.${cluster}.${domain}`;
}

function formatTime(epoch: number | null): string {
  if (!epoch) return '-';
  const d = new Date(epoch * 1000);
  const now = Date.now();
  const agoSec = Math.floor((now - d.getTime()) / 1000);
  if (agoSec < 0) return 'just now';
  if (agoSec < 60) return `${agoSec}s ago`;
  if (agoSec < 3600) return `${Math.floor(agoSec / 60)}m ago`;
  return d.toLocaleTimeString();
}

export default function Admin() {
  const [activeTab, setActiveTab] = useState(0);

  return (
    <>
      <PageSection style={{ paddingBottom: 0 }}>
        <Content>
          <Content component="h1">Admin</Content>
        </Content>
        <Tabs activeKey={activeTab} onSelect={(_e, k) => setActiveTab(k as number)} style={{ marginTop: '0.5rem' }}>
          <Tab eventKey={0} title={<TabTitleText>Scanner</TabTitleText>} />
          <Tab eventKey={1} title={<TabTitleText>Auto-Remediation</TabTitleText>} />
        </Tabs>
      </PageSection>
      {activeTab === 0 ? <ScannerTab /> : <RemediationTab />}
    </>
  );
}


function ScannerTab() {
  const { data, isLoading, isError } = useSchedulerStatus();
  const { data: history } = useScanHistory();
  const action = useSchedulerAction();
  const queryClient = useQueryClient();

  const handleAction = (type: 'start' | 'stop') => {
    action.mutate(type, {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: ['scheduler-status'] }),
    });
  };

  if (isLoading) return <PageSection><Spinner size="xl" /></PageSection>;
  if (isError) return <PageSection><Alert variant="danger" title="Failed to load scheduler status" /></PageSection>;
  if (!data) return null;

  return (
    <>
      <PageSection>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
            {data.running ? (
              <>
                <Label color="green" style={{ fontSize: '0.9rem', padding: '4px 12px' }}>Running — {data.worker_count} workers</Label>
                <Button variant="danger" size="sm" onClick={() => handleAction('stop')} isLoading={action.isPending}>
                  Stop Scanner
                </Button>
              </>
            ) : (
              <>
                <Label color="red" style={{ fontSize: '0.9rem', padding: '4px 12px' }}>Stopped</Label>
                <Button variant="primary" onClick={() => handleAction('start')} isLoading={action.isPending}>
                  Start Scanner
                </Button>
              </>
            )}
          </div>
        </div>
      </PageSection>

      <PageSection style={{ paddingTop: 0 }}>
        <ApprovalQueue />
      </PageSection>

      {!data.running && (
        <PageSection style={{ paddingTop: 0 }}>
          <Card>
            <CardBody>
              <div style={{ display: 'flex', gap: '3rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
                <div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)', marginBottom: '0.25rem' }}>Last Scan</div>
                  <div style={{ fontSize: '1.1rem', fontWeight: 600 }}>
                    {data.last_scan ? new Date(data.last_scan).toLocaleString() : 'Never'}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)', marginBottom: '0.25rem' }}>Scan History</div>
                  <div style={{ fontSize: '1.1rem', fontWeight: 600 }}>{data.scan_files ?? 0} files</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)', marginBottom: '0.25rem' }}>Clusters Configured</div>
                  <div style={{ fontSize: '1.1rem', fontWeight: 600 }}>{Object.keys(data.latest_scans || {}).length || data.worker_count || '—'}</div>
                </div>
              </div>

              <Alert variant="warning" title="Scanner is not running" isInline>
                <p>No workers are collecting cluster data. Dashboard metrics may be stale.</p>
                <p style={{ marginTop: '0.5rem' }}>
                  Click <strong>Start Scanner</strong> to launch workers for all configured clusters.
                  Each worker collects node metrics (every 5m), pod health (every 15m), and namespace evidence (every 1h).
                  Workers stagger 30s apart to avoid API server spikes.
                </p>
              </Alert>

              <div style={{ marginTop: '1.5rem' }}>
                <h4 style={{ marginBottom: '0.5rem' }}>Worker Schedule</h4>
                <Table aria-label="Schedule" variant="compact">
                  <Thead>
                    <Tr>
                      <Th>Tier</Th>
                      <Th>What</Th>
                      <Th>Interval</Th>
                      <Th>API Calls</Th>
                      <Th>Impact</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    <Tr>
                      <Td><Label isCompact color="green">Tier 1</Label></Td>
                      <Td>Node metrics (CPU, memory)</Td>
                      <Td>Every 5 min</Td>
                      <Td>2 oc calls per cluster</Td>
                      <Td><Label isCompact color="green">Minimal</Label></Td>
                    </Tr>
                    <Tr>
                      <Td><Label isCompact color="blue">Tier 2</Label></Td>
                      <Td>Pod delta scan (new failures, recoveries)</Td>
                      <Td>Every 15 min</Td>
                      <Td>1 oc call per cluster</Td>
                      <Td><Label isCompact color="green">Low</Label></Td>
                    </Tr>
                    <Tr>
                      <Td><Label isCompact color="orange">Tier 3</Label></Td>
                      <Td>Namespace evidence (rubric evaluation)</Td>
                      <Td>Every 1 hour</Td>
                      <Td>~50 oc calls (5 namespaces x 10 resources)</Td>
                      <Td><Label isCompact color="orange">Moderate</Label></Td>
                    </Tr>
                  </Tbody>
                </Table>
              </div>
            </CardBody>
          </Card>
        </PageSection>
      )}

      {data.running && data.unavailable_clusters && data.unavailable_clusters.length > 0 && (
        <PageSection style={{ paddingTop: 0 }}>
          <Alert variant="warning" title={`${data.unavailable_clusters.length} cluster(s) unavailable — tokens expired`} isInline>
            <p>These clusters could not authenticate with <code>oc whoami</code>. Kubeconfig tokens need to be refreshed:</p>
            <div style={{ marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              {data.unavailable_clusters.map(c => (
                <a key={c} href={clusterConsoleUrl(c)} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                  <Label isCompact color="orange" style={{ cursor: 'pointer' }}>{c}</Label>
                </a>
              ))}
            </div>
            <p style={{ marginTop: '0.5rem', fontSize: '0.85rem' }}>
              Run <code>oc login</code> for each cluster and update the kubeconfig files in <code>secrets/</code>, then restart the scanner.
            </p>
          </Alert>
        </PageSection>
      )}

      {data.running && data.available_clusters && data.available_clusters.length > 0 && (
        <PageSection style={{ paddingTop: 0 }}>
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center', fontSize: '0.9rem' }}>
            <strong>Active workers:</strong>
            {data.available_clusters.map(c => (
              <a key={c} href={clusterConsoleUrl(c)} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                <Label isCompact color="green" style={{ cursor: 'pointer' }}>{c}</Label>
              </a>
            ))}
          </div>
        </PageSection>
      )}

      {data.running && data.workers.length > 0 && (
        <PageSection style={{ paddingTop: 0 }}>
          <Card>
            <CardTitle>Cluster Workers ({data.workers.length})</CardTitle>
            <CardBody>
              <div className="sg-table-wrap">
              <Table aria-label="Workers" variant="compact">
                <Thead>
                  <Tr>
                    <Th>Cluster</Th>
                    <Th>Status</Th>
                    <Th>Ticks</Th>
                    <Th>CPU</Th>
                    <Th>VMs</Th>
                    <Th>VM/Node</Th>
                    <Th>Crashloop</Th>
                    <Th>New Fail</Th>
                    <Th>Recovered</Th>
                    <Th>NS Scanned</Th>
                    <Th>Last Nodes</Th>
                    <Th>Last Pods</Th>
                    <Th>Last NS</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {data.workers.map(w => (
                    <Tr key={w.cluster}>
                      <Td><a href={clusterConsoleUrl(w.cluster)} target="_blank" rel="noreferrer" style={{ color: 'var(--sg-color--info)', fontWeight: 600, textDecoration: 'none' }}>{w.cluster}</a></Td>
                      <Td>
                        {w.errors > 0 ? (
                          <Label isCompact color="red">Error ({w.errors})</Label>
                        ) : w.node_status && w.node_status !== 'pending' ? (
                          <StatusLabel status={w.node_status} isCompact />
                        ) : (
                          <Label isCompact color="blue">Starting ({w.offset}s offset)</Label>
                        )}
                      </Td>
                      <Td>{w.ticks}</Td>
                      <Td style={{ color: (w.avg_cpu ?? 0) > 80 ? 'var(--sg-color--critical)' : (w.avg_cpu ?? 0) > 60 ? 'var(--sg-color--warning)' : undefined }}>
                        {w.avg_cpu != null && w.ticks > 0 ? `${w.avg_cpu.toFixed(0)}%` : '-'}
                      </Td>
                      <Td>{w.ticks > 0 ? (w.total_vms ?? 0) : '-'}</Td>
                      <Td style={{ color: (w.vms_per_node ?? 0) > 100 ? 'var(--sg-color--critical)' : (w.vms_per_node ?? 0) > 50 ? 'var(--sg-color--warning)' : undefined }}>
                        {w.ticks > 0 && w.vms_per_node != null ? w.vms_per_node.toFixed(0) : '-'}
                      </Td>
                      <Td style={{ color: (w.crashloops ?? 0) > 0 ? 'var(--sg-color--critical)' : undefined }}>
                        {w.ticks > 0 ? (w.crashloops ?? 0) : '-'}
                      </Td>
                      <Td style={{ color: (w.new_failures ?? 0) > 0 ? 'var(--sg-color--critical)' : undefined }}>
                        {w.ticks > 0 ? <strong>{w.new_failures ?? 0}</strong> : '-'}
                      </Td>
                      <Td style={{ color: (w.recovered ?? 0) > 0 ? 'var(--sg-color--healthy)' : undefined }}>
                        {w.ticks > 0 ? (w.recovered ?? 0) : '-'}
                      </Td>
                      <Td>
                        {w.ns_scanned != null && w.ns_available != null && w.ticks > 0 ? (
                          <span>{w.ns_scanned}/{w.ns_available}</span>
                        ) : '-'}
                      </Td>
                      <Td style={{ fontSize: '0.8rem' }}>{formatTime(w.last_node_scan)}</Td>
                      <Td style={{ fontSize: '0.8rem' }}>{formatTime(w.last_pod_scan)}</Td>
                      <Td style={{ fontSize: '0.8rem' }}>{formatTime(w.last_ns_scan)}</Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
              </div>
            </CardBody>
          </Card>
        </PageSection>
      )}

      {data.running && data.workers.length === 0 && (
        <PageSection style={{ paddingTop: 0 }}>
          <Card>
            <CardBody>
              <Spinner size="md" style={{ marginRight: '0.5rem' }} />
              Workers are initializing...
            </CardBody>
          </Card>
        </PageSection>
      )}

      {data.latest_scans && Object.keys(data.latest_scans).length > 0 && (
        <PageSection style={{ paddingTop: 0 }}>
          <Card>
            <CardTitle>Cluster State</CardTitle>
            <CardBody>
              <div className="sg-table-wrap">
              <Table aria-label="Scan history" variant="compact">
                <Thead>
                  <Tr>
                    <Th>Cluster</Th>
                    <Th>Status</Th>
                    <Th>CPU</Th>
                    <Th>Hot Nodes</Th>
                    <Th>VMs</Th>
                    <Th>VM/Node</Th>
                    <Th>Labs</Th>
                    <Th>Failing</Th>
                    <Th>Crashloop</Th>
                    <Th>Health %</Th>
                    <Th>Scanned</Th>
                    <Th>Issues</Th>
                  </Tr>
                </Thead>
                <Tbody>
                  {Object.entries(data.latest_scans)
                    .sort(([a], [b]) => a.localeCompare(b))
                    .map(([cluster, s]) => (
                      <Tr key={cluster}>
                        <Td>
                          <a href={clusterConsoleUrl(cluster)} target="_blank" rel="noreferrer" style={{ color: 'var(--sg-color--info)', fontWeight: 600, textDecoration: 'none' }}>
                            {cluster}
                          </a>
                        </Td>
                        <Td><StatusLabel status={s.status} isCompact /></Td>
                        <Td style={{ color: (s.avg_cpu_pct ?? 0) > 80 ? 'var(--sg-color--critical)' : (s.avg_cpu_pct ?? 0) > 60 ? 'var(--sg-color--warning)' : undefined }}>
                          {s.avg_cpu_pct != null ? `${s.avg_cpu_pct.toFixed(1)}%` : '-'}
                        </Td>
                        <Td style={{ color: (s.hot_nodes ?? 0) > 0 ? 'var(--sg-color--critical)' : undefined }}>{s.hot_nodes ?? '-'}</Td>
                        <Td>{s.total_vms}</Td>
                        <Td style={{ color: s.vms_per_node > 100 ? 'var(--sg-color--critical)' : s.vms_per_node > 50 ? 'var(--sg-color--warning)' : undefined }}>
                          {s.vms_per_node.toFixed(1)}
                        </Td>
                        <Td>{s.sandbox_active}</Td>
                        <Td style={{ color: s.sandbox_failing > 0 ? 'var(--sg-color--critical)' : undefined }}>
                          <strong>{s.sandbox_failing}</strong>
                        </Td>
                        <Td style={{ color: (s.sandbox_crashloop ?? 0) > 0 ? 'var(--sg-color--critical)' : undefined }}>
                          {s.sandbox_crashloop ?? 0}
                        </Td>
                        <Td>
                          <strong style={{ color: s.health_rate >= 95 ? 'var(--sg-color--healthy)' : s.health_rate >= 80 ? 'var(--sg-color--warning)' : 'var(--sg-color--critical)' }}>
                            {s.health_rate.toFixed(1)}%
                          </strong>
                        </Td>
                        <Td style={{ fontSize: '0.8rem' }}>
                          {s.source === 'live'
                            ? <Label isCompact color="green">Live</Label>
                            : new Date(s.scan_time).toLocaleString()}
                        </Td>
                        <Td style={{ maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '0.8rem' }}>
                          {s.issues.length > 0 ? s.issues.join('; ') : '-'}
                        </Td>
                      </Tr>
                    ))}
                </Tbody>
              </Table>
              </div>
            </CardBody>
          </Card>
        </PageSection>
      )}

      {data.running && data.babylon && (
        <PageSection style={{ paddingTop: 0 }}>
          <Card>
            <CardTitle>Babylon Control Plane</CardTitle>
            <CardBody>
              <DescriptionList isHorizontal isCompact>
                <DescriptionListGroup>
                  <DescriptionListTerm>Pools</DescriptionListTerm>
                  <DescriptionListDescription>
                    {data.babylon.total_pools} total, {' '}
                    <strong style={{ color: data.babylon.exhausted > 0 ? 'var(--sg-color--critical)' : undefined }}>{data.babylon.exhausted} exhausted</strong>, {' '}
                    {data.babylon.low} low
                  </DescriptionListDescription>
                </DescriptionListGroup>
                <DescriptionListGroup>
                  <DescriptionListTerm>Provisioning</DescriptionListTerm>
                  <DescriptionListDescription>
                    {data.babylon.total_subjects} subjects, {data.babylon.started} started, {' '}
                    <strong style={{ color: data.babylon.failed > 0 ? 'var(--sg-color--critical)' : undefined }}>{data.babylon.failed} failed</strong>
                  </DescriptionListDescription>
                </DescriptionListGroup>
              </DescriptionList>
            </CardBody>
          </Card>
        </PageSection>
      )}

      {data.running && data.workers.some(w => w.recent_failures && w.recent_failures.length > 0) && (
        <PageSection style={{ paddingTop: 0 }}>
          <Card>
            <CardTitle>Recent Failures Detected</CardTitle>
            <CardBody>
              {data.workers
                .filter(w => w.recent_failures && w.recent_failures.length > 0)
                .map(w => (
                  <div key={w.cluster} style={{ marginBottom: '0.5rem' }}>
                    <strong>{w.cluster}</strong>:
                    {w.recent_failures!.map((f, i) => (
                      <Label key={i} isCompact color="red" style={{ marginLeft: '0.5rem' }}>{f.pod} ({f.status})</Label>
                    ))}
                  </div>
                ))}
            </CardBody>
          </Card>
        </PageSection>
      )}
      <ScanHistorySection history={history ?? null} />
    </>
  );
}

const MODE_LABELS: Record<ExecutionMode, string> = {
  recommend_only: 'Recommend Only',
  low_risk_auto: 'Low-Risk Auto',
  full_auto: 'Full Auto',
};

const MODE_COLORS: Record<ExecutionMode, 'grey' | 'blue' | 'green'> = {
  recommend_only: 'grey',
  low_risk_auto: 'blue',
  full_auto: 'green',
};

const MODES: ExecutionMode[] = ['recommend_only', 'low_risk_auto', 'full_auto'];

function ModeSelect({ value, onChange }: { value: ExecutionMode; onChange: (m: ExecutionMode) => void }) {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <Select
      isOpen={isOpen}
      onOpenChange={setIsOpen}
      onSelect={(_e, val) => { onChange(val as ExecutionMode); setIsOpen(false); }}
      selected={value}
      toggle={(toggleRef) => (
        <MenuToggle ref={toggleRef} onClick={() => setIsOpen(!isOpen)} isExpanded={isOpen} style={{ minWidth: '160px' }}>
          <Label isCompact color={MODE_COLORS[value]}>{MODE_LABELS[value]}</Label>
        </MenuToggle>
      )}
    >
      <SelectList>
        {MODES.map(m => (
          <SelectOption key={m} value={m}>
            <Label isCompact color={MODE_COLORS[m]}>{MODE_LABELS[m]}</Label>
          </SelectOption>
        ))}
      </SelectList>
    </Select>
  );
}

function RemediationTab() {
  const { data: configData, isLoading } = useRemediationConfigs();
  const { data: activityData } = useRemediationActivity();
  const updateMutation = useRemediationConfigMutation();
  const deleteMutation = useRemediationConfigDelete();

  const [confirmModal, setConfirmModal] = useState<{ labCode: string; mode: ExecutionMode } | null>(null);
  const [addLabCode, setAddLabCode] = useState('');

  const configs = configData?.configs ?? [];
  const activity = activityData?.activity ?? [];

  const counts = { recommend_only: 0, low_risk_auto: 0, full_auto: 0 };
  for (const c of configs) {
    if (c.execution_mode in counts) counts[c.execution_mode as ExecutionMode]++;
  }

  const handleModeChange = (labCode: string, newMode: ExecutionMode) => {
    const current = configs.find(c => c.lab_code === labCode);
    const currentMode = current?.execution_mode ?? 'recommend_only';
    const isUpgrade = MODES.indexOf(newMode) > MODES.indexOf(currentMode);
    if (isUpgrade) {
      setConfirmModal({ labCode, mode: newMode });
    } else {
      updateMutation.mutate({ labCode, mode: newMode });
    }
  };

  const handleAddLab = () => {
    if (!addLabCode.trim()) return;
    updateMutation.mutate({ labCode: addLabCode.trim(), mode: 'recommend_only' });
    setAddLabCode('');
  };

  if (isLoading) return <PageSection><Spinner size="xl" /></PageSection>;

  return (
    <>
      <PageSection style={{ paddingTop: '1rem' }}>
        <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
          {(Object.entries(counts) as [ExecutionMode, number][]).map(([mode, count]) => (
            <div key={mode}>
              <div style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)', marginBottom: '0.25rem' }}>
                {MODE_LABELS[mode]}
              </div>
              <div style={{ fontSize: '1.5rem', fontWeight: 600 }}>
                <Label color={MODE_COLORS[mode]}>{count}</Label>
              </div>
            </div>
          ))}
        </div>

        <Alert variant="info" isInline title="Gradual rollout" style={{ marginBottom: '1rem' }}>
          Labs default to Recommend Only. Promote to Low-Risk Auto (executes low-risk actions) or Full Auto (low + medium risk).
          The stargate-test namespace always allows full auto-execution regardless of this config.
        </Alert>

        <Card>
          <CardTitle>Lab Remediation Config</CardTitle>
          <CardBody>
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', alignItems: 'center' }}>
              <TextInput
                value={addLabCode}
                onChange={(_e, v) => setAddLabCode(v)}
                placeholder="lab-code (e.g. summit-lb1)"
                style={{ maxWidth: '300px' }}
              />
              <Button variant="secondary" size="sm" onClick={handleAddLab} isDisabled={!addLabCode.trim()}>
                Add Lab
              </Button>
            </div>
            <div className="sg-table-wrap">
              <Table aria-label="Remediation configs" variant="compact">
                <Thead>
                  <Tr>
                    <Th>Lab Code</Th>
                    <Th>Display Name</Th>
                    <Th>Execution Mode</Th>
                    <Th>Max/hr</Th>
                    <Th>Enabled By</Th>
                    <Th>Enabled At</Th>
                    <Th>Notes</Th>
                    <Th />
                  </Tr>
                </Thead>
                <Tbody>
                  {configs.length === 0 && (
                    <Tr>
                      <Td colSpan={8} style={{ textAlign: 'center', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>
                        No labs configured. All labs use Recommend Only by default.
                      </Td>
                    </Tr>
                  )}
                  {configs.map(c => (
                    <Tr key={c.lab_code}>
                      <Td><strong>{c.lab_code}</strong></Td>
                      <Td style={{ fontSize: '0.85rem' }}>{c.display_name !== c.lab_code ? c.display_name : '-'}</Td>
                      <Td>
                        <ModeSelect
                          value={c.execution_mode}
                          onChange={(m) => handleModeChange(c.lab_code, m)}
                        />
                      </Td>
                      <Td>{c.max_actions_per_hour}</Td>
                      <Td style={{ fontSize: '0.85rem' }}>{c.enabled_by ?? '-'}</Td>
                      <Td style={{ fontSize: '0.8rem' }}>
                        {c.enabled_at ? new Date(c.enabled_at).toLocaleString() : '-'}
                      </Td>
                      <Td style={{ fontSize: '0.85rem', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {c.notes ?? '-'}
                      </Td>
                      <Td>
                        <Button variant="link" isDanger size="sm" onClick={() => deleteMutation.mutate(c.lab_code)}>
                          Reset
                        </Button>
                      </Td>
                    </Tr>
                  ))}
                </Tbody>
              </Table>
            </div>
          </CardBody>
        </Card>
      </PageSection>

      <PageSection style={{ paddingTop: 0 }}>
        <Card>
          <CardTitle>Recent Remediation Activity</CardTitle>
          <CardBody>
            {activity.length === 0 ? (
              <div style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>No remediation activity recorded yet.</div>
            ) : (
              <div className="sg-table-wrap">
                <Table aria-label="Remediation activity" variant="compact">
                  <Thead>
                    <Tr>
                      <Th>Time</Th>
                      <Th>Action</Th>
                      <Th>Target</Th>
                      <Th>Status</Th>
                      <Th>By</Th>
                      <Th>Result</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {activity.slice(0, 20).map(a => (
                      <Tr key={a.id}>
                        <Td style={{ fontSize: '0.8rem', whiteSpace: 'nowrap' }}>
                          {a.created_at ? new Date(a.created_at).toLocaleString() : '-'}
                        </Td>
                        <Td><Label isCompact>{a.action_type}</Label></Td>
                        <Td style={{ fontSize: '0.85rem' }}>{a.target}</Td>
                        <Td>
                          <Label isCompact color={a.status === 'executed' ? 'green' : a.status === 'failed' ? 'red' : 'grey'}>
                            {a.status}
                          </Label>
                        </Td>
                        <Td style={{ fontSize: '0.85rem' }}>{a.proposed_by ?? '-'}</Td>
                        <Td style={{ fontSize: '0.8rem', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {a.result ?? '-'}
                        </Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              </div>
            )}
          </CardBody>
        </Card>
      </PageSection>

      {confirmModal && (
        <Modal
          isOpen
          onClose={() => setConfirmModal(null)}
          variant="small"
        >
          <ModalHeader title="Confirm Execution Mode Upgrade" />
          <ModalBody>
            Upgrade <strong>{confirmModal.labCode}</strong> to{' '}
            <Label color={MODE_COLORS[confirmModal.mode]}>{MODE_LABELS[confirmModal.mode]}</Label>?
            {confirmModal.mode === 'full_auto' && (
              <Alert variant="warning" isInline title="Full Auto enables low and medium risk actions" style={{ marginTop: '0.75rem' }}>
                This lab will auto-execute remediation commands without manual approval for low and medium risk catalog entries.
              </Alert>
            )}
          </ModalBody>
          <ModalFooter>
            <Button
              variant="primary"
              onClick={() => {
                updateMutation.mutate({ labCode: confirmModal.labCode, mode: confirmModal.mode });
                setConfirmModal(null);
              }}
            >
              Confirm
            </Button>
            <Button variant="link" onClick={() => setConfirmModal(null)}>Cancel</Button>
          </ModalFooter>
        </Modal>
      )}
    </>
  );
}


const HISTORY_COLORS = ['#0066CC', '#3E8635', '#F0AB00', '#C9190B', '#6753AC', '#009596'];

function ScanHistorySection({ history }: { history: import('../api/types').ScanHistory | null }) {
  if (!history || history.timeline.length === 0) return null;

  const clusters = new Set<string>();
  for (const entry of history.timeline) {
    for (const c of Object.keys(entry.clusters)) clusters.add(c);
  }
  const clusterList = [...clusters].filter(c => !c.includes('infra') && c !== 'ocp-us-east-1').sort();

  if (clusterList.length === 0) return null;

  const cpuData: Record<string, { x: number; y: number }[]> = {};
  const healthData: Record<string, { x: number; y: number }[]> = {};
  const vmData: Record<string, { x: number; y: number }[]> = {};

  for (const entry of history.timeline) {
    const ts = new Date(entry.timestamp).getTime();
    for (const c of clusterList) {
      const s = entry.clusters[c];
      if (!s) continue;
      if (!cpuData[c]) cpuData[c] = [];
      if (!healthData[c]) healthData[c] = [];
      if (!vmData[c]) vmData[c] = [];
      if (s.avg_cpu_pct != null) cpuData[c]!.push({ x: ts, y: s.avg_cpu_pct });
      healthData[c]!.push({ x: ts, y: s.health_rate });
      vmData[c]!.push({ x: ts, y: s.total_vms });
    }
  }

  return (
    <PageSection style={{ paddingTop: 0 }}>
      <Card>
        <CardTitle>Scan History ({history.total_files} scans)</CardTitle>
        <CardBody>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2rem' }}>
            <div>
              <h4 style={{ marginBottom: '0.5rem', fontSize: '0.9rem' }}>CPU % by Cluster</h4>
              {clusterList.map((c, i) => (
                cpuData[c]?.length ? (
                  <div key={c} style={{ marginBottom: '0.25rem' }}>
                    <span style={{ fontSize: '0.75rem', color: HISTORY_COLORS[i % HISTORY_COLORS.length], fontWeight: 600 }}>{c}</span>
                    <TrendChart data={cpuData[c]!} color={HISTORY_COLORS[i % HISTORY_COLORS.length]} height={40} width={300} sparkline />
                  </div>
                ) : null
              ))}
            </div>
            <div>
              <h4 style={{ marginBottom: '0.5rem', fontSize: '0.9rem' }}>Health % by Cluster</h4>
              {clusterList.map((c, i) => (
                healthData[c]?.length ? (
                  <div key={c} style={{ marginBottom: '0.25rem' }}>
                    <span style={{ fontSize: '0.75rem', color: HISTORY_COLORS[i % HISTORY_COLORS.length], fontWeight: 600 }}>{c}</span>
                    <TrendChart data={healthData[c]!} color={HISTORY_COLORS[i % HISTORY_COLORS.length]} height={40} width={300} sparkline />
                  </div>
                ) : null
              ))}
            </div>
            <div>
              <h4 style={{ marginBottom: '0.5rem', fontSize: '0.9rem' }}>Total VMs by Cluster</h4>
              {clusterList.map((c, i) => (
                vmData[c]?.length ? (
                  <div key={c} style={{ marginBottom: '0.25rem' }}>
                    <span style={{ fontSize: '0.75rem', color: HISTORY_COLORS[i % HISTORY_COLORS.length], fontWeight: 600 }}>{c}</span>
                    <TrendChart data={vmData[c]!} color={HISTORY_COLORS[i % HISTORY_COLORS.length]} height={40} width={300} sparkline />
                  </div>
                ) : null
              ))}
            </div>
          </div>

          <h4 style={{ marginTop: '1.5rem', marginBottom: '0.5rem', fontSize: '0.9rem' }}>Scan Timeline</h4>
          <div className="sg-table-wrap">
            <Table aria-label="Scan history timeline" variant="compact">
              <Thead>
                <Tr>
                  <Th>Time</Th>
                  {clusterList.map(c => <Th key={c}>{c}</Th>)}
                </Tr>
              </Thead>
              <Tbody>
                {[...history.timeline].reverse().map((entry, i) => (
                  <Tr key={i}>
                    <Td style={{ fontSize: '0.8rem', whiteSpace: 'nowrap' }}>{new Date(entry.timestamp).toLocaleString()}</Td>
                    {clusterList.map(c => {
                      const s = entry.clusters[c];
                      if (!s) return <Td key={c}>-</Td>;
                      return (
                        <Td key={c} style={{ fontSize: '0.8rem' }}>
                          <StatusLabel status={s.status} isCompact />
                          {' '}{s.avg_cpu_pct != null ? `${s.avg_cpu_pct.toFixed(0)}%` : '-'}
                          {' '}<span style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>{s.total_vms}vm</span>
                          {s.sandbox_failing > 0 && <span style={{ color: 'var(--sg-color--critical)', marginLeft: '4px' }}>{s.sandbox_failing}fail</span>}
                        </Td>
                      );
                    })}
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </div>
        </CardBody>
      </Card>
    </PageSection>
  );
}
