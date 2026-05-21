import { useParams, useNavigate } from 'react-router-dom';
import {
  Breadcrumb,
  BreadcrumbItem,
  Card,
  CardBody,
  CardTitle,
  Content,
  Gallery,
  GalleryItem,
  PageSection,
  Spinner,
  Alert,
} from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import { useClusterSummary, useClusterFailures, useEvents } from '../api/hooks';
import StatusLabel from '../components/StatusLabel';

export default function ClusterDetail() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const { data: summary, isLoading, isError } = useClusterSummary(name ?? '');
  const { data: failures } = useClusterFailures(name ?? '');
  const { data: events } = useEvents(name ? { cluster: name, limit: '20' } : undefined);

  if (isLoading) return <PageSection><Spinner size="xl" /></PageSection>;
  if (isError) return <PageSection><Alert variant="danger" title={`Failed to load cluster ${name}`} /></PageSection>;
  if (!summary) return null;

  const failureEntries = failures ? Object.entries(failures).sort(([, a], [, b]) => b - a) : [];

  return (
    <>
      <PageSection>
        <Breadcrumb>
          <BreadcrumbItem onClick={() => navigate('/clusters')} style={{ cursor: 'pointer' }}>Clusters</BreadcrumbItem>
          <BreadcrumbItem isActive>{name}</BreadcrumbItem>
        </Breadcrumb>
        <Content style={{ marginTop: '1rem' }}>
          <Content component="h1">{name}</Content>
        </Content>
      </PageSection>

      <PageSection>
        <Gallery hasGutter minWidths={{ default: '180px' }}>
          <GalleryItem>
            <Card isFullHeight>
              <CardTitle>Health Rate</CardTitle>
              <CardBody>
                <span style={{ fontSize: '2rem', fontWeight: 700, color: summary.health_rate >= 80 ? 'var(--sg-color--healthy)' : summary.health_rate >= 50 ? 'var(--sg-color--warning)' : 'var(--sg-color--critical)' }}>
                  {summary.health_rate.toFixed(1)}%
                </span>
              </CardBody>
            </Card>
          </GalleryItem>
          <GalleryItem>
            <Card isFullHeight>
              <CardTitle>Evaluations</CardTitle>
              <CardBody><span style={{ fontSize: '2rem', fontWeight: 700 }}>{summary.total_evaluations}</span></CardBody>
            </Card>
          </GalleryItem>
          <GalleryItem>
            <Card isFullHeight>
              <CardTitle>Passed</CardTitle>
              <CardBody><span style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--sg-color--healthy)' }}>{summary.passed}</span></CardBody>
            </Card>
          </GalleryItem>
          <GalleryItem>
            <Card isFullHeight>
              <CardTitle>Failed</CardTitle>
              <CardBody><span style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--sg-color--critical)' }}>{summary.failed}</span></CardBody>
            </Card>
          </GalleryItem>
          <GalleryItem>
            <Card isFullHeight>
              <CardTitle>Labs</CardTitle>
              <CardBody><span style={{ fontSize: '2rem', fontWeight: 700 }}>{summary.labs_seen}</span></CardBody>
            </Card>
          </GalleryItem>
          <GalleryItem>
            <Card isFullHeight>
              <CardTitle>Failing Labs</CardTitle>
              <CardBody><span style={{ fontSize: '2rem', fontWeight: 700, color: summary.labs_failing > 0 ? 'var(--sg-color--critical)' : 'var(--sg-color--healthy)' }}>{summary.labs_failing}</span></CardBody>
            </Card>
          </GalleryItem>
        </Gallery>
      </PageSection>

      {failureEntries.length > 0 && (
        <PageSection variant="secondary">
          <Content><Content component="h2">Failure Distribution</Content></Content>
          <Table aria-label="Failure classes" variant="compact">
            <Thead><Tr><Th>Failure Class</Th><Th>Count</Th></Tr></Thead>
            <Tbody>
              {failureEntries.map(([cls, count]) => (
                <Tr key={cls}><Td>{cls}</Td><Td>{count}</Td></Tr>
              ))}
            </Tbody>
          </Table>
        </PageSection>
      )}

      {events && events.length > 0 && (
        <PageSection>
          <Content><Content component="h2">Recent Events</Content></Content>
          <Table aria-label="Cluster events" variant="compact">
            <Thead><Tr><Th>Time</Th><Th>Type</Th><Th>Lab</Th><Th>Outcome</Th><Th>Failure Class</Th></Tr></Thead>
            <Tbody>
              {events.slice(0, 20).map(evt => (
                <Tr key={evt.event_id}>
                  <Td>{new Date(evt.timestamp).toLocaleString()}</Td>
                  <Td><StatusLabel status={evt.event_type.split('.')[1] ?? evt.event_type} isCompact /></Td>
                  <Td>{evt.lab_code || '-'}</Td>
                  <Td>{evt.outcome || '-'}</Td>
                  <Td>{evt.failure_class || '-'}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </PageSection>
      )}
    </>
  );
}
