import { Component, type ReactNode } from 'react';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import EcosystemHealth from './pages/EcosystemHealth';
import LabDetail from './pages/LabDetail';
import PipelineMatrix from './pages/PipelineMatrix';
import FailureClasses from './pages/FailureClasses';
import LLMAdmin from './pages/LLMAdmin';
import Remediation from './pages/Remediation';
import ClusterDetail from './pages/ClusterDetail';

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
  { to: '/', label: 'Health', end: true },
  { to: '/pipeline', label: 'Pipeline' },
  { to: '/failures', label: 'Failures' },
  { to: '/llm', label: 'LLM' },
  { to: '/remediation', label: 'Remediation' },
];

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <div className="min-h-screen flex flex-col" style={{ backgroundColor: 'var(--brand-dark)' }}>
            <header style={{ backgroundColor: 'var(--brand-dark)' }} className="text-white border-b border-[#333]">
              <div className="max-w-7xl mx-auto px-6 lg:px-8">
                <div className="flex items-center justify-between h-16">
                  <div className="flex items-center gap-4">
                    <img src="/logos/redhat.svg" alt="Red Hat" style={{ height: '28px' }} />
                    <span className="text-[#6A6E73] mx-3">|</span>
                    <span className="text-lg font-semibold tracking-tight" style={{ fontFamily: 'Red Hat Display, sans-serif' }}>StarGate</span>
                  </div>
                  <nav className="flex gap-1">
                    {navItems.map(({ to, label, end }) => (
                      <NavLink key={to} to={to} end={end}
                        className={({ isActive }) =>
                          `px-3 py-2 rounded text-sm font-medium transition ${isActive ? 'bg-white/15 text-white' : 'text-[#6A6E73] hover:text-white hover:bg-white/10'}`
                        }>
                        {label}
                      </NavLink>
                    ))}
                  </nav>
                </div>
              </div>
            </header>
            <div className="h-0.5 flex">
              <div className="flex-1" style={{ backgroundColor: 'var(--brand-primary)' }} />
              <div className="flex-1" style={{ backgroundColor: 'var(--brand-secondary)' }} />
            </div>
            <main className="flex-1">
              <Routes>
                <Route path="/" element={<EcosystemHealth />} />
                <Route path="/lab/:code" element={<LabDetail />} />
                <Route path="/pipeline" element={<PipelineMatrix />} />
                <Route path="/failures" element={<FailureClasses />} />
                <Route path="/llm" element={<LLMAdmin />} />
                <Route path="/remediation" element={<Remediation />} />
                <Route path="/cluster/:name" element={<ClusterDetail />} />
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
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
