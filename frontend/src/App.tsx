import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Spinner } from '@patternfly/react-core';
import AppLayout from './components/AppLayout';
import ErrorBoundary from './components/ErrorBoundary';
import Dashboard from './pages/Dashboard';

const LabDetail = lazy(() => import('./pages/LabDetail'));
const ClusterDetail = lazy(() => import('./pages/ClusterDetail'));
const Admin = lazy(() => import('./pages/Admin'));
const LLMAdmin = lazy(() => import('./pages/LLMAdmin'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30000 },
  },
});

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Suspense fallback={<div style={{ padding: '2rem', textAlign: 'center' }}><Spinner size="xl" /></div>}>
            <Routes>
              <Route element={<AppLayout />}>
                <Route index element={<Dashboard />} />
                <Route path="/labs/:labCode" element={<LabDetail />} />
                <Route path="/clusters/:name" element={<ClusterDetail />} />
                <Route path="/admin" element={<Admin />} />
                <Route path="/llm" element={<LLMAdmin />} />
              </Route>
            </Routes>
          </Suspense>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
