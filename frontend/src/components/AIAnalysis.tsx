import { useState } from 'react';
import {
  Alert,
  Button,
  CodeBlock,
  CodeBlockCode,
  Label,
  Spinner,
  TextArea,
} from '@patternfly/react-core';
import { useRemediation, useLLMFeedback } from '../api/hooks';

interface Props {
  contextType: 'lab' | 'cluster' | 'pool' | 'error';
  labCode?: string;
  clusterName?: string;
  poolName?: string;
  failureClass?: string;
}

export default function AIAnalysis({ contextType, labCode, clusterName, poolName, failureClass }: Props) {
  const remediation = useRemediation();
  const feedback = useLLMFeedback();
  const [requested, setRequested] = useState(false);
  const [feedbackNotes, setFeedbackNotes] = useState('');
  const [feedbackSubmitted, setFeedbackSubmitted] = useState<boolean | null>(null);

  const handleAnalyze = () => {
    setRequested(true);
    setFeedbackSubmitted(null);
    remediation.mutate({
      context_type: contextType,
      failure_class: failureClass ?? '',
      lab_code: labCode,
      cluster: clusterName,
      pool_name: poolName,
    });
  };

  const handleFeedback = (helpful: boolean) => {
    setFeedbackSubmitted(helpful);
    feedback.mutate({
      llm_metric_id: remediation.data?.llm_metric_id,
      endpoint: 'remediation',
      helpful,
      notes: feedbackNotes || undefined,
    });
  };

  return (
    <div style={{ marginTop: '1.5rem', borderTop: '1px solid var(--rh-color--border)', paddingTop: '1rem' }}>
      {!requested && (
        <Button variant="primary" onClick={handleAnalyze}>
          Analyze with AI (Granite on Xeon 6)
        </Button>
      )}

      {remediation.isPending && (
        <div style={{ marginTop: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Spinner size="md" />
          <span style={{ fontSize: '0.9rem', color: 'var(--rh-color--text-secondary)' }}>Analyzing on Intel Xeon 6 / Gaudi...</span>
        </div>
      )}

      {remediation.isError && (
        <Alert variant="danger" title="Analysis failed" style={{ marginTop: '0.5rem' }}>
          {(remediation.error as Error).message}
        </Alert>
      )}

      {remediation.data && (
        <div style={{ marginTop: '0.75rem' }}>
          {remediation.data.evidence_summary && (
            <div style={{ fontSize: '0.85rem', color: 'var(--rh-color--text-secondary)', marginBottom: '0.75rem', whiteSpace: 'pre-wrap' }}>
              {remediation.data.evidence_summary}
            </div>
          )}

          {remediation.data.runbook_steps.length > 0 && (
            <>
              <h4 style={{ marginBottom: '0.25rem', fontSize: '0.9rem' }}>Diagnostic Commands</h4>
              <CodeBlock>
                <CodeBlockCode>{remediation.data.runbook_steps.join('\n')}</CodeBlockCode>
              </CodeBlock>
            </>
          )}

          {remediation.data.llm_analysis && (
            <>
              <h4 style={{ marginTop: '0.75rem', marginBottom: '0.25rem', fontSize: '0.9rem' }}>
                AI Analysis
                <Label isCompact color="blue" style={{ marginLeft: '0.5rem' }}>{remediation.data.llm_model}</Label>
              </h4>
              <div style={{
                background: 'var(--rh-color--surface-tertiary)',
                border: '1px solid var(--rh-color--border)',
                borderRadius: '4px',
                padding: '0.75rem',
                fontSize: '0.9rem',
                whiteSpace: 'pre-wrap',
                lineHeight: 1.6,
              }}>
                {remediation.data.llm_analysis}
              </div>
            </>
          )}

          {/* Confidence + Metrics */}
          <div style={{ marginTop: '0.75rem', display: 'flex', gap: '1.5rem', alignItems: 'center', fontSize: '0.85rem', flexWrap: 'wrap' }}>
            <span>
              Confidence:
              <Label
                isCompact
                color={remediation.data.confidence === 'high' ? 'green' : remediation.data.confidence === 'medium' ? 'yellow' : 'orange'}
                style={{ marginLeft: '0.25rem' }}
              >
                {remediation.data.confidence}
                {remediation.data.confidence_score != null && ` (${(remediation.data.confidence_score * 100).toFixed(0)}%)`}
              </Label>
            </span>
            {remediation.data.llm_latency_ms != null && (
              <span style={{ color: 'var(--rh-color--text-secondary)' }}>
                {(remediation.data.llm_latency_ms / 1000).toFixed(1)}s latency
              </span>
            )}
            {remediation.data.llm_tokens != null && (
              <span style={{ color: 'var(--rh-color--text-secondary)' }}>
                {remediation.data.llm_tokens} tokens
              </span>
            )}
          </div>

          {/* Feedback */}
          <div style={{ marginTop: '1rem', borderTop: '1px solid var(--rh-color--border)', paddingTop: '0.75rem' }}>
            {feedbackSubmitted === null ? (
              <>
                <span style={{ fontSize: '0.85rem', fontWeight: 600, marginRight: '0.75rem' }}>Was this analysis helpful?</span>
                <Button variant="link" size="sm" onClick={() => handleFeedback(true)} style={{ marginRight: '0.5rem', color: 'var(--sg-color--healthy)' }}>
                  Yes, helpful
                </Button>
                <Button variant="link" size="sm" onClick={() => handleFeedback(false)} style={{ color: 'var(--sg-color--critical)' }}>
                  Not helpful
                </Button>
                <div style={{ marginTop: '0.5rem' }}>
                  <TextArea
                    value={feedbackNotes}
                    onChange={(_e, v) => setFeedbackNotes(v)}
                    rows={1}
                    placeholder="Optional: what was wrong or could be better?"
                    style={{ fontSize: '0.85rem' }}
                  />
                </div>
              </>
            ) : (
              <Alert
                variant={feedbackSubmitted ? 'success' : 'info'}
                title={feedbackSubmitted ? 'Thanks — marked as helpful' : 'Thanks — marked as not helpful'}
                isInline
                isPlain
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
