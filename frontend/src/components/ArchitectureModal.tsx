import { useState } from 'react';
import {
  Button,
  Label,
  Modal,
  ModalBody,
  ModalHeader,
  ModalFooter,
  Spinner,
  Tab,
  TabContent,
  TabTitleText,
  Tabs,
} from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import { useDataMapping } from '../api/hooks';

const SOURCES = [
  {
    name: 'Labagator',
    color: 'blue' as const,
    url: 'Labagator REST API (configured via STARGATE_LABAGATOR_URL)',
    provides: ['Lab metadata (code, title, status, cloud)', 'Session schedule (dates, rooms, attendees)', 'Developer & ops assignments', 'Lab development stage (planning/building)'],
    feedsTo: ['Labs View', 'Readiness Banner', 'Executive Summary'],
    refresh: 'Every 30s via dashboard polling',
  },
  {
    name: 'Demolition',
    color: 'orange' as const,
    url: 'Demolition REST API (configured via STARGATE_DEMOLITION_URL)',
    provides: ['Smoke test results (pass/fail per worker)', 'Load test history', 'Worker count and completion rates'],
    feedsTo: ['Labs View (Smoke Test column)', 'Lab Drawer (failure analysis)', 'Executive Summary'],
    refresh: 'Every 30s via dashboard polling',
  },
  {
    name: 'Babylon Control Plane',
    color: 'purple' as const,
    url: 'ocp-us-east-1 cluster via oc CLI',
    provides: ['ResourcePool capacity (available, ready, min)', 'AnarchySubject provisioning state', 'Lab-to-instance mapping', 'CatalogItem and Workshop counts'],
    feedsTo: ['Pools View', 'Labs View (Capacity column)', 'Readiness Banner (provisioning gate)'],
    refresh: 'Every 3 min via Babylon worker',
  },
  {
    name: 'Cluster Scanners (9 clusters)',
    color: 'green' as const,
    url: 'Configured clusters via kubeconfigs (STARGATE_CLUSTERS env var)',
    provides: [
      'Tier 1 (5 min): Node CPU/memory, hot nodes',
      'Tier 2 (5 min): Pod status, sandbox health, VM count, crashloops',
      'Tier 3 (5 min): Namespace evidence — 150 namespaces/batch with rubric evaluation',
      'Showroom HTTP health checks',
    ],
    feedsTo: ['Clusters View', 'Admin Page (workers)', 'Readiness Banner (health gate)', 'Pipeline View'],
    refresh: 'Every 5 min per tier, staggered 30s between clusters',
  },
  {
    name: 'StarGate Engine',
    color: 'red' as const,
    url: 'PostgreSQL (stargate database)',
    provides: [
      '11 rubric stages: cluster-health, namespace-ready, deployment-ready, route-ready, vm-runtime-ready, etc.',
      'Evidence collection and persistence',
      'Failure classification (pods_not_ready, route_missing, etc.)',
      'Evaluation history with timestamps',
    ],
    feedsTo: ['Pipeline View', 'Errors View', 'Lab Drawer (evaluations)', 'Trends Charts'],
    refresh: 'Continuous — evaluations persisted on each namespace scan',
  },
  {
    name: 'Event Bus',
    color: 'grey' as const,
    url: 'In-memory event processing pipeline',
    provides: [
      'Nanoagent pipeline: Filter → Correlate → Triage → Impact',
      'Systemic issue detection (>20% same failure on cluster)',
      'Blast radius estimation (failing labs per cluster)',
      'Priority scoring (0-10) and escalation',
    ],
    feedsTo: ['Errors View (blast radius)', 'Event Feed', 'Readiness Banner (escalation alerts)'],
    refresh: 'Real-time — processes each evaluation event',
  },
  {
    name: 'LLM Engine (via LiteLLM)',
    color: 'blue' as const,
    url: 'Configurable via STARGATE_LITELLM_URL + STARGATE_LLM_MODEL',
    provides: ['Executive readiness summary', 'Per-lab remediation analysis', 'Cluster diagnostics', 'Failure root cause analysis'],
    feedsTo: ['Executive Summary', 'AI Analysis buttons on all drawers'],
    refresh: 'On-demand — triggered by user click',
  },
  {
    name: 'AgnosticV',
    color: 'grey' as const,
    url: 'Local git repository (agnosticv/*.yaml)',
    provides: ['Lab deployment constraints', 'Cloud provider requirements', 'OCP version requirements', 'Operator channel specifications'],
    feedsTo: ['Lab Drawer (constraints section)', 'Lab Detail Page'],
    refresh: 'Cached — refreshed every 10 min',
  },
  {
    name: 'Sandbox-API',
    color: 'purple' as const,
    url: 'babylon-sandbox-api deployment on infra01',
    provides: ['API deployment health (replicas, pod status)', 'Sandbox namespace counts per cluster', 'Crashloop and failure detection'],
    feedsTo: ['Readiness Banner (sandbox-api gate)', 'Capacity Analysis', 'Executive Summary'],
    refresh: 'Every 5 min via scanner data',
  },
  {
    name: 'ZeroTouch',
    color: 'orange' as const,
    url: 'Configurable via STARGATE_ZEROTOUCH_URL',
    provides: ['Catalog item availability', 'Workshop seat counts', 'Service request status'],
    feedsTo: ['Executive Summary', 'Capacity Analysis'],
    refresh: 'Every 5 min, cached 5 min',
  },
];

