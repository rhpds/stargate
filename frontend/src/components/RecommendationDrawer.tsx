import { useState } from 'react';
import {
  Alert,
  Button,
  CodeBlock,
  CodeBlockCode,
  DescriptionList,
  DescriptionListDescription,
  DescriptionListGroup,
  DescriptionListTerm,
  Label,
  TextArea,
} from '@patternfly/react-core';
import type { Recommendation } from '../api/types';
import { useLLMFeedback } from '../api/hooks';
import AIAnalysis from './AIAnalysis';

const TYPE_LABELS: Record<string, string> = {
  provision_blocked_lab: 'Blocked Lab — No Provisioning',
  cleanup_stuck: 'Stuck Instances — Resource Waste',
  pool_exhaustion: 'Pool Exhaustion Risk',
  cluster_capacity: 'Cluster Capacity Warning',
  smoke_test_failing: 'Smoke Test Failures',
};

const URGENCY_COLORS: Record<string, 'red' | 'orange' | 'yellow' | 'grey'> = {
  critical: 'red',
  high: 'orange',
  medium: 'yellow',
  low: 'grey',
};

const TYPE_EXPLANATIONS: Record<string, string> = {
  provision_blocked_lab: 'This lab has scheduled sessions but no pool allocation or provisioned instances. Attendees will arrive to an unprovisioned lab unless action is taken.',
  cleanup_stuck: 'Failed instances are consuming cluster resources (CPU, memory, storage) without serving any attendees. Cleaning them up frees capacity for working labs.',
  pool_exhaustion: 'This resource pool is running critically low. When exhausted, new lab provisioning requests will queue indefinitely until capacity is restored.',
  cluster_capacity: 'This cluster is approaching resource limits. High CPU or VM density increases the risk of performance degradation and scheduling failures.',
  smoke_test_failing: 'Demolition smoke tests are failing for this lab, indicating the lab experience may be broken for attendees. Investigate showroom, services, or VM issues.',
};

interface Props {
  recommendation: Recommendation;
}

