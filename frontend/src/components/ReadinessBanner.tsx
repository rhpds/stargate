import {
  Alert,
  Card,
  CardBody,
  Flex,
  FlexItem,
  Label,
  Skeleton,
} from '@patternfly/react-core';
import { ChartDonutUtilization } from '@patternfly/react-charts/victory';
import { useReadiness } from '../api/hooks';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import type { ReadinessData } from '../api/types';

const GATE_COLORS: Record<string, string> = {
  red: 'var(--sg-color--critical)',
  yellow: 'var(--sg-color--warning)',
  green: 'var(--sg-color--healthy)',
};

function GateLine({ name, color, children }: { name: string; color: 'green' | 'orange' | 'red'; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.3rem', fontSize: '0.9rem' }}>
      <Label color={color} isCompact style={{ minWidth: 90 }}>{name}</Label>
      <span>{children}</span>
    </div>
  );
}

function gateColor(status: string): 'green' | 'orange' | 'red' {
  return status === 'green' ? 'green' : status === 'yellow' ? 'orange' : 'red';
}

function renderGates(data: ReadinessData) {
  const { gates } = data;
  return (
    <div>
      <GateLine name="Provisioning" color={gateColor(gates.provisioning.status)}>
        <strong>{gates.provisioning.value}</strong> / {gates.provisioning.target} labs deployed ({gates.provisioning.pct}%)
      </GateLine>
      <GateLine name="Health" color={gateColor(gates.health.status)}>
        <strong>{gates.health.value}%</strong> cluster health (target: {gates.health.target}%)
      </GateLine>
      <GateLine name="Deployments" color={gateColor(gates.sessions.status)}>
        <strong>{gates.sessions.value}</strong> / {gates.sessions.target} labs with sessions ({gates.sessions.pct}%)
      </GateLine>
      <GateLine name="Infrastructure" color={gateColor(gates.infrastructure.status)}>
        {gates.infrastructure.detail}
      </GateLine>
      {gates.capacity && (
        <GateLine name="Capacity" color={gateColor(gates.capacity.status)}>
          {gates.capacity.detail}
        </GateLine>
      )}
      {gates.sandbox_api && (
        <GateLine name="Sandbox API" color={gateColor(gates.sandbox_api.status)}>
          {gates.sandbox_api.detail}
        </GateLine>
      )}
    </div>
  );
}

export default function ReadinessBanner() {
  const { data, isLoading, isError } = useReadiness();
  const { data: actionStrip } = useQuery({ queryKey: ['action-strip'], queryFn: api.getActionStrip, refetchInterval: 30_000 });

  if (isLoading) {
    return <Skeleton height="120px" />;
  }
  if (isError || !data) return null;

  return (
    <>
      {data.escalated_events > 0 && (
        <Alert variant="danger" title={`${data.escalated_events} escalated event(s) require attention`} isInline style={{ marginBottom: '1rem' }} />
      )}
      <Card isPlain>
        <CardBody>
          <Flex alignItems={{ default: 'alignItemsCenter' }} gap={{ default: 'gap2xl' }} flexWrap={{ default: 'wrap' }}>
            <FlexItem>
              <div style={{ textAlign: 'center' }}>
                {(data.days_until_event != null || data.days_until_summit != null) ? (
                  <>
                    <div style={{ fontSize: '2.5rem', fontWeight: 700, lineHeight: 1, color: GATE_COLORS[(data.days_until_event ?? data.days_until_summit ?? 99) <= 3 ? 'red' : (data.days_until_event ?? data.days_until_summit ?? 99) <= 14 ? 'yellow' : 'green'] }}>
                      {data.days_until_event ?? data.days_until_summit}
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>days to event</div>
                  </>
                ) : (
                  <>
                    <div style={{ fontSize: '1.5rem', fontWeight: 700, lineHeight: 1.2, color: 'var(--sg-color--healthy, #3e8635)' }}>
                      Live
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>continuous ops</div>
                  </>
                )}
              </div>
            </FlexItem>

            <FlexItem>
              <div style={{ width: 100, height: 100 }}>
                <ChartDonutUtilization
                  data={{ x: 'Readiness', y: data.overall_readiness_pct }}
                  title={`${Math.round(data.overall_readiness_pct)}%`}
                  subTitle="ready"
                  thresholds={[{ value: 33, color: '#C9190B' }, { value: 66, color: '#F0AB00' }]}
                  height={100}
                  width={100}
                  padding={{ top: 0, bottom: 0, left: 0, right: 0 }}
                />
              </div>
            </FlexItem>

            <FlexItem grow={{ default: 'grow' }}>
              {renderGates(data)}
              <div style={{ marginTop: '0.5rem', fontSize: '0.75rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>
                Readiness score: 30% provisioning + 25% health + 15% sessions + 10% infra + 10% capacity + 10% sandbox-api
              </div>
            </FlexItem>
          </Flex>

          {/* Action Strip */}
          {actionStrip?.actions?.length > 0 && (
            <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginTop: '1rem', padding: '0.75rem', background: '#f8f9fa', borderRadius: '6px', border: '1px solid #e2e8f0' }}>
              {actionStrip.actions.map((a: any, i: number) => (
                <div key={i} style={{
                  display: 'flex', alignItems: 'center', gap: '6px',
                  padding: '4px 12px', borderRadius: '4px', fontSize: '0.85rem', fontWeight: 600,
                  background: a.urgency === 'critical' ? '#fceaea' : a.urgency === 'high' ? '#fff4e6' : '#f0f0f0',
                  border: `1px solid ${a.urgency === 'critical' ? '#c9190b' : a.urgency === 'high' ? '#f0ab00' : '#d2d2d2'}`,
                  color: a.urgency === 'critical' ? '#a30000' : a.urgency === 'high' ? '#8f4700' : '#151515',
                }}>
                  <span style={{ fontSize: '0.8rem' }}>{a.urgency === 'critical' ? '🔴' : a.urgency === 'high' ? '🟡' : '🔵'}</span>
                  {a.message}
                </div>
              ))}
            </div>
          )}

          {/* Source Freshness */}
          {actionStrip?.source_freshness && (
            <div style={{ display: 'flex', gap: '1rem', marginTop: '0.5rem', fontSize: '0.75rem', color: 'var(--rh-color--text-secondary, #6a6e73)' }}>
              <span>Sources:</span>
              {Object.entries(actionStrip.source_freshness).map(([src, info]: [string, any]) => (
                <span key={src} style={{ display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                  <span style={{
                    width: 6, height: 6, borderRadius: '50%',
                    backgroundColor: info.status === 'fresh' ? '#3e8635' : info.status === 'aging' ? '#f0ab00' : info.status === 'stale' ? '#c9190b' : '#d2d2d2',
                  }} />
                  {src}
                </span>
              ))}
            </div>
          )}
        </CardBody>
      </Card>
    </>
  );
}
