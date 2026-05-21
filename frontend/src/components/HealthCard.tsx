import { Card, CardBody, CardTitle } from '@patternfly/react-core';
import type { ClusterSummary } from '../api/types';

function healthColor(rate: number): string {
  if (rate >= 80) return 'var(--sg-color--healthy)';
  if (rate >= 50) return 'var(--sg-color--warning)';
  return 'var(--sg-color--critical)';
}

function healthBg(rate: number): string {
  if (rate >= 80) return 'var(--sg-color--healthy-bg)';
  if (rate >= 50) return 'var(--sg-color--warning-bg)';
  return 'var(--sg-color--critical-bg)';
}

interface HealthCardProps {
  cluster: ClusterSummary;
  onClick: () => void;
}

export default function HealthCard({ cluster, onClick }: HealthCardProps) {
  const topFailures = Object.entries(cluster.failure_classes)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 3);

  return (
    <Card isClickable isSelectable onClick={onClick} isFullHeight>
      <CardTitle>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>{cluster.cluster}</span>
          <span
            style={{
              fontSize: '1.5rem',
              fontWeight: 700,
              color: healthColor(cluster.health_rate),
              background: healthBg(cluster.health_rate),
              padding: '2px 10px',
              borderRadius: '4px',
            }}
          >
            {cluster.health_rate.toFixed(1)}%
          </span>
        </div>
      </CardTitle>
      <CardBody>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', fontSize: '0.9rem' }}>
          <div><strong>{cluster.labs_seen}</strong> labs</div>
          <div><strong>{cluster.labs_failing}</strong> failing</div>
          <div><strong>{cluster.total_evaluations}</strong> evals</div>
          <div><strong>{cluster.systemic_events}</strong> systemic</div>
        </div>
        {topFailures.length > 0 && (
          <div style={{ marginTop: '0.75rem', fontSize: '0.85rem', color: 'var(--rh-color--text-secondary)' }}>
            {topFailures.map(([cls, count]) => (
              <div key={cls}>{cls}: {count}</div>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}
