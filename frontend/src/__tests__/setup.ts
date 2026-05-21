import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

vi.mock('@patternfly/react-charts/victory', () => ({
  Chart: ({ children }: { children?: React.ReactNode }) => children ?? null,
  ChartArea: () => null,
  ChartAxis: () => null,
  ChartBar: () => null,
  ChartStack: () => null,
  ChartTooltip: () => null,
  ChartDonutUtilization: () => null,
  ChartVoronoiContainer: () => null,
}));
