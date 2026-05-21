import { useState, lazy, Suspense } from 'react';
import {
  Alert,
  Card,
  CardBody,
  CardTitle,
  Content,
  PageSection,
  Spinner,
  ToggleGroup,
  ToggleGroupItem,
} from '@patternfly/react-core';
import { useOverview, useSummitDashboard, usePoolsDashboard, usePipeline, useRecommendations } from '../api/hooks';
import type { SummitLab, ClusterScan, PoolEntry, PipelineStage, Recommendation } from '../api/types';
import type { ErrorRow } from '../components/ErrorsView';
import OverviewCards from '../components/OverviewCards';
import ReadinessBanner from '../components/ReadinessBanner';
import DetailDrawer from '../components/DetailDrawer';
import LabsView from '../components/LabsView';
import LabDrawer from '../components/LabDrawer';
import EventFeed from '../components/EventFeed';

// Lazy load non-default tabs
const ClustersView = lazy(() => import('../components/ClustersView'));
const ClusterDrawer = lazy(() => import('../components/ClusterDrawer'));
const PoolsView = lazy(() => import('../components/PoolsView'));
const PoolDrawer = lazy(() => import('../components/PoolDrawer'));
const ErrorsView = lazy(() => import('../components/ErrorsView'));
const ErrorDrawer = lazy(() => import('../components/ErrorDrawer'));
const LabPipelineMatrix = lazy(() => import('../components/LabPipelineMatrix'));
const NodesPodsView = lazy(() => import('../components/NodesPodsView'));
const PipelineDrawer = lazy(() => import('../components/PipelineDrawer'));
const ExecutiveSummary = lazy(() => import('../components/ExecutiveSummary'));
const RecommendationsView = lazy(() => import('../components/RecommendationsView'));
const RecommendationDrawer = lazy(() => import('../components/RecommendationDrawer'));
const SecurityView = lazy(() => import('../components/SecurityView'));
const ForecastView = lazy(() => import('../components/ForecastView'));
const AAPView = lazy(() => import('../components/AAPView'));
const CatalogView = lazy(() => import('../components/CatalogView'));

type View = 'labs' | 'clusters' | 'pools' | 'errors' | 'pipeline' | 'nodes' | 'recommendations' | 'provisioning' | 'security' | 'forecast' | 'catalog';

type Selected =
  | { type: 'lab'; item: SummitLab }
  | { type: 'cluster'; item: ClusterScan }
  | { type: 'pool'; item: PoolEntry }
  | { type: 'error'; item: ErrorRow }
  | { type: 'pipeline'; item: PipelineStage }
  | { type: 'recommendation'; item: Recommendation };

