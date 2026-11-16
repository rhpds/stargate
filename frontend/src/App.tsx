import { Component, type ReactNode } from 'react';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TimeRangeProvider, ClusterPicker } from './components/TimeRangeContext';
import LabDetail from './pages/LabDetail';
import PipelineMatrix from './pages/PipelineMatrix';
import FailureClasses from './pages/FailureClasses';
import LLMAdmin from './pages/LLMAdmin';
import Remediation from './pages/Remediation';
import ClusterDetail from './pages/ClusterDetail';
import PoolDetail from './pages/PoolDetail';
import ProvisioningDetail from './pages/ProvisioningDetail';
import CatalogItemDetail from './pages/CatalogItemDetail';
import TrendsPage from './pages/TrendsPage';
import CapacityPage from './pages/CapacityPage';
import SummitReport from './pages/SummitReport';
import ProofDashboard from './pages/ProofDashboard';
import Operations from './pages/Operations';
import Overview from './pages/Overview';
import Capacity from './pages/Capacity';
import Investigations from './pages/Investigations';
import Knowledge from './pages/Knowledge';
import DeepfieldOverview from './pages/DeepfieldOverview';
import GeoluxOverview from './pages/GeoluxOverview';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30000 },
  },
});

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: 'var(--brand-dark)' }}>
          <div className="text-center">
            <h1 className="text-2xl font-bold text-white mb-4" style={{ fontFamily: 'Red Hat Display' }}>Something went wrong</h1>
            <p className="text-[#6A6E73] mb-6">{this.state.error.message}</p>
            <button
              onClick={() => { this.setState({ error: null }); window.location.href = '/'; }}
              className="px-4 py-2 rounded text-sm font-medium text-white"
              style={{ backgroundColor: 'var(--brand-primary)' }}
            >
              Return Home
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

const navItems = [
  { to: '/', label: 'Overview', end: true },
  { to: '/capacity', label: 'Capacity' },
  { to: '/investigations', label: 'Investigations' },
  { to: '/knowledge', label: 'Knowledge' },
];

// StarGate's own machinery: in the loop, not in your face — a secondary
// "Platform" group instead of primary nav slots.
const platformNavItems = [
  { to: '/operations', label: 'Operations' },
  { to: '/deepfield', label: 'Deepfield' },
  { to: '/geolux', label: 'GeoLux' },
  { to: '/proof', label: 'Proof Lab' },
  { to: '/failures', label: 'Taxonomy' },
  { to: '/remediation', label: 'Remediation' },
];

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <TimeRangeProvider>
        <BrowserRouter>
          <div className="min-h-screen flex flex-col" style={{ backgroundColor: 'var(--brand-dark)' }}>
            <header style={{ backgroundColor: 'var(--brand-dark)' }} className="text-white">
              <div className="max-w-7xl mx-auto px-6 lg:px-8">
                <div className="flex items-center h-14 gap-6">
                  <div className="flex items-center gap-3 shrink-0">
                    <img src="/logos/redhat.svg" alt="Red Hat" style={{ height: '28px' }} />
                    <span className="text-[#6A6E73]">|</span>
                    <span className="text-lg font-semibold tracking-tight" style={{ fontFamily: 'Red Hat Display, sans-serif' }}>StarGate</span>
                  </div>
                  <nav className="flex gap-1" aria-label="Primary">
                    {navItems.map(({ to, label, end }) => (
                      <NavLink key={to} to={to} end={end}
                        className={({ isActive }) =>
                          `px-3 py-1.5 rounded text-sm font-medium transition ${isActive ? 'bg-white/15 text-white' : 'text-[#6A6E73] hover:text-white hover:bg-white/10'}`
                        }>
                        {label}
                      </NavLink>
                    ))}
                  </nav>
                  <div className="flex-1" />
                  <details className="relative group">
                    <summary className="cursor-pointer list-none text-sm text-[#6A6E73] hover:text-white transition px-3 py-1.5 rounded select-none flex items-center gap-1.5">
                      Platform
                      <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M1 3l4 4 4-4" stroke="currentColor" strokeWidth="1.5" fill="none"/></svg>
                    </summary>
                    <div className="absolute right-0 top-full mt-1 w-44 bg-[#212121] border border-[#3a3a3a] rounded-lg shadow-xl py-1 z-50">
                      {platformNavItems.map(({ to, label }) => (
                        <NavLink key={to} to={to}
                          className="block px-4 py-2 text-sm text-[#c7c7c7] hover:text-white hover:bg-white/10 transition">
                          {label}
                        </NavLink>
                      ))}
                    </div>
                  </details>
                </div>
              </div>
            </header>
            <div className="h-0.5 flex">
              <div className="flex-1" style={{ backgroundColor: 'var(--brand-primary)' }} />
              <div className="flex-1" style={{ backgroundColor: 'var(--brand-secondary)' }} />
            </div>
            <div className="border-b border-[#2e2e2e]" style={{ backgroundColor: '#1a1a1a' }}>
              <div className="max-w-7xl mx-auto px-6 lg:px-8 flex items-center justify-between h-9">
                <ClusterPicker />
              </div>
            </div>
            <main className="flex-1">
              <Routes>
                <Route path="/" element={<Overview />} />
                <Route path="/operations" element={<Operations />} />
                <Route path="/capacity" element={<Capacity />} />
                <Route path="/investigations" element={<Investigations />} />
                <Route path="/knowledge" element={<Knowledge />} />
                <Route path="/proof" element={<ProofDashboard />} />
                <Route path="/deepfield" element={<DeepfieldOverview />} />
                <Route path="/geolux" element={<GeoluxOverview />} />
                <Route path="/lab/:code" element={<LabDetail />} />
                <Route path="/cluster/:name" element={<ClusterDetail />} />
                <Route path="/pool/:name" element={<PoolDetail />} />
                <Route path="/pipeline" element={<PipelineMatrix />} />
                <Route path="/failures" element={<FailureClasses />} />
                <Route path="/remediation" element={<Remediation />} />
                <Route path="/llm" element={<LLMAdmin />} />
                <Route path="/provisioning" element={<ProvisioningDetail />} />
                <Route path="/catalog/:name" element={<CatalogItemDetail />} />
                <Route path="/trends" element={<TrendsPage />} />
                <Route path="/capacity" element={<CapacityPage />} />
                <Route path="/summit" element={<SummitReport />} />
                <Route path="*" element={
                  <div className="max-w-7xl mx-auto px-6 lg:px-8 py-20 text-center">
                    <h1 className="text-3xl font-bold text-white mb-4" style={{ fontFamily: 'Red Hat Display' }}>Page not found</h1>
                    <p className="text-[#6A6E73] mb-6">The page you're looking for doesn't exist.</p>
                    <a href="/" className="px-4 py-2 rounded text-sm font-medium text-white" style={{ backgroundColor: '#EE0000' }}>Return to Operations</a>
                  </div>
                } />
              </Routes>
            </main>
            <footer style={{ backgroundColor: 'var(--brand-dark)' }} className="border-t border-[#333] text-[#6A6E73] text-sm py-5">
              <div className="max-w-7xl mx-auto px-6 lg:px-8 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <img src="/logos/redhat.svg" alt="" style={{ height: '16px', opacity: 0.6 }} />
                </div>
                <span>Validated AI Infrastructure on Red Hat OpenShift</span>
              </div>
            </footer>
          </div>
        </BrowserRouter>
        </TimeRangeProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
