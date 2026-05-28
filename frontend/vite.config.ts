import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const apiTarget = process.env.API_PROXY_TARGET || 'http://localhost:8090';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/dashboard': apiTarget,
      '/runs': apiTarget,
      '/labs': apiTarget,
      '/clusters': apiTarget,
      '/events': apiTarget,
      '/health': apiTarget,
      '/constraints': apiTarget,
      '/integration': apiTarget,
      '/admin/scheduler': apiTarget,
      '/admin/scan-history': apiTarget,
      '/admin/llm': apiTarget,
      '/admin/remediation': apiTarget,
      '/admin/approval-queue': apiTarget,
      '/admin/receipts': apiTarget,
      '/api/v1': apiTarget,
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/__tests__/setup.ts',
  },
});
