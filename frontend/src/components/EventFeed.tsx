import { Label, Spinner } from '@patternfly/react-core';
import { useEvents } from '../api/hooks';

function priorityColor(priority: number): string {
  if (priority >= 8) return 'var(--sg-color--critical)';
  if (priority >= 5) return 'var(--sg-color--warning)';
  if (priority > 0) return 'var(--sg-color--info)';
  return '#d2d2d2';
}

interface GroupedEvent {
  lab_code: string;
  cluster_name: string;
  timestamp: string;
  events: Array<{ outcome: string; failure_class: string | null; systemic: boolean; stage_id: string }>;
  max_priority: number;
  has_systemic: boolean;
}

export default function EventFeed() {
  const { data: events, isLoading } = useEvents({ limit: '60' });

  if (isLoading) return <Spinner size="md" />;
  if (!events || events.length === 0) return <div style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>No recent events</div>;

  const nonFiltered = events.filter((e: any) => !e.filtered);
  if (nonFiltered.length === 0) return <div style={{ color: 'var(--rh-color--text-secondary, #6a6e73)' }}>All recent events filtered (routine passes)</div>;

  // Group by lab_code + timestamp minute
  const groups: Record<string, GroupedEvent> = {};
  for (const evt of nonFiltered) {
    const ts = new Date(evt.timestamp);
    const key = `${evt.lab_code || 'unknown'}-${evt.cluster_name || ''}-${ts.getHours()}:${ts.getMinutes()}`;
    if (!groups[key]) {
      groups[key] = {
        lab_code: evt.lab_code || 'unknown',
        cluster_name: evt.cluster_name || '',
        timestamp: evt.timestamp,
        events: [],
        max_priority: 0,
        has_systemic: false,
      };
    }
    groups[key].events.push({
      outcome: evt.outcome ?? evt.event_type?.split('.')[1] ?? '?',
      failure_class: evt.failure_class,
      systemic: evt.systemic,
      stage_id: evt.stage_id || '',
    });
    if (evt.priority > groups[key].max_priority) groups[key].max_priority = evt.priority;
    if (evt.systemic) groups[key].has_systemic = true;
  }

  const sorted = Object.values(groups).sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()).slice(0, 15);

  return (
    <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
      {sorted.map((group, i) => {
        const fails = group.events.filter(e => e.outcome === 'fail');
        const passes = group.events.filter(e => e.outcome === 'pass');
        const warns = group.events.filter(e => e.outcome === 'warn');

        return (
          <div
            key={i}
            style={{
              padding: '0.5rem 0.75rem',
              borderLeft: `3px solid ${priorityColor(group.max_priority)}`,
              marginBottom: '0.5rem',
              fontSize: '0.85rem',
              background: group.has_systemic ? 'var(--sg-color-bg--critical, #fceaea)' : undefined,
              borderRadius: '2px',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
              <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                <Label isCompact color="blue">{group.lab_code}</Label>
                {group.cluster_name && <Label isCompact>{group.cluster_name}</Label>}
                {group.has_systemic && <Label isCompact color="red">SYSTEMIC</Label>}
              </div>
              <span style={{ color: 'var(--rh-color--text-secondary, #6a6e73)', fontSize: '0.8rem' }}>
                {new Date(group.timestamp).toLocaleTimeString()}
              </span>
            </div>
            <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', fontSize: '0.8rem' }}>
              {fails.map((e, j) => (
                <span key={`f${j}`} style={{ color: 'var(--sg-color--critical)', fontWeight: 600 }}>
                  ✗ {e.failure_class || e.outcome}
                </span>
              ))}
              {warns.length > 0 && (
                <span style={{ color: 'var(--sg-color--warning)' }}>⚠ {warns.length} warn</span>
              )}
              {passes.length > 0 && (
                <span style={{ color: 'var(--sg-color--healthy)' }}>✓ {passes.length} pass</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
