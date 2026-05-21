import { useParams, useNavigate } from 'react-router-dom';
import {
  Breadcrumb,
  BreadcrumbItem,
  Card,
  CardBody,
  CardTitle,
  Content,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Gallery,
  GalleryItem,
  Label,
  PageSection,
  Spinner,
  Alert,
} from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import { useLabDetail } from '../api/hooks';
import StatusLabel from '../components/StatusLabel';

export default function LabDetail() {
  const { labCode } = useParams<{ labCode: string }>();
  const navigate = useNavigate();
  const { data, isLoading, isError } = useLabDetail(labCode ?? '');

  if (isLoading) return <PageSection><Spinner size="xl" /></PageSection>;
  if (isError) return <PageSection><Alert variant="danger" title={`Failed to load lab ${labCode}`} /></PageSection>;
  if (!data) return null;

  const failureEntries = Object.entries(data.stargate.failure_classes).sort(([, a], [, b]) => b - a);

  return (
    <>
      <PageSection>
        <Breadcrumb>
          <BreadcrumbItem onClick={() => navigate('/')} style={{ cursor: 'pointer' }}>Summit Overview</BreadcrumbItem>
          <BreadcrumbItem isActive>{labCode}</BreadcrumbItem>
        </Breadcrumb>
        <Content style={{ marginTop: '1rem' }}>
          <Content component="h1">{data.labagator?.title ?? labCode}</Content>
          {data.labagator && <StatusLabel status={data.labagator.status} />}
        </Content>
      </PageSection>

      {/* Metadata + Eval Summary */}
      <PageSection>
        <Gallery hasGutter minWidths={{ default: '400px' }}>
          {data.labagator && (
            <GalleryItem>
              <Card isFullHeight>
                <CardTitle>Lab Metadata</CardTitle>
                <CardBody>
                  <DescriptionList isHorizontal isCompact>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Cloud</DescriptionListTerm>
                      <DescriptionListDescription>{data.labagator.cloud}</DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Deploy Mode</DescriptionListTerm>
                      <DescriptionListDescription>{data.labagator.deploy_mode || '-'}</DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>CI Name</DescriptionListTerm>
                      <DescriptionListDescription>{data.labagator.ci_name || '-'}</DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Lead Developer</DescriptionListTerm>
                      <DescriptionListDescription>{data.labagator.lead_developer || '-'}</DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>RHDP Developer</DescriptionListTerm>
                      <DescriptionListDescription>{data.labagator.rhdp_developer || '-'}</DescriptionListDescription>
                    </DescriptionListGroup>
                    <DescriptionListGroup>
                      <DescriptionListTerm>Ops Assigned</DescriptionListTerm>
                      <DescriptionListDescription>{data.labagator.ops_assigned || '-'}</DescriptionListDescription>
                    </DescriptionListGroup>
                  </DescriptionList>
                </CardBody>
              </Card>
            </GalleryItem>
          )}
          <GalleryItem>
            <Card isFullHeight>
              <CardTitle>StarGate Evaluations</CardTitle>
              <CardBody>
                <DescriptionList isHorizontal isCompact>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Total</DescriptionListTerm>
                    <DescriptionListDescription><strong>{data.stargate.evaluation_count}</strong></DescriptionListDescription>
                  </DescriptionListGroup>
                  <DescriptionListGroup>
                    <DescriptionListTerm>Last Passing</DescriptionListTerm>
                    <DescriptionListDescription>
                      {data.stargate.last_passing_run
                        ? String(data.stargate.last_passing_run.evaluated_at ?? data.stargate.last_passing_run.run_id ?? '-')
                        : 'None'}
                    </DescriptionListDescription>
                  </DescriptionListGroup>
                </DescriptionList>
                {failureEntries.length > 0 && (
                  <div style={{ marginTop: '1rem' }}>
                    <strong>Failure Classes</strong>
                    {failureEntries.map(([cls, count]) => (
                      <div key={cls} style={{ display: 'flex', justifyContent: 'space-between', padding: '0.2rem 0' }}>
                        <span>{cls}</span>
                        <strong>{count}</strong>
                      </div>
                    ))}
                  </div>
                )}
              </CardBody>
            </Card>
          </GalleryItem>
        </Gallery>
      </PageSection>

      {/* Session Schedule */}
      {data.labagator_sessions.length > 0 && (
        <PageSection variant="secondary">
          <Content><Content component="h2">Session Schedule</Content></Content>
          <Table aria-label="Sessions" variant="compact">
            <Thead><Tr><Th>Date</Th><Th>Start</Th><Th>End</Th><Th>Room</Th><Th>Attendees</Th><Th>Status</Th></Tr></Thead>
            <Tbody>
              {data.labagator_sessions.map((s, i) => (
                <Tr key={i}>
                  <Td>{s.session_date}</Td>
                  <Td>{s.start_time}</Td>
                  <Td>{s.end_time}</Td>
                  <Td>{s.room}</Td>
                  <Td>{s.attendees}</Td>
                  <Td><StatusLabel status={s.status} isCompact /></Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </PageSection>
      )}

      {/* Evaluation History */}
      {data.stargate.history.length > 0 && (
        <PageSection>
          <Content><Content component="h2">Evaluation History</Content></Content>
          <Table aria-label="Evaluation history" variant="compact">
            <Thead><Tr><Th>Time</Th><Th>Stage</Th><Th>Outcome</Th><Th>Failure Class</Th><Th>Cluster</Th></Tr></Thead>
            <Tbody>
              {data.stargate.history.map((e, i) => (
                <Tr key={i}>
                  <Td>{e.evaluated_at ? new Date(e.evaluated_at).toLocaleString() : '-'}</Td>
                  <Td>{e.stage_id}</Td>
                  <Td><StatusLabel status={e.outcome} isCompact /></Td>
                  <Td>{e.failure_class || '-'}</Td>
                  <Td>{e.cluster_name || '-'}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </PageSection>
      )}

      {/* Demolition Results */}
      {data.demolition.length > 0 && (
        <PageSection variant="secondary">
          <Content><Content component="h2">Demolition Test Results</Content></Content>
          <Table aria-label="Demolition results" variant="compact">
            <Thead><Tr><Th>Name</Th><Th>Status</Th><Th>Workers</Th><Th>Completed</Th><Th>Failed</Th><Th>Total</Th></Tr></Thead>
            <Tbody>
              {data.demolition.map(d => (
                <Tr key={d.id}>
                  <Td>{d.name}</Td>
                  <Td><StatusLabel status={d.status} isCompact /></Td>
                  <Td>{d.workers}</Td>
                  <Td>{d.completed}</Td>
                  <Td style={{ color: d.failed > 0 ? 'var(--sg-color--critical)' : undefined }}>{d.failed}</Td>
                  <Td>{d.total}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </PageSection>
      )}

      {/* Constraints */}
      {data.constraints && (
        <PageSection>
          <Content><Content component="h2">AgnosticV Constraints</Content></Content>
          <DescriptionList isHorizontal isCompact>
            {data.constraints.display_name != null && (
              <DescriptionListGroup>
                <DescriptionListTerm>Display Name</DescriptionListTerm>
                <DescriptionListDescription>{String(data.constraints.display_name)}</DescriptionListDescription>
              </DescriptionListGroup>
            )}
            {data.constraints.cloud_provider != null && (
              <DescriptionListGroup>
                <DescriptionListTerm>Cloud Provider</DescriptionListTerm>
                <DescriptionListDescription>{String(data.constraints.cloud_provider)}</DescriptionListDescription>
              </DescriptionListGroup>
            )}
            {data.constraints.ocp_version != null && (
              <DescriptionListGroup>
                <DescriptionListTerm>OCP Version</DescriptionListTerm>
                <DescriptionListDescription>{String(data.constraints.ocp_version)}</DescriptionListDescription>
              </DescriptionListGroup>
            )}
            {Array.isArray(data.constraints.workloads) && (
              <DescriptionListGroup>
                <DescriptionListTerm>Workloads</DescriptionListTerm>
                <DescriptionListDescription>
                  {(data.constraints.workloads as string[]).map(w => (
                    <Label key={w} isCompact style={{ marginRight: '4px', marginBottom: '2px' }}>{w}</Label>
                  ))}
                </DescriptionListDescription>
              </DescriptionListGroup>
            )}
            {data.constraints.operator_channels != null && typeof data.constraints.operator_channels === 'object' && (
              <DescriptionListGroup>
                <DescriptionListTerm>Operators</DescriptionListTerm>
                <DescriptionListDescription>
                  {Object.entries(data.constraints.operator_channels as Record<string, string>).map(([op, ch]) => (
                    <Label key={op} isCompact style={{ marginRight: '4px', marginBottom: '2px' }}>{op}: {ch}</Label>
                  ))}
                </DescriptionListDescription>
              </DescriptionListGroup>
            )}
            {Array.isArray(data.constraints.components) && (
              <DescriptionListGroup>
                <DescriptionListTerm>Components</DescriptionListTerm>
                <DescriptionListDescription>
                  {(data.constraints.components as string[]).map(c => (
                    <Label key={c} isCompact color="blue" style={{ marginRight: '4px', marginBottom: '2px' }}>{c}</Label>
                  ))}
                </DescriptionListDescription>
              </DescriptionListGroup>
            )}
          </DescriptionList>
        </PageSection>
      )}

      {/* Recent Events */}
      {data.recent_events.length > 0 && (
        <PageSection variant="secondary">
          <Content><Content component="h2">Recent Events</Content></Content>
          <Table aria-label="Recent events" variant="compact">
            <Thead><Tr><Th>Time</Th><Th>Type</Th><Th>Outcome</Th><Th>Failure Class</Th><Th>Priority</Th></Tr></Thead>
            <Tbody>
              {data.recent_events.map(evt => (
                <Tr key={evt.event_id}>
                  <Td>{new Date(evt.timestamp).toLocaleString()}</Td>
                  <Td>{evt.event_type}</Td>
                  <Td>{evt.outcome ? <StatusLabel status={evt.outcome} isCompact /> : '-'}</Td>
                  <Td>{evt.failure_class || '-'}</Td>
                  <Td>{evt.priority > 0 ? evt.priority.toFixed(1) : '-'}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </PageSection>
      )}
    </>
  );
}
