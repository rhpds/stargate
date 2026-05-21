import { useState } from 'react';
import {
  Alert,
  Button,
  Card,
  CardBody,
  CardTitle,
  CodeBlock,
  CodeBlockCode,
  Label,
  Spinner,
  Tab,
  TabContent,
  TabTitleText,
  Tabs,
} from '@patternfly/react-core';
import { useExecutiveSummary, useLLMFeedback } from '../api/hooks';

export default function ExecutiveSummary() {
  const summary = useExecutiveSummary();
  const feedback = useLLMFeedback();
  const [activeTab, setActiveTab] = useState(0);
  const [minimized, setMinimized] = useState(false);
  const [feedbackSubmitted, setFeedbackSubmitted] = useState<boolean | null>(null);

  if (!summary.isSuccess && !summary.isPending) {
    return (
      <Card>
        <CardBody>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <Button
              variant="primary"
              onClick={() => summary.mutate()}
              isLoading={summary.isPending}
            >
              Generate Executive Summary
            </Button>
            <span style={{ fontSize: '0.85rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>
              Sends all readiness data to Granite AI (Gaudi) for analysis
            </span>
          </div>
          {summary.isError && (
            <Alert variant="danger" title="Failed to generate summary" isInline style={{ marginTop: '1rem' }} />
          )}
        </CardBody>
      </Card>
    );
  }

  if (summary.isPending) {
    return (
      <Card>
        <CardBody>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <Spinner size="lg" />
            <div>
              <strong>Generating executive summary...</strong>
              <div style={{ fontSize: '0.85rem', color: 'var(--rh-color--text-secondary, #6a6e73)', marginTop: '0.25rem' }}>
                Collecting evidence from all clusters, labs, and pipelines — analyzing with Granite on Intel Gaudi
              </div>
            </div>
          </div>
        </CardBody>
      </Card>
    );
  }

  const data = summary.data!;

  return (
    <Card>
      <CardTitle>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ cursor: 'pointer' }} onClick={() => setMinimized(!minimized)}>
            Executive Summary {minimized ? '▼' : '▲'}
          </span>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
            <Label isCompact color="blue">{data.model}</Label>
            <Label isCompact>{new Date(data.timestamp).toLocaleTimeString()}</Label>
            <Button variant="link" size="sm" onClick={() => summary.mutate()} isLoading={summary.isPending}>
              Refresh
            </Button>
          </div>
        </div>
      </CardTitle>
      {!minimized && <CardBody>
        {data.lab_counts && (
          <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap', marginBottom: '1rem', fontSize: '0.9rem' }}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--sg-color--healthy)' }}>{data.lab_counts.ready}</div>
              <div>Ready</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--sg-color--warning)' }}>{data.lab_counts.at_risk}</div>
              <div>At Risk</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--sg-color--critical)' }}>{data.lab_counts.blocked}</div>
              <div>Blocked</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--rh-color--text-secondary, #6a6e73)' }}>{data.lab_counts.no_sessions}</div>
              <div>No Sessions</div>
            </div>
          </div>
        )}
        <Tabs activeKey={activeTab} onSelect={(_e, key) => setActiveTab(key as number)}>
          <Tab eventKey={0} title={<TabTitleText>AI Analysis</TabTitleText>}>
            <TabContent id="analysis-tab" style={{ paddingTop: '1rem' }}>
              <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6, fontSize: '0.9rem' }}>
                {data.analysis}
              </div>
            </TabContent>
          </Tab>
          <Tab eventKey={1} title={<TabTitleText>Evidence Bundle</TabTitleText>}>
            <TabContent id="evidence-tab" style={{ paddingTop: '1rem' }}>
              <CodeBlock>
                <CodeBlockCode>{data.evidence}</CodeBlockCode>
              </CodeBlock>
            </TabContent>
          </Tab>
        </Tabs>

        {/* Feedback */}
        <div style={{ marginTop: '1rem', borderTop: '1px solid var(--rh-color--border)', paddingTop: '0.75rem' }}>
          {feedbackSubmitted === null ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Was this summary helpful?</span>
              <Button variant="link" size="sm" onClick={() => { setFeedbackSubmitted(true); feedback.mutate({ endpoint: 'executive-summary', helpful: true }); }} style={{ color: 'var(--sg-color--healthy)' }}>
                Yes
              </Button>
              <Button variant="link" size="sm" onClick={() => { setFeedbackSubmitted(false); feedback.mutate({ endpoint: 'executive-summary', helpful: false }); }} style={{ color: 'var(--sg-color--critical)' }}>
                No
              </Button>
            </div>
          ) : (
            <Alert
              variant={feedbackSubmitted ? 'success' : 'info'}
              title={feedbackSubmitted ? 'Thanks — marked as helpful' : 'Thanks — marked as not helpful'}
              isInline
              isPlain
            />
          )}
        </div>
      </CardBody>}
    </Card>
  );
}