export default function Dashboard() {
  const [view, setView] = useState<View>('labs');
  const [selected, setSelected] = useState<Selected | null>(null);

  const { data: overview, isLoading: loadingOverview, isError: errorOverview } = useOverview();
  const { data: summit, isLoading: loadingSummit } = useSummitDashboard();
  const { data: pools, isLoading: loadingPools } = usePoolsDashboard();
  const { data: pipeline, isLoading: loadingPipeline } = usePipeline();
  const { data: recs } = useRecommendations();

  const handleViewChange = (newView: View) => {
    setView(newView);
    setSelected(null);
  };

  if (loadingOverview) return <PageSection><Spinner size="xl" /></PageSection>;
  if (errorOverview || !overview) return <PageSection><Alert variant="danger" title="Failed to load dashboard" /></PageSection>;

  const drawerTitle =
    selected?.type === 'lab' ? selected.item.lab_code :
    selected?.type === 'cluster' ? selected.item.cluster :
    selected?.type === 'pool' ? selected.item.name :
    selected?.type === 'error' ? selected.item.failure_class :
    selected?.type === 'pipeline' ? selected.item.stage_id :
    selected?.type === 'recommendation' ? (selected.item.lab_code || selected.item.cluster || selected.item.pool_name || '') : '';

  const drawerContent = (() => {
    if (!selected) return null;
    switch (selected.type) {
      case 'lab': {
        const pool = selected.item.pool && summit ? summit.pools[selected.item.pool] ?? null : null;
        return <LabDrawer lab={selected.item} pool={pool} />;
      }
      case 'cluster':
        return <ClusterDrawer cluster={selected.item} />;
      case 'pool':
        return pools ? <PoolDrawer pool={selected.item} dashboard={pools} /> : null;
      case 'error':
        return <ErrorDrawer error={selected.item} />;
      case 'pipeline':
        return <PipelineDrawer stage={selected.item} />;
      case 'recommendation':
        return <RecommendationDrawer recommendation={selected.item} />;
    }
  })();

  const mainContent = (
    <>
      <PageSection style={{ paddingBottom: 0 }}>
        <ReadinessBanner />
      </PageSection>

      <PageSection style={{ paddingBottom: 0 }}>
        <ExecutiveSummary />
      </PageSection>

      <PageSection>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
          <Content>
            <Content component="h1">Platform Readiness</Content>
          </Content>
          <ToggleGroup aria-label="Dashboard view">
            <ToggleGroupItem text="Labs" isSelected={view === 'labs'} onChange={(_e, sel) => sel && handleViewChange('labs')} />
            <ToggleGroupItem text="Clusters" isSelected={view === 'clusters'} onChange={(_e, sel) => sel && handleViewChange('clusters')} />
            <ToggleGroupItem text="Pools" isSelected={view === 'pools'} onChange={(_e, sel) => sel && handleViewChange('pools')} />
            <ToggleGroupItem text="Errors" isSelected={view === 'errors'} onChange={(_e, sel) => sel && handleViewChange('errors')} />
            <ToggleGroupItem text="Pipeline" isSelected={view === 'pipeline'} onChange={(_e, sel) => sel && handleViewChange('pipeline')} />
            <ToggleGroupItem text="Nodes & Pods" isSelected={view === 'nodes'} onChange={(_e, sel) => sel && handleViewChange('nodes')} />
            <ToggleGroupItem text={`Recommendations${recs ? ` (${recs.total})` : ''}`} isSelected={view === 'recommendations'} onChange={(_e, sel) => sel && handleViewChange('recommendations')} />
            <ToggleGroupItem text="Security" isSelected={view === 'security'} onChange={(_e, sel) => sel && handleViewChange('security')} />
            <ToggleGroupItem text="Provisioning" isSelected={view === 'provisioning'} onChange={(_e, sel) => sel && handleViewChange('provisioning')} />
            <ToggleGroupItem text="Forecast" isSelected={view === 'forecast'} onChange={(_e, sel) => sel && handleViewChange('forecast')} />
            <ToggleGroupItem text="Catalog" isSelected={view === 'catalog'} onChange={(_e, sel) => sel && handleViewChange('catalog')} />
          </ToggleGroup>
        </div>
      </PageSection>

      {view !== 'pipeline' && view !== 'nodes' && (
        <PageSection>
          <OverviewCards data={overview} activeView={view} />
        </PageSection>
      )}

      <PageSection variant="secondary">
        {view === 'labs' && (loadingSummit || !summit
          ? <Spinner size="lg" />
          : <LabsView data={summit} onSelect={(lab) => setSelected({ type: 'lab', item: lab })} selectedCode={selected?.type === 'lab' ? selected.item.lab_code : null} />
        )}
        <Suspense fallback={<Spinner size="lg" />}>
        {view === 'clusters' && (
          <ClustersView data={overview} onSelect={(c) => setSelected({ type: 'cluster', item: c })} selectedCluster={selected?.type === 'cluster' ? selected.item.cluster : null} />
        )}
        {view === 'pools' && (loadingPools || !pools
          ? <Spinner size="lg" />
          : <PoolsView data={pools} onSelect={(p) => setSelected({ type: 'pool', item: p })} selectedPool={selected?.type === 'pool' ? selected.item.name : null} />
        )}
        {view === 'errors' && (
          <ErrorsView data={overview} onSelect={(e) => setSelected({ type: 'error', item: e })} selectedClass={selected?.type === 'error' ? selected.item.failure_class : null} />
        )}
        {view === 'nodes' && <NodesPodsView />}
        {view === 'recommendations' && (
          <RecommendationsView
            onSelectPipelineStage={(s) => setSelected({ type: 'pipeline', item: s })}
            onSelectRecommendation={(r) => setSelected({ type: 'recommendation', item: r })}
            selectedStage={selected?.type === 'pipeline' ? selected.item.stage_id : null}
            selectedRecommendation={selected?.type === 'recommendation' ? selected.item : null}
          />
        )}
        {view === 'pipeline' && (
          <>
            {loadingPipeline || !pipeline
              ? <Spinner size="lg" />
              : <StageHealthFlow stages={pipeline.stages} onSelect={(s) => setSelected({ type: 'pipeline', item: s })} />
            }
            <LabPipelineMatrix />
          </>
        )}
        {view === 'security' && <SecurityView />}
        {view === 'provisioning' && <AAPView />}
        {view === 'forecast' && <ForecastView />}
        {view === 'catalog' && <CatalogView />}
        </Suspense>
      </PageSection>

      <PageSection>
        <Card>
          <CardTitle>Recent Activity</CardTitle>
          <CardBody>
            <EventFeed />
          </CardBody>
        </Card>
      </PageSection>
    </>
  );

  return (
    <DetailDrawer
      isExpanded={!!selected}
      title={drawerTitle}
      onClose={() => setSelected(null)}
      mainContent={mainContent}
    >
      {drawerContent}
    </DetailDrawer>
  );
}