export default function RecommendationDrawer({ recommendation: r }: Props) {
  const feedback = useLLMFeedback();
  const [feedbackSubmitted, setFeedbackSubmitted] = useState<boolean | null>(null);
  const [feedbackNotes, setFeedbackNotes] = useState('');

  return (
    <div style={{ padding: '0.5rem' }}>
      <h4 style={{ marginBottom: '0.5rem' }}>
        {TYPE_LABELS[r.type] || r.type}
        <Label isCompact color={URGENCY_COLORS[r.urgency]} style={{ marginLeft: '0.5rem' }}>{r.urgency}</Label>
      </h4>

      <p style={{ fontSize: '0.9rem', color: 'var(--rh-color--text-secondary, #6a6e73)', marginBottom: '1rem' }}>
        {TYPE_EXPLANATIONS[r.type] || ''}
      </p>

      <DescriptionList isHorizontal isCompact>
        <DescriptionListGroup>
          <DescriptionListTerm>Recommendation</DescriptionListTerm>
          <DescriptionListDescription><strong>{r.recommendation}</strong></DescriptionListDescription>
        </DescriptionListGroup>

        {r.action && (
          <DescriptionListGroup>
            <DescriptionListTerm>Suggested Action</DescriptionListTerm>
            <DescriptionListDescription style={{ color: 'var(--sg-color--info, #06c)' }}>{r.action}</DescriptionListDescription>
          </DescriptionListGroup>
        )}

        {r.lab_code && (
          <DescriptionListGroup>
            <DescriptionListTerm>Lab</DescriptionListTerm>
            <DescriptionListDescription>
              <strong>{r.lab_code}</strong>
              {r.title && <span style={{ marginLeft: '0.5rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>— {r.title}</span>}
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}

        {r.cluster && (
          <DescriptionListGroup>
            <DescriptionListTerm>Cluster</DescriptionListTerm>
            <DescriptionListDescription><strong>{r.cluster}</strong></DescriptionListDescription>
          </DescriptionListGroup>
        )}

        {r.pool_name && (
          <DescriptionListGroup>
            <DescriptionListTerm>Pool</DescriptionListTerm>
            <DescriptionListDescription><strong>{r.pool_name}</strong></DescriptionListDescription>
          </DescriptionListGroup>
        )}

        {r.sessions != null && r.sessions > 0 && (
          <DescriptionListGroup>
            <DescriptionListTerm>Sessions</DescriptionListTerm>
            <DescriptionListDescription>
              <strong style={{ color: 'var(--sg-color--critical)' }}>{r.sessions}</strong> scheduled
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}

        {r.summit_days && r.summit_days.length > 0 && (
          <DescriptionListGroup>
            <DescriptionListTerm>Event Days</DescriptionListTerm>
            <DescriptionListDescription>
              {r.summit_days.map(d => <Label key={d} isCompact color="blue" style={{ marginRight: 4 }}>{d}</Label>)}
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}

        {r.attendees != null && r.attendees > 0 && (
          <DescriptionListGroup>
            <DescriptionListTerm>Attendees</DescriptionListTerm>
            <DescriptionListDescription><strong>{r.attendees}</strong></DescriptionListDescription>
          </DescriptionListGroup>
        )}

        {r.stuck_count != null && (
          <DescriptionListGroup>
            <DescriptionListTerm>Stuck Instances</DescriptionListTerm>
            <DescriptionListDescription>
              <strong style={{ color: 'var(--sg-color--critical)' }}>{r.stuck_count}</strong>
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}

        {r.cpu != null && (
          <DescriptionListGroup>
            <DescriptionListTerm>CPU Usage</DescriptionListTerm>
            <DescriptionListDescription>
              <strong style={{ color: r.cpu > 80 ? 'var(--sg-color--critical)' : r.cpu > 70 ? 'var(--sg-color--warning)' : undefined }}>
                {r.cpu.toFixed(1)}%
              </strong>
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}

        {r.vms_per_node != null && (
          <DescriptionListGroup>
            <DescriptionListTerm>VMs/Node</DescriptionListTerm>
            <DescriptionListDescription>
              <strong style={{ color: r.vms_per_node > 80 ? 'var(--sg-color--critical)' : undefined }}>
                {r.vms_per_node.toFixed(1)}
              </strong>
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}

        {r.available != null && r.min_required != null && (
          <DescriptionListGroup>
            <DescriptionListTerm>Pool Capacity</DescriptionListTerm>
            <DescriptionListDescription>
              <strong style={{ color: 'var(--sg-color--critical)' }}>{r.available}</strong> available of <strong>{r.min_required}</strong> required
            </DescriptionListDescription>
          </DescriptionListGroup>
        )}
      </DescriptionList>

      {/* Evidence — what data drove this recommendation, organized by source */}
      {r.evidence && Object.keys(r.evidence).length > 0 && (
        <div style={{ marginTop: '1rem' }}>
          <h4 style={{ marginBottom: '0.5rem' }}>Evidence by Source</h4>
          {Object.entries(r.evidence).map(([source, data]) => {
            const label = source.replace('source_', '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            const entries = Object.entries(data as Record<string, unknown>).filter(([, v]) => v != null && v !== '' && !(Array.isArray(v) && v.length === 0));
            if (entries.length === 0) return null;
            return (
              <div key={source} style={{ marginBottom: '0.75rem' }}>
                <Label isCompact color="blue" style={{ marginBottom: '0.25rem' }}>{label}</Label>
                <DescriptionList isHorizontal isCompact style={{ marginTop: '0.25rem' }}>
                  {entries.map(([key, val]) => (
                    <DescriptionListGroup key={key}>
                      <DescriptionListTerm style={{ fontSize: '0.8rem' }}>{key.replace(/_/g, ' ')}</DescriptionListTerm>
                      <DescriptionListDescription style={{ fontSize: '0.8rem' }}>
                        {typeof val === 'object' ? (
                          <CodeBlock><CodeBlockCode>{JSON.stringify(val, null, 2)}</CodeBlockCode></CodeBlock>
                        ) : String(val)}
                      </DescriptionListDescription>
                    </DescriptionListGroup>
                  ))}
                </DescriptionList>
              </div>
            );
          })}
        </div>
      )}

      {/* Full Trace Summary */}
      <div style={{ marginTop: '1rem', padding: '0.75rem', background: 'var(--rh-color--surface-tertiary)', borderRadius: 4, fontSize: '0.8rem', fontFamily: 'var(--rh-font--family-mono, monospace)', lineHeight: 1.8 }}>
        <strong>Trace:</strong> {TYPE_LABELS[r.type] || r.type} ({r.urgency}, {r.confidence_score != null ? `${(r.confidence_score * 100).toFixed(0)}%` : '?'})
        <br />&nbsp;&nbsp;← Decision: <code>{r.decision_logic || '?'}</code>
        {r.rubric_context && r.rubric_context.failures.length > 0 && (
          <>
            <br />&nbsp;&nbsp;← Rubric: {r.rubric_context.failures.map(f => `${f.stage_id} ${f.outcome.toUpperCase()} (${f.failure_class || '?'})`).join(', ')}
          </>
        )}
        {r.constraint_violations && r.constraint_violations.length > 0 && (
          <>
            <br />&nbsp;&nbsp;← Constraints: {r.constraint_violations.map(v => `${v.type} (expected: ${v.expected})`).join(', ')}
          </>
        )}
        <br />&nbsp;&nbsp;← Evidence: {r.evidence ? Object.keys(r.evidence).map(s => s.replace('source_', '')).join(', ') : 'none'}
      </div>

      {/* Rubric Failures */}
      {r.rubric_context && r.rubric_context.failures.length > 0 && (
        <div style={{ marginTop: '1rem' }}>
          <h4 style={{ marginBottom: '0.5rem' }}>
            Rubric Pipeline — {r.rubric_context.stages_passing} passing, {r.rubric_context.stages_failing} failing of {r.rubric_context.stages_evaluated} evaluated
          </h4>
          {r.rubric_context.failures.map((f, i) => (
            <div key={i} style={{ marginBottom: '0.5rem', padding: '0.5rem', border: '1px solid var(--rh-color--border)', borderRadius: 4, borderLeft: `3px solid ${f.outcome === 'fail' ? 'var(--sg-color--critical)' : 'var(--sg-color--warning)'}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                <strong>{f.stage_id}</strong>
                <div>
                  <Label isCompact color={f.outcome === 'fail' ? 'red' : 'orange'}>{f.outcome}</Label>
                  {f.failure_class && <Label isCompact color="grey" style={{ marginLeft: 4 }}>{f.failure_class}</Label>}
                </div>
              </div>
              <div style={{ fontSize: '0.8rem' }}>
                {f.criteria_failed.map(c => (
                  <span key={c} style={{ color: 'var(--sg-color--critical)', marginRight: '0.75rem' }}>✗ {c}</span>
                ))}
                {f.criteria_passed.map(c => (
                  <span key={c} style={{ color: 'var(--sg-color--healthy)', marginRight: '0.75rem' }}>✓ {c}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Constraint Violations */}
      {r.constraint_violations && r.constraint_violations.length > 0 && (
        <div style={{ marginTop: '1rem' }}>
          <h4 style={{ marginBottom: '0.5rem' }}>Constraint Violations</h4>
          {r.constraint_violations.map((v, i) => (
            <div key={i} style={{ marginBottom: '0.5rem', padding: '0.5rem', border: '1px solid var(--rh-color--border)', borderRadius: 4, borderLeft: `3px solid ${v.severity === 'critical' ? 'var(--sg-color--critical)' : 'var(--sg-color--warning)'}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <strong>{v.type.replace(/_/g, ' ')}</strong>
                <Label isCompact color={v.severity === 'critical' ? 'red' : 'orange'}>{v.severity}</Label>
              </div>
              <div style={{ fontSize: '0.8rem', marginTop: '0.25rem' }}>
                <span>Expected: <code>{v.expected}</code></span>
                <span style={{ marginLeft: '1rem' }}>Actual: <code>{v.actual}</code></span>
              </div>
              {v.correlated_rubric_stage && (
                <div style={{ fontSize: '0.8rem', marginTop: '0.25rem', color: 'var(--rh-color--text-secondary)' }}>
                  Correlated: {v.correlated_rubric_stage} → {v.correlated_failure_class || '?'}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Decision Logic */}
      {r.decision_logic && (
        <div style={{ marginTop: '0.75rem' }}>
          <h4 style={{ marginBottom: '0.25rem' }}>Decision Rule</h4>
          <code style={{ fontSize: '0.85rem', padding: '4px 8px', background: 'var(--rh-color--surface-tertiary)', borderRadius: 4 }}>
            {r.decision_logic}
          </code>
        </div>
      )}

      {/* Confidence */}
      {r.confidence_score != null && (
        <div style={{ marginTop: '1rem' }}>
          <h4 style={{ marginBottom: '0.5rem' }}>Confidence</h4>
          <DescriptionList isHorizontal isCompact>
            <DescriptionListGroup>
              <DescriptionListTerm>Score</DescriptionListTerm>
              <DescriptionListDescription>
                <Label isCompact color={r.confidence_score >= 0.9 ? 'green' : r.confidence_score >= 0.75 ? 'yellow' : 'orange'}>
                  {(r.confidence_score * 100).toFixed(0)}%
                </Label>
              </DescriptionListDescription>
            </DescriptionListGroup>
            {r.confidence_reason && (
              <DescriptionListGroup>
                <DescriptionListTerm>Basis</DescriptionListTerm>
                <DescriptionListDescription style={{ fontSize: '0.85rem' }}>{r.confidence_reason}</DescriptionListDescription>
              </DescriptionListGroup>
            )}
          </DescriptionList>
        </div>
      )}

      {/* Feedback */}
      <div style={{ marginTop: '1rem', borderTop: '1px solid var(--rh-color--border)', paddingTop: '0.75rem' }}>
        {feedbackSubmitted === null ? (
          <>
            <span style={{ fontSize: '0.85rem', fontWeight: 600, marginRight: '0.75rem' }}>Is this recommendation actionable?</span>
            <Button variant="link" size="sm" onClick={() => { setFeedbackSubmitted(true); feedback.mutate({ endpoint: 'policy-recommendation', helpful: true, notes: feedbackNotes || undefined }); }} style={{ marginRight: '0.5rem', color: 'var(--sg-color--healthy)' }}>
              Yes, actionable
            </Button>
            <Button variant="link" size="sm" onClick={() => { setFeedbackSubmitted(false); feedback.mutate({ endpoint: 'policy-recommendation', helpful: false, notes: feedbackNotes || undefined }); }} style={{ color: 'var(--sg-color--critical)' }}>
              Not actionable
            </Button>
            <div style={{ marginTop: '0.5rem' }}>
              <TextArea
                value={feedbackNotes}
                onChange={(_e, v) => setFeedbackNotes(v)}
                rows={1}
                placeholder="Optional: why not actionable, or what's missing?"
                style={{ fontSize: '0.85rem' }}
              />
            </div>
          </>
        ) : (
          <Alert
            variant={feedbackSubmitted ? 'success' : 'info'}
            title={feedbackSubmitted ? 'Thanks — marked as actionable' : 'Thanks — marked as not actionable'}
            isInline
            isPlain
          />
        )}
      </div>

      {r.lab_code && (
        <AIAnalysis contextType="lab" labCode={r.lab_code} />
      )}
      {r.cluster && !r.lab_code && (
        <AIAnalysis contextType="cluster" clusterName={r.cluster} />
      )}
    </div>
  );
}
