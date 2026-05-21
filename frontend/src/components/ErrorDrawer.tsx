import {
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Label,
} from '@patternfly/react-core';
import type { ErrorRow } from './ErrorsView';
import { useEvents } from '../api/hooks';
import AIAnalysis from './AIAnalysis';
import FeedbackForm from './FeedbackForm';

interface Props {
  error: ErrorRow;
}

export default function ErrorDrawer({ error }: Props) {
  const { data: events } = useEvents({ limit: '10' });
  const latestEvent = events?.find(e => e.failure_class === error.failure_class);

  return (
    <div style={{ padding: '0.5rem' }}>
      <h4 style={{ marginBottom: '0.5rem' }}>
        Failure: {error.failure_class}
        {error.has_escalation && <Label isCompact color="red" style={{ marginLeft: '0.5rem' }}>ESCALATED</Label>}
      </h4>
      <DescriptionList isHorizontal isCompact>
        <DescriptionListGroup>
          <DescriptionListTerm>Occurrences</DescriptionListTerm>
          <DescriptionListDescription><strong style={{ color: 'var(--sg-color--critical)' }}>{error.count}</strong></DescriptionListDescription>
        </DescriptionListGroup>
        <DescriptionListGroup>
          <DescriptionListTerm>% of Total</DescriptionListTerm>
          <DescriptionListDescription>{error.pct.toFixed(1)}%</DescriptionListDescription>
        </DescriptionListGroup>
        {error.clusters.length > 0 && (
          <DescriptionListGroup>
            <DescriptionListTerm>Clusters</DescriptionListTerm>
            <DescriptionListDescription>
              {error.clusters.map(c => <Label key={c} isCompact color="blue" style={{ marginRight: '4px' }}>{c}</Label>)}
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}
        {error.stages.length > 0 && (
          <DescriptionListGroup>
            <DescriptionListTerm>Stages</DescriptionListTerm>
            <DescriptionListDescription>
              {error.stages.map(s => <Label key={s} isCompact style={{ marginRight: '4px' }}>{s}</Label>)}
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}
        {error.latest_time && (
          <DescriptionListGroup>
            <DescriptionListTerm>Latest</DescriptionListTerm>
            <DescriptionListDescription>{new Date(error.latest_time).toLocaleString()}</DescriptionListDescription>
          </DescriptionListGroup>
        )}
      </DescriptionList>

      {error.max_blast_radius && (
        <>
          <h4 style={{ marginTop: '1rem', marginBottom: '0.5rem' }}>Blast Radius</h4>
          <DescriptionList isHorizontal isCompact>
            <DescriptionListGroup>
              <DescriptionListTerm>Failing Labs</DescriptionListTerm>
              <DescriptionListDescription>
                <strong style={{ color: 'var(--sg-color--critical)' }}>{error.max_blast_radius.failing_labs}</strong>
                {' / '}{error.max_blast_radius.total_labs}
              </DescriptionListDescription>
            </DescriptionListGroup>
            <DescriptionListGroup>
              <DescriptionListTerm>Failure Rate</DescriptionListTerm>
              <DescriptionListDescription>
                <strong style={{ color: error.max_blast_radius.failure_rate > 30 ? 'var(--sg-color--critical)' : undefined }}>
                  {error.max_blast_radius.failure_rate.toFixed(1)}%
                </strong>
              </DescriptionListDescription>
            </DescriptionListGroup>
          </DescriptionList>
        </>
      )}

      <AIAnalysis contextType="error" failureClass={error.failure_class} />

      {latestEvent?.run_id && (
        <FeedbackForm runId={latestEvent.run_id} currentClass={error.failure_class} />
      )}
    </div>
  );
}