const STAGE_SHORT_NAMES: Record<string, string> = {
  'cluster-health': 'Cluster', 'run-created': 'Run', 'provision-complete': 'Provision',
  'namespace-ready': 'NS', 'deployment-ready': 'Deploy', 'storage-clone-ready': 'Storage',
  'route-ready': 'Route', 'vm-runtime-ready': 'VM', 'smoke-test-ready': 'Smoke',
  'showroom-healthy': 'Showroom', 'model-endpoint-ready': 'Model',
};

function StageHealthFlow({ stages, onSelect }: { stages: PipelineStage[]; onSelect: (s: PipelineStage) => void }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, overflowX: 'auto', padding: '1rem 0', marginBottom: '0.5rem' }}>
      {stages.map((s, i) => {
        const health = s.health_rate ?? 0;
        const hasData = s.total > 0;
        const color = !hasData ? '#d2d2d2' : health >= 95 ? '#3e8635' : health >= 80 ? '#f0ab00' : '#c9190b';
        const bg = !hasData ? '#f0f0f0' : health >= 95 ? '#f3faf2' : health >= 80 ? '#fff4e6' : '#fceaea';

        return (
          <div key={s.stage_id} style={{ display: 'flex', alignItems: 'center' }}>
            <div
              onClick={() => onSelect(s)}
              style={{
                padding: '8px 12px', borderRadius: '8px', border: `2px solid ${color}`,
                background: bg, cursor: 'pointer', textAlign: 'center', minWidth: '70px',
                transition: 'transform 0.1s',
              }}
              onMouseEnter={e => { e.currentTarget.style.transform = 'scale(1.05)'; }}
              onMouseLeave={e => { e.currentTarget.style.transform = 'scale(1)'; }}
              title={`${s.stage_id}: ${s.pass} pass, ${s.warn} warn, ${s.fail} fail (${health}%)`}
            >
              <div style={{ fontSize: '0.7rem', fontWeight: 600, color: '#151515' }}>
                {STAGE_SHORT_NAMES[s.stage_id] || s.stage_id}
              </div>
              <div style={{ fontSize: '1.1rem', fontWeight: 700, color }}>
                {hasData ? `${Math.round(health)}%` : '—'}
              </div>
              {hasData && (
                <div style={{ fontSize: '0.6rem', color: '#6a6e73' }}>
                  {s.pass}✓ {s.fail > 0 ? `${s.fail}✗` : ''} {s.warn > 0 ? `${s.warn}⚠` : ''}
                </div>
              )}
            </div>
            {i < stages.length - 1 && (
              <svg width="24" height="12" viewBox="0 0 24 12" style={{ flexShrink: 0 }}>
                <line x1="0" y1="6" x2="18" y2="6" stroke={color} strokeWidth="2" />
                <polygon points="18,2 24,6 18,10" fill={color} />
              </svg>
            )}
          </div>
        );
      })}
    </div>
  );
}