function FlowDiagram() {
  const W = 960;
  const H = 720;

  const box = (x: number, y: number, w: number, h: number, label: string, sub: string, fill: string, stroke: string) => (
    <g key={label}>
      <rect x={x} y={y} width={w} height={h} rx={6} fill={fill} stroke={stroke} strokeWidth={2} />
      <text x={x + w / 2} y={y + h / 2 - 6} textAnchor="middle" fontSize={12} fontWeight={700} fill="#151515">{label}</text>
      <text x={x + w / 2} y={y + h / 2 + 10} textAnchor="middle" fontSize={9} fill="#6a6e73">{sub}</text>
    </g>
  );

  const arrow = (x1: number, y1: number, x2: number, y2: number, label?: string, dashed?: boolean) => (
    <g key={`${x1}-${y1}-${x2}-${y2}`}>
      <defs><marker id="ah" markerWidth={8} markerHeight={6} refX={8} refY={3} orient="auto"><polygon points="0 0, 8 3, 0 6" fill="#6a6e73" /></marker></defs>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="#6a6e73" strokeWidth={1.5} markerEnd="url(#ah)" strokeDasharray={dashed ? '4 3' : undefined} />
      {label && <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 5} textAnchor="middle" fontSize={8} fill="#6a6e73">{label}</text>}
    </g>
  );

  return (
    <div style={{ overflowX: 'auto' }}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ fontFamily: 'Red Hat Text, sans-serif' }}>
        {/* Title */}
        <text x={W / 2} y={24} textAnchor="middle" fontSize={16} fontWeight={700} fill="#151515">StarGate Platform — Data Flow</text>
        <text x={W / 2} y={42} textAnchor="middle" fontSize={10} fill="#6a6e73">All cluster operations are read-only. No writes to production infrastructure.</text>

        {/* Row 1: External Data Sources */}
        <text x={20} y={75} fontSize={11} fontWeight={600} fill="#6a6e73">EXTERNAL DATA SOURCES</text>
        {box(20, 85, 150, 50, 'Labagator', 'Labs, Sessions, People', '#E7F1FF', '#0066CC')}
        {box(190, 85, 150, 50, 'Demolition', 'Smoke Tests', '#FFF4E6', '#F0AB00')}
        {box(360, 85, 150, 50, 'Babylon', 'Pools, Provisioning', '#F3F0FF', '#6753AC')}
        {box(530, 85, 130, 50, 'AgnosticV', 'Constraints', '#F0F0F0', '#8A8D90')}
        {box(680, 85, 130, 50, 'LLM Engine', 'via LiteLLM', '#E7F1FF', '#0066CC')}

        {/* Arrows from center-bottom of each source to center-top of StarGate API (x=120, y=205) */}
        {arrow(95, 135, 120, 205, 'labs, sessions')}
        {arrow(265, 135, 120, 205, 'test results')}
        {arrow(435, 135, 120, 205, 'pools, subjects')}
        {arrow(595, 135, 120, 205, 'constraints', true)}
        {arrow(745, 135, 120, 205, 'AI analysis', true)}

        {/* Row 2: StarGate Platform */}
        <text x={20} y={195} fontSize={11} fontWeight={600} fill="#6a6e73">STARGATE PLATFORM</text>
        {box(20, 205, 200, 60, 'StarGate API', 'FastAPI — aggregation, evaluation', '#FCEAEA', '#C9190B')}
        {box(240, 205, 200, 60, 'Scheduler', '9 cluster workers, staggered', '#F3FAF2', '#3E8635')}
        {box(460, 205, 160, 60, 'Rubric Engine', '11 stages, evaluations', '#FCEAEA', '#C9190B')}
        {box(640, 205, 160, 60, 'Event Bus', 'Filter→Correlate→Triage', '#F0F0F0', '#8A8D90')}
        {box(820, 205, 120, 60, 'PostgreSQL', 'Persistence', '#F0F0F0', '#8A8D90')}

        {/* Internal horizontal arrows between platform components */}
        {arrow(220, 235, 240, 235)}
        {arrow(440, 235, 460, 235)}
        {arrow(620, 235, 640, 235)}
        {arrow(800, 235, 820, 235)}

        {/* Row 3: Cluster Scanning Detail */}
        <text x={20} y={295} fontSize={11} fontWeight={600} fill="#6a6e73">CLUSTER SCANNING (read-only)</text>
        {box(20, 305, 130, 50, 'Tier 1: Nodes', 'CPU, memory (5 min)', '#F3FAF2', '#3E8635')}
        {box(165, 305, 130, 50, 'Tier 2: Pods', 'Health, VMs (5 min)', '#F3FAF2', '#3E8635')}
        {box(310, 305, 150, 50, 'Tier 3: Namespaces', '150/batch (5 min)', '#F3FAF2', '#3E8635')}
        {box(475, 305, 130, 50, 'HTTP Checks', 'Showroom probes', '#F3FAF2', '#3E8635')}
        {box(620, 305, 150, 50, 'Cluster Health', 'Rubric evaluation', '#FCEAEA', '#C9190B')}

        {/* Arrows from scheduler center-bottom to each tier center-top */}
        {arrow(340, 265, 85, 305)}
        {arrow(340, 265, 230, 305)}
        {arrow(340, 265, 385, 305)}
        {arrow(340, 265, 540, 305)}
        {arrow(540, 265, 695, 305)}

        {/* Row 3b: Clusters */}
        {box(20, 380, 900, 40, '9 OpenShift Clusters: ocpv05  |  ocpv06  |  ocpv07  |  ocpv08  |  ocpv09  |  ocpv10  |  infra01  |  infra02  |  us-east-1', '', '#F8F9FA', '#D2D2D2')}

        {/* Arrows from each tier down to the clusters bar */}
        {arrow(85, 355, 85, 380, 'oc adm top')}
        {arrow(230, 355, 230, 380, 'oc get pods -A')}
        {arrow(385, 355, 385, 380, 'oc get ns,svc,route...')}
        {arrow(540, 355, 540, 380, 'https GET')}

        {/* Row 4: Dashboard Views */}
        <text x={20} y={450} fontSize={11} fontWeight={600} fill="#6a6e73">DASHBOARD VIEWS</text>
        {box(20, 460, 110, 50, 'Labs View', '71 labs, readiness', '#E7F1FF', '#0066CC')}
        {box(145, 460, 110, 50, 'Clusters View', 'Health, CPU, VMs', '#E7F1FF', '#0066CC')}
        {box(270, 460, 110, 50, 'Pools View', 'Capacity, status', '#E7F1FF', '#0066CC')}
        {box(395, 460, 110, 50, 'Errors View', 'Failures, blast', '#E7F1FF', '#0066CC')}
        {box(520, 460, 110, 50, 'Pipeline View', 'Stage pass rates', '#E7F1FF', '#0066CC')}
        {box(645, 460, 110, 50, 'Admin Page', 'Workers, history', '#E7F1FF', '#0066CC')}
        {box(770, 460, 150, 50, 'Executive Summary', 'AI readiness report', '#E7F1FF', '#0066CC')}

        {/* Arrows from API/platform down to dashboard views */}
        {arrow(75, 420, 75, 460, '', true)}
        {arrow(200, 420, 200, 460, '', true)}
        {arrow(325, 420, 325, 460, '', true)}
        {arrow(450, 420, 450, 460, '', true)}
        {arrow(575, 420, 575, 460, '', true)}
        {arrow(700, 420, 700, 460, '', true)}
        {arrow(845, 420, 845, 460, '', true)}

        {/* Row 5: Key outputs */}
        <text x={20} y={540} fontSize={11} fontWeight={600} fill="#6a6e73">KEY OUTPUTS</text>
        {box(20, 550, 150, 50, 'Readiness Score', '40% prov + 30% health...', '#F3FAF2', '#3E8635')}
        {box(185, 550, 120, 50, 'Scan History', 'JSON files (5 min)', '#F0F0F0', '#8A8D90')}
        {box(320, 550, 120, 50, 'Event Stream', 'Systemic detection', '#FFF4E6', '#F0AB00')}
        {box(455, 550, 130, 50, 'Failure Classes', 'Categorized issues', '#FCEAEA', '#C9190B')}
        {box(600, 550, 120, 50, 'Delta Tracking', 'Change detection', '#F3FAF2', '#3E8635')}
        {box(735, 550, 180, 50, 'AI Remediation', 'LLM via LiteLLM', '#E7F1FF', '#0066CC')}

        {/* Legend */}
        <rect x={20} y={630} width={920} height={70} rx={4} fill="#F8F9FA" stroke="#D2D2D2" />
        <text x={30} y={650} fontSize={10} fontWeight={600}>LEGEND:</text>
        <rect x={30} y={658} width={14} height={14} rx={2} fill="#E7F1FF" stroke="#0066CC" strokeWidth={1.5} />
        <text x={50} y={669} fontSize={9}>External API / UI</text>
        <rect x={150} y={658} width={14} height={14} rx={2} fill="#FCEAEA" stroke="#C9190B" strokeWidth={1.5} />
        <text x={170} y={669} fontSize={9}>StarGate Core</text>
        <rect x={270} y={658} width={14} height={14} rx={2} fill="#F3FAF2" stroke="#3E8635" strokeWidth={1.5} />
        <text x={290} y={669} fontSize={9}>Scanning / Collection</text>
        <rect x={420} y={658} width={14} height={14} rx={2} fill="#FFF4E6" stroke="#F0AB00" strokeWidth={1.5} />
        <text x={440} y={669} fontSize={9}>Events / Alerts</text>
        <rect x={550} y={658} width={14} height={14} rx={2} fill="#F0F0F0" stroke="#8A8D90" strokeWidth={1.5} />
        <text x={570} y={669} fontSize={9}>Storage / Infrastructure</text>
        <line x1={700} y1={665} x2={740} y2={665} stroke="#6a6e73" strokeWidth={1.5} markerEnd="url(#ah)" />
        <text x={750} y={669} fontSize={9}>Data flow</text>
        <line x1={820} y1={665} x2={860} y2={665} stroke="#6a6e73" strokeWidth={1.5} strokeDasharray="4 3" markerEnd="url(#ah)" />
        <text x={870} y={669} fontSize={9}>On-demand</text>
      </svg>
    </div>
  );
}

