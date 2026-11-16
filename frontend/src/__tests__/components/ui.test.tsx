/**
 * Shared UI primitives — the contract tests (frontend redesign Phase 2).
 * The primitives replace 14 copies of MetricCard, 7 of relativeTime,
 * etc.; these tests pin the behaviors every page relied on.
 */

import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import {
  MetricCard,
  SectionHeader,
  StateStrip,
  StatusBadge,
  relativeTime,
  statusColor,
} from '../../components/ui';

describe('MetricCard', () => {
  it('renders label, value, and sub', () => {
    render(<MetricCard label="Fleet VM slots" value={3687} sub="48h peak" />);
    expect(screen.getByText('3687')).toBeTruthy();
    expect(screen.getByText('Fleet VM slots')).toBeTruthy();
    expect(screen.getByText('48h peak')).toBeTruthy();
  });

  it('omits sub when absent', () => {
    const { container } = render(<MetricCard label="Sessions" value={0} />);
    expect(container.textContent).not.toContain('undefined');
  });
});

describe('SectionHeader', () => {
  it('renders title and optional right slot', () => {
    render(
      <SectionHeader right={<span>last 24h</span>}>Capacity</SectionHeader>,
    );
    expect(screen.getByText('Capacity')).toBeTruthy();
    expect(screen.getByText('last 24h')).toBeTruthy();
  });
});

describe('relativeTime', () => {
  it('handles null and invalid input without crashing', () => {
    expect(relativeTime(null)).toBe('--');
    expect(relativeTime(undefined)).toBe('--');
    expect(relativeTime('not-a-date')).toBe('--');
  });

  it('formats recent and old times', () => {
    expect(relativeTime(new Date().toISOString())).toMatch(/ago|just now/);
    const old = new Date(Date.now() - 45 * 24 * 3600 * 1000).toISOString();
    expect(relativeTime(old)).toBe('1mo ago');
  });
});

describe('statusColor', () => {
  it('maps known states consistently (RAG semantics)', () => {
    expect(statusColor('ok')).toBe('#3E8635');
    expect(statusColor('FAILED')).toBe('#EE0000'); // case-insensitive
    expect(statusColor('warn')).toBe('#F0AB00');
  });

  it('falls back to neutral, never crashes', () => {
    expect(statusColor(null)).toBe('#6A6E73');
    expect(statusColor('bogus-state')).toBe('#6A6E73');
  });
});

describe('StatusBadge', () => {
  it('renders text AND color — never color alone (a11y rule)', () => {
    render(<StatusBadge status="critical" />);
    const badge = screen.getByText('critical');
    expect(badge).toBeTruthy();
  });
});

describe('StateStrip', () => {
  it('keeps title tooltips when no rich tooltip is provided', () => {
    render(
      <StateStrip
        cells={[
          { state: 'green', title: 'ok hour' },
          { state: 'red' },
          { state: 'floor' },
          { state: 'unknown' },
        ]}
      />,
    );
    expect(screen.getByTitle('ok hour')).toBeTruthy();
    expect(screen.getByTitle('at least (lower bound)')).toBeTruthy();
    expect(screen.getByTitle('not measured')).toBeTruthy();
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('shows the rich tooltip card immediately on cell hover when provided', () => {
    const { container } = render(
      <StateStrip
        cells={[{ state: 'green' }, { state: 'red' }]}
        tooltip={(i) => `hour ${i}: 845 slots`}
      />,
    );
    // hidden until hover — no browser tooltip delay
    expect(screen.queryByRole('tooltip')).toBeNull();
    const cells = container.querySelectorAll('.flex-1');
    fireEvent.mouseEnter(cells[1]!);
    expect(screen.getByRole('tooltip').textContent).toContain('hour 1: 845 slots');
    // titles are replaced by the rich hover, not doubled
    expect(cells[1]!.getAttribute('title')).toBeNull();
    // leaving the strip hides it again
    fireEvent.mouseLeave(container.firstElementChild!);
    expect(screen.queryByRole('tooltip')).toBeNull();
  });
});
