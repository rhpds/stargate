import { Card, CardBody, CardTitle, Label, Spinner } from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import { useSecurity } from '../api/hooks';

export default function SecurityView() {
  const { data, isLoading } = useSecurity();

  if (isLoading) return <Spinner size="lg" />;
  if (!data) return <em>No security data available.</em>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      <Card>
        <CardTitle>Known CVEs</CardTitle>
        <CardBody>
          <Table aria-label="CVEs" variant="compact">
            <Thead><Tr><Th>CVE</Th><Th>Name</Th><Th>Severity</Th><Th>CVSS</Th><Th>Affected</Th><Th>Status</Th><Th>Mitigation</Th><Th>Applied</Th></Tr></Thead>
            <Tbody>
              {data.known_cves.map(c => (
                <Tr key={c.cve_id}>
                  <Td><strong>{c.cve_id}</strong></Td>
                  <Td>{c.name}</Td>
                  <Td><Label isCompact color={c.severity === 'HIGH' ? 'red' : c.severity === 'CRITICAL' ? 'red' : 'orange'}>{c.severity}</Label></Td>
                  <Td>{c.cvss}</Td>
                  <Td style={{ fontSize: '0.85rem' }}>{c.affected}</Td>
                  <Td style={{ fontSize: '0.85rem' }}>{c.status}</Td>
                  <Td style={{ fontSize: '0.85rem' }}>{c.mitigation}</Td>
                  <Td>{c.applied ? <Label isCompact color="green">Yes</Label> : <Label isCompact color="red">No</Label>}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </CardBody>
      </Card>

      <Card>
        <CardTitle>OCP Version Status</CardTitle>
        <CardBody>
          <Table aria-label="Versions" variant="compact">
            <Thead><Tr><Th>Cluster Group</Th><Th>Version Status</Th></Tr></Thead>
            <Tbody>
              {Object.entries(data.ocp_versions_behind).map(([k, v]) => (
                <Tr key={k}><Td><strong>{k}</strong></Td><Td>{v}</Td></Tr>
              ))}
            </Tbody>
          </Table>
        </CardBody>
      </Card>

      <Card>
        <CardTitle>Security Recommendations</CardTitle>
        <CardBody>
          <Table aria-label="Recommendations" variant="compact">
            <Thead><Tr><Th>Priority</Th><Th>Action</Th><Th>Est. Time</Th></Tr></Thead>
            <Tbody>
              {data.recommendations.map((r, i) => (
                <Tr key={i}>
                  <Td><Label isCompact color={r.priority === 'IMMEDIATE' ? 'red' : 'blue'}>{r.priority}</Label></Td>
                  <Td>{r.action}</Td>
                  <Td>{r.time}</Td>
                </Tr>
              ))}
            </Tbody>
          </Table>
        </CardBody>
      </Card>

      <Card>
        <CardTitle>Cluster Security Status</CardTitle>
        <CardBody>
          {data.clusters.length > 0 ? (
            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              {data.clusters.map(c => (
                <Label key={c.cluster} isCompact color={c.status === 'healthy' ? 'green' : c.status === 'warning' ? 'orange' : 'red'}>
                  {c.cluster}: {c.status}
                </Label>
              ))}
            </div>
          ) : <em>No cluster data.</em>}
        </CardBody>
      </Card>
    </div>
  );
}