const RELIABILITY_COLORS: Record<string, string> = { high: '#3e8635', medium: '#f0ab00', low: '#c9190b' };
const SOURCE_LABELS = ['labagator', 'babylon', 'pools', 'demolition', 'scanner', 'agnosticv', 'llm'];
const SOURCE_SHORT: Record<string, string> = {
  labagator: 'Lab', babylon: 'Bab', pools: 'Pool', demolition: 'Demo',
  scanner: 'Scan', agnosticv: 'AgV', llm: 'LLM',
};

function DataMappingView() {
  const { data, isLoading } = useDataMapping();

  if (isLoading) return <Spinner size="lg" />;
  if (!data) return <em>No data mapping available.</em>;

  const { summary, join_keys, labs } = data;

  return (
    <div>
      <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.5rem' }}>
        <div style={{ padding: '0.75rem 1.5rem', borderRadius: '6px', background: '#f3faf2', border: '1px solid #3e8635', textAlign: 'center' }}>
          <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#3e8635' }}>{summary.fully_connected}</div>
          <div style={{ fontSize: '0.8rem' }}>Fully Connected</div>
        </div>
        <div style={{ padding: '0.75rem 1.5rem', borderRadius: '6px', background: '#fff4e6', border: '1px solid #f0ab00', textAlign: 'center' }}>
          <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#8f4700' }}>{summary.partially_connected}</div>
          <div style={{ fontSize: '0.8rem' }}>Partial</div>
        </div>
        <div style={{ padding: '0.75rem 1.5rem', borderRadius: '6px', background: '#fceaea', border: '1px solid #c9190b', textAlign: 'center' }}>
          <div style={{ fontSize: '1.5rem', fontWeight: 700, color: '#c9190b' }}>{summary.disconnected}</div>
          <div style={{ fontSize: '0.8rem' }}>Disconnected</div>
        </div>
        <div style={{ padding: '0.75rem 1.5rem', borderRadius: '6px', background: '#f0f0f0', border: '1px solid #d2d2d2', textAlign: 'center' }}>
          <div style={{ fontSize: '1.5rem', fontWeight: 700 }}>{summary.total_labs}</div>
          <div style={{ fontSize: '0.8rem' }}>Total Labs</div>
        </div>
      </div>

      <h4 style={{ marginBottom: '0.5rem' }}>Join Keys Between Sources</h4>
      <Table aria-label="Join keys" variant="compact">
        <Thead><Tr><Th>From</Th><Th>To</Th><Th>Join Key</Th><Th>Reliability</Th></Tr></Thead>
        <Tbody>
          {join_keys.map((jk, i) => (
            <Tr key={i}>
              <Td><Label isCompact color="blue">{jk.from_source}</Label></Td>
              <Td><Label isCompact color="blue">{jk.to_source}</Label></Td>
              <Td style={{ fontSize: '0.8rem' }}>{jk.key}</Td>
              <Td><span style={{ padding: '2px 8px', borderRadius: '10px', fontSize: '0.75rem', fontWeight: 600, color: '#fff', backgroundColor: RELIABILITY_COLORS[jk.reliability] }}>{jk.reliability}</span></Td>
            </Tr>
          ))}
        </Tbody>
      </Table>

      <h4 style={{ marginTop: '1.5rem', marginBottom: '0.5rem' }}>Per-Lab Source Connectivity</h4>
      <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
        <Table aria-label="Lab data mapping" variant="compact">
          <Thead>
            <Tr>
              <Th>Lab</Th>
              {SOURCE_LABELS.map(s => <Th key={s} style={{ textAlign: 'center', fontSize: '0.75rem', padding: '4px' }}>{SOURCE_SHORT[s]}</Th>)}
              <Th>Health</Th>
              <Th>Issues</Th>
            </Tr>
          </Thead>
          <Tbody>
            {labs.map(lab => (
              <Tr key={lab.lab_code}>
                <Td style={{ fontSize: '0.8rem', fontWeight: 600, whiteSpace: 'nowrap' }}>{lab.lab_code}</Td>
                {SOURCE_LABELS.map(src => {
                  const s = lab.sources[src];
                  return (
                    <Td key={src} style={{ textAlign: 'center', padding: '4px', backgroundColor: s?.connected ? '#f3faf2' : '#fceaea' }} title={s?.key || ''}>
                      <span style={{ color: s?.connected ? '#3e8635' : '#c9190b', fontWeight: 600 }}>
                        {s?.connected ? '✓' : '✗'}
                      </span>
                    </Td>
                  );
                })}
                <Td style={{ fontSize: '0.8rem', whiteSpace: 'nowrap' }}>{lab.join_health}</Td>
                <Td style={{ fontSize: '0.75rem', color: '#c9190b', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {lab.issues.length > 0 ? lab.issues[0] : '—'}
                </Td>
              </Tr>
            ))}
          </Tbody>
        </Table>
      </div>
    </div>
  );
}

export default function ArchitectureModal({ renderTrigger }: { renderTrigger?: (onClick: () => void) => React.ReactNode } = {}) {
  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState(0);

  return (
    <>
      {renderTrigger ? renderTrigger(() => setIsOpen(true)) : (
        <Button variant="link" size="sm" onClick={() => setIsOpen(true)} style={{ padding: 0 }}>
          Architecture
        </Button>
      )}
      <Modal
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        variant="large"
        aria-label="StarGate Architecture"
      >
        <ModalHeader title="StarGate Platform — Data Architecture" />
        <ModalBody>
          <Tabs activeKey={activeTab} onSelect={(_e, key) => setActiveTab(key as number)}>
            <Tab eventKey={0} title={<TabTitleText>Flow Diagram</TabTitleText>}>
              <TabContent id="diagram-tab" style={{ paddingTop: '1rem' }}>
                <FlowDiagram />
              </TabContent>
            </Tab>
            <Tab eventKey={1} title={<TabTitleText>Data Sources Reference</TabTitleText>}>
              <TabContent id="reference-tab" style={{ paddingTop: '1rem' }}>
                <p style={{ marginBottom: '1rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>
                  StarGate aggregates data from 10 sources to provide a unified operational view.
                  All cluster scanning is read-only (oc get). No write operations are performed on production clusters.
                </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>

            <div style={{ padding: '0.75rem', border: '2px solid var(--sg-color--info)', borderRadius: '6px', background: 'var(--sg-color--info-bg)' }}>
              <div style={{ fontWeight: 700, fontSize: '1rem', marginBottom: '0.5rem' }}>
                StarGate Dashboard (this app)
              </div>
              <div style={{ fontSize: '0.85rem' }}>
                React + PatternFly 6 frontend → FastAPI backend → PostgreSQL persistence
              </div>
              <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.5rem' }}>
                <Label isCompact>Labs View</Label>
                <Label isCompact>Clusters View</Label>
                <Label isCompact>Pools View</Label>
                <Label isCompact>Errors View</Label>
                <Label isCompact>Pipeline View</Label>
                <Label isCompact>Admin Page</Label>
              </div>
            </div>

            <div style={{ textAlign: 'center', fontSize: '1.2rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>
              pulls from ▼
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '0.75rem' }}>
              {SOURCES.map(src => (
                <div key={src.name} style={{ border: '1px solid var(--rh-color--border, #d2d2d2)', borderRadius: '6px', padding: '0.75rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <Label color={src.color}>{src.name}</Label>
                    <span style={{ fontSize: '0.7rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>{src.refresh}</span>
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--rh-color--text-secondary, #6a6e73)', marginBottom: '0.5rem', wordBreak: 'break-all' }}>
                    {src.url}
                  </div>
                  <div style={{ fontSize: '0.8rem', marginBottom: '0.5rem' }}>
                    <strong>Provides:</strong>
                    <ul style={{ margin: '0.15rem 0', paddingLeft: '1rem' }}>
                      {src.provides.map((p, i) => <li key={i}>{p}</li>)}
                    </ul>
                  </div>
                  <div style={{ fontSize: '0.8rem' }}>
                    <strong>Feeds:</strong>{' '}
                    {src.feedsTo.map((f, i) => (
                      <Label key={i} isCompact style={{ marginRight: '3px', marginBottom: '2px' }}>{f}</Label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
              </TabContent>
            </Tab>
            <Tab eventKey={2} title={<TabTitleText>Data Mapping</TabTitleText>}>
              <TabContent id="mapping-tab" style={{ paddingTop: '1rem' }}>
                <DataMappingView />
              </TabContent>
            </Tab>
          </Tabs>
        </ModalBody>
        <ModalFooter>
          <Button variant="primary" onClick={() => setIsOpen(false)}>Close</Button>
        </ModalFooter>
      </Modal>
    </>
  );
}
