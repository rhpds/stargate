import { Card, CardBody, CardTitle, Gallery, GalleryItem } from '@patternfly/react-core';
import type { OverviewData } from '../api/types';

interface Props {
  data: OverviewData;
  activeView: string;
}

export default function OverviewCards({ data, activeView }: Props) {
  if (activeView === 'labs') {
    const provPct = data.labs.total > 0 ? ((data.provisioning.started / Math.max(data.provisioning.total, 1)) * 100).toFixed(0) : '-';
    return (
      <Gallery hasGutter minWidths={{ default: '160px' }}>
        <StatCard title="Total Labs" value={data.labs.total} />
        <StatCard title="With Sessions" value={data.labs.with_sessions} color="var(--sg-color--info)" />
        <StatCard title="Building" value={data.labs.status_counts.in_development ?? 0} color="var(--sg-color--healthy)" />
        <StatCard title="Planning" value={data.labs.status_counts.planning ?? 0} />
        <StatCard title="Provisioned" value={`${data.provisioning.started}/${data.provisioning.total}`} sub={`${provPct}% success`} color={data.provisioning.failed > 0 ? 'var(--sg-color--warning)' : 'var(--sg-color--healthy)'} />
      </Gallery>
    );
  }

  if (activeView === 'clusters') {
    return (
      <Gallery hasGutter minWidths={{ default: '160px' }}>
        <StatCard title="Clusters" value={data.clusters.total} />
        <StatCard title="Healthy" value={data.clusters.healthy} color="var(--sg-color--healthy)" />
        <StatCard title="Warning" value={data.clusters.warning} color="var(--sg-color--warning)" />
        <StatCard title="Critical" value={data.clusters.critical} color="var(--sg-color--critical)" />
      </Gallery>
    );
  }

  if (activeView === 'pools') {
    return (
      <Gallery hasGutter minWidths={{ default: '160px' }}>
        <StatCard title="Total Pools" value={data.pools.total} />
        <StatCard title="Exhausted" value={data.pools.exhausted} color={data.pools.exhausted > 0 ? 'var(--sg-color--critical)' : undefined} />
        <StatCard title="Low" value={data.pools.low} color={data.pools.low > 0 ? 'var(--sg-color--warning)' : undefined} />
        <StatCard title="Provisioned" value={data.provisioning.started} sub={`of ${data.provisioning.total} (${(100 - data.provisioning.failure_rate).toFixed(0)}%)`} color="var(--sg-color--healthy)" />
        <StatCard title="Prov. Failed" value={data.provisioning.failed} color={data.provisioning.failed > 0 ? 'var(--sg-color--critical)' : undefined} />
      </Gallery>
    );
  }

  if (activeView === 'errors') {
    return (
      <Gallery hasGutter minWidths={{ default: '160px' }}>
        <StatCard title="Total Failures" value={data.errors.total_failures} color={data.errors.total_failures > 0 ? 'var(--sg-color--critical)' : undefined} />
        <StatCard title="Top Class" value={data.errors.top_class ?? '-'} isText />
        <StatCard title="Systemic" value={data.errors.systemic} color={data.errors.systemic > 0 ? 'var(--sg-color--critical)' : undefined} />
      </Gallery>
    );
  }

  return null;
}

function StatCard({ title, value, color, sub, isText }: { title: string; value: string | number; color?: string; sub?: string; isText?: boolean }) {
  return (
    <GalleryItem>
      <Card isCompact isFullHeight>
        <CardTitle style={{ fontSize: '0.85rem' }}>{title}</CardTitle>
        <CardBody style={{ paddingTop: 0 }}>
          <span style={{ fontSize: isText ? '1rem' : '1.5rem', fontWeight: 700, color }}>{value}</span>
          {sub && <div style={{ fontSize: '0.8rem', color: 'var(--rh-color--text-secondary)' }}>{sub}</div>}
        </CardBody>
      </Card>
    </GalleryItem>
  );
}
