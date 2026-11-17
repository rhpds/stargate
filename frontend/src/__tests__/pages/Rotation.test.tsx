/**
 * Rotation page — behaviour cases (BDD).
 *
 * The page's job is to say two things without merging them: what Jira counts
 * and what the audit verified. These tests pin the cases where that matters:
 * an explicit empty state, the disagreement callout, and the trend.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { RotationResponse } from '../../api/types';

const useRotation = vi.fn();

vi.mock('../../api/hooks', () => ({
  useRotation: () => useRotation(),
}));

import Rotation from '../../pages/Rotation';

function response(overrides: Partial<RotationResponse> = {}): RotationResponse {
  return {
    generated_at: '2026-11-17T18:00:00Z',
    last_sync: '2026-11-17T18:00:00Z',
    source: { jira: 'ok', verification: 'snapshot' },
    summary: {
      tickets: 15,
      closed: 6,
      closed_pct: 40,
      in_progress: 1,
      new: 8,
      unassigned: 4,
      verified_live: 34,
      live_locations: 162,
      untracked_live: 5,
      providers: 2,
    },
    providers: [
      {
        provider: 'AWS',
        tickets: 12,
        closed: 5,
        in_progress: 1,
        new: 6,
        unassigned: 3,
        closed_pct: 42,
        verified_live: 30,
        live_locations: 150,
        untracked_live: 4,
      },
      {
        provider: 'IBM Cloud',
        tickets: 3,
        closed: 1,
        in_progress: 0,
        new: 2,
        unassigned: 1,
        closed_pct: 33,
        verified_live: 4,
        live_locations: 12,
        untracked_live: 1,
      },
    ],
    trend: [
      { date: '2026-11-16', tickets: 15, closed: 4, in_progress: 1, new: 10, unassigned: 5, verified_live: 30, live_locations: 150, untracked_live: 5 },
      { date: '2026-11-17', tickets: 15, closed: 6, in_progress: 1, new: 8, unassigned: 4, verified_live: 34, live_locations: 162, untracked_live: 5 },
    ],
    ...overrides,
  };
}

describe('Rotation page', () => {
  beforeEach(() => useRotation.mockReset());

  it('shows an explicit empty state instead of fake zeros', () => {
    useRotation.mockReturnValue({
      data: response({
        source: { jira: 'unconfigured', verification: 'none' },
        providers: [],
        trend: [],
        summary: {
          tickets: 0, closed: 0, closed_pct: 0, in_progress: 0, new: 0, unassigned: 0,
          verified_live: 0, live_locations: 0, untracked_live: 0, providers: 0,
        },
      }),
      isLoading: false,
      isError: false,
    });

    render(<Rotation />);

    expect(screen.getByText(/Jira is not configured/i)).toBeInTheDocument();
    expect(screen.getByText(/Nothing is shown as zero that has not been measured/i)).toBeInTheDocument();
  });

  it('shows Jira and audit numbers side by side, and names the gap', () => {
    useRotation.mockReturnValue({ data: response(), isLoading: false, isError: false });

    render(<Rotation />);

    expect(screen.getByText('Progress by provider')).toBeInTheDocument();
    expect(screen.getByText('AWS')).toBeInTheDocument();
    expect(screen.getByText('IBM Cloud')).toBeInTheDocument();
    // Jira total and the audit's verified count are both present.
    expect(screen.getByText('15')).toBeInTheDocument();
    expect(screen.getByText('34')).toBeInTheDocument();
    // The disagreement is stated, not reconciled away.
    expect(screen.getByText(/5 live credentials have no ticket/i)).toBeInTheDocument();
  });

  it('renders the trend once there are two snapshots', () => {
    useRotation.mockReturnValue({ data: response(), isLoading: false, isError: false });

    render(<Rotation />);

    expect(
      screen.getByRole('img', { name: /rotation trend/i }),
    ).toBeInTheDocument();
    expect(screen.getByText('2 snapshots')).toBeInTheDocument();
  });

  it('explains a single snapshot rather than drawing a line from one point', () => {
    const one = response();
    useRotation.mockReturnValue({
      data: response({ trend: [one.trend[0]] }),
      isLoading: false,
      isError: false,
    });

    render(<Rotation />);

    expect(screen.getByText(/One snapshot so far/i)).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /rotation trend/i })).not.toBeInTheDocument();
  });

  it('surfaces a failed load instead of an empty table', () => {
    useRotation.mockReturnValue({ data: undefined, isLoading: false, isError: true });

    render(<Rotation />);

    expect(screen.getByText(/Failed to load the rotation snapshot/i)).toBeInTheDocument();
  });
});
