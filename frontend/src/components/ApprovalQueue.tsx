import { Alert, Button, Card, CardBody, CardTitle, Label, Spinner } from '@patternfly/react-core';
import { Table, Thead, Tr, Th, Tbody, Td } from '@patternfly/react-table';
import { useApprovalQueue, useApproveAction, useRejectAction } from '../api/hooks';
import { useQueryClient } from '@tanstack/react-query';

export default function ApprovalQueue() {
  const { data, isLoading } = useApprovalQueue();
  const approve = useApproveAction();
  const reject = useRejectAction();
  const queryClient = useQueryClient();

  const handleApprove = (id: number) => {
    approve.mutate(id, {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: ['approval-queue'] }),
    });
  };

  const handleReject = (id: number) => {
    reject.mutate(id, {
      onSuccess: () => queryClient.invalidateQueries({ queryKey: ['approval-queue'] }),
    });
  };

  if (isLoading) return <Spinner size="lg" />;

  const pending = data?.pending ?? [];

  return (
    <Card>
      <CardTitle>
        Approval Queue
        {pending.length > 0 && (
          <Label isCompact color="orange" style={{ marginLeft: '0.5rem' }}>
            {pending.length} pending
          </Label>
        )}
      </CardTitle>
      <CardBody>
        {pending.length === 0 ? (
          <em style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>
            No actions pending approval. Actions with confidence below threshold are queued here.
          </em>
        ) : (
          <>
            {approve.isError && <Alert variant="danger" title="Approve failed" isInline style={{ marginBottom: '0.5rem' }} />}
            {reject.isError && <Alert variant="danger" title="Reject failed" isInline style={{ marginBottom: '0.5rem' }} />}

            <Table aria-label="Approval queue" variant="compact">
              <Thead>
                <Tr>
                  <Th>ID</Th>
                  <Th>Action</Th>
                  <Th>Target</Th>
                  <Th>Confidence</Th>
                  <Th>Proposed</Th>
                  <Th>Actions</Th>
                </Tr>
              </Thead>
              <Tbody>
                {pending.map(p => (
                  <Tr key={p.id}>
                    <Td>#{p.id}</Td>
                    <Td><strong>{p.action_type}</strong></Td>
                    <Td>{p.target}</Td>
                    <Td>
                      <Label
                        isCompact
                        color={p.confidence >= 0.7 ? 'yellow' : p.confidence >= 0.5 ? 'orange' : 'red'}
                      >
                        {(p.confidence * 100).toFixed(0)}%
                      </Label>
                    </Td>
                    <Td style={{ fontSize: '0.85rem' }}>
                      {p.proposed_at ? new Date(p.proposed_at).toLocaleString() : '—'}
                    </Td>
                    <Td>
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={() => handleApprove(p.id)}
                        isLoading={approve.isPending}
                        style={{ marginRight: '0.5rem' }}
                      >
                        Approve
                      </Button>
                      <Button
                        variant="danger"
                        size="sm"
                        onClick={() => handleReject(p.id)}
                        isLoading={reject.isPending}
                      >
                        Reject
                      </Button>
                    </Td>
                  </Tr>
                ))}
              </Tbody>
            </Table>
          </>
        )}
      </CardBody>
    </Card>
  );
}
