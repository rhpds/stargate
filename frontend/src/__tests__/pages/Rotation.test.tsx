/**
 * Rotation page — behaviour cases (BDD).
 *
 * The page's job is to say two things without merging them: what Jira counts
 * and what the audit verified. These tests pin the cases where that matters:
 * an explicit empty state, the disagreement callout, and the trend.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import type { RotationResponse } from '../../api/types';

const useRotation = vi.fn();
const useRotationProvider = vi.fn();

vi.mock('../../api/hooks', () => ({
  useRotation: () => useRotation(),
  useRotationProvider: (provider: string | null) => useRotationProvider(provider),
}));

import Rotation from '../../pages/Rotation';

function response(overrides: Partial<RotationResponse> = {}): RotationResponse {
  return {
    generated_at: '2026-11-17T18:00:00Z',
    last_sync: '2026-11-17T18:00:00Z',
    source: {
      jira: 'ok',
      verification: 'snapshot',
      verification_at: '2026-11-17T13:00:00Z',
    },
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
    links: [
      { label: 'Progress spreadsheet', url: 'https://docs.google.com/spreadsheets/d/example' },
    ],
    trend: [
      { date: '2026-11-16', tickets: 15, closed: 4, in_progress: 1, new: 10, unassigned: 5, verified_live: 30, live_locations: 150, untracked_live: 5 },
      { date: '2026-11-17', tickets: 15, closed: 6, in_progress: 1, new: 8, unassigned: 4, verified_live: 34, live_locations: 162, untracked_live: 5 },
    ],
    ...overrides,
  };
}

const providerDetail = {
  provider: 'AWS',
  jira_url: 'https://redhat.atlassian.net/issues/?jql=key%20in%20%28GPTEINFRA-3%29',
  credential_counts: { total: 2, ticketed: 1, untracked: 1 },
  credentials: [
    {
      id: 'abc123',
      credential: 'aws.assumerole_secret',
      live_copies: 87,
      clusters: 'ocpv-infra01',
      example_location: 'anarchy-operator/gpte-sandbox:key',
      coverage: 'in-jira',
      jira_keys: 'GPTEINFRA-9',
    },
    {
      id: 'def456',
      credential: 'sandbox_metrics_key',
      live_copies: 3,
      clusters: null,
      example_location: null,
      coverage: 'not-in-tracker',
      jira_keys: null,
    },
  ],
  counts: { tickets: 2, closed: 0, in_progress: 1, new: 1, unassigned: 1 },
  audit: { verified_live: 30, live_locations: 150, untracked_live: 4 },
  tickets: [
    {
      key: 'GPTEINFRA-3',
      summary: '[turkeyvulture] Maintenance — Rotate cluster-scheduler-token (AWS)',
      status: 'In Progress',
      assignee: 'Guillaume',
      url: 'https://redhat.atlassian.net/browse/GPTEINFRA-3',
    },
    {
      key: 'GPTEINFRA-2',
      summary: '[turkeyvulture] Maintenance — Rotate models_aws_s3_access_key (AWS)',
      status: 'New',
      assignee: null,
      url: 'https://redhat.atlassian.net/browse/GPTEINFRA-2',
    },
  ],
};

describe('Rotation page', () => {
  beforeEach(() => {
    useRotation.mockReset();
    useRotationProvider.mockReset();
    useRotationProvider.mockReturnValue({ data: providerDetail, isLoading: false, isError: false });
  });

  it('shows an explicit empty state instead of fake zeros', () => {
    useRotation.mockReturnValue({
      data: response({
        source: { jira: 'unconfigured', verification: 'none', verification_at: null },
        providers: [],
        links: [
      { label: 'Progress spreadsheet', url: 'https://docs.google.com/spreadsheets/d/example' },
    ],
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
    // Jira total and the audit's verified count are both present (in the
    // metric cards and again in the totals row).
    expect(screen.getAllByText('15').length).toBeGreaterThan(0);
    expect(screen.getAllByText('34').length).toBeGreaterThan(0);
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

  it('links to where the source data lives', () => {
    useRotation.mockReturnValue({ data: response(), isLoading: false, isError: false });

    render(<Rotation />);

    const link = screen.getByRole('link', { name: /progress spreadsheet/i });
    expect(link).toHaveAttribute('href', 'https://docs.google.com/spreadsheets/d/example');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('omits the source row when no links are configured', () => {
    useRotation.mockReturnValue({ data: response({ links: [] }), isLoading: false, isError: false });

    render(<Rotation />);

    expect(screen.queryByText('Source data:')).not.toBeInTheDocument();
  });

  it('totals every column, including untracked, without adding a fake provider', () => {
    useRotation.mockReturnValue({ data: response(), isLoading: false, isError: false });

    render(<Rotation />);

    const totals = within(screen.getByTestId('rotation-totals'));
    expect(totals.getByText('15')).toBeInTheDocument();
    expect(totals.getByText('40%')).toBeInTheDocument();
    expect(totals.getByText('34')).toBeInTheDocument();
    expect(totals.getByText('5')).toBeInTheDocument();
    // Provider rows only; the total is a footer, not a provider.
    expect(screen.getAllByRole('button', { name: /AWS|IBM Cloud/ })).toHaveLength(2);
  });

  it('says when the audit last verified the numbers', () => {
    useRotation.mockReturnValue({ data: response(), isLoading: false, isError: false });

    render(<Rotation />);

    expect(screen.getByText(/audit verified/i)).toBeInTheDocument();
  });

  it('opens a provider into its tickets', () => {
    useRotation.mockReturnValue({ data: response(), isLoading: false, isError: false });

    render(<Rotation />);
    fireEvent.click(screen.getByRole('button', { name: /AWS/ }));

    expect(screen.getByText('GPTEINFRA-3')).toBeInTheDocument();
    expect(screen.getByText('Guillaume')).toBeInTheDocument();
    expect(screen.getByText(/audit: 30 verified/)).toBeInTheDocument();
    expect(screen.getByText('aws.assumerole_secret')).toBeInTheDocument();
    expect(screen.getByText('sandbox_metrics_key')).toBeInTheDocument();
    expect(screen.getByText(/1 untracked/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /open in jira/i })).toHaveAttribute(
      'href',
      providerDetail.jira_url,
    );
    expect(screen.getByRole('button', { name: /AWS/ })).toHaveAttribute('aria-expanded', 'true');
  });

  it('closes the detail on a second click', () => {
    useRotation.mockReturnValue({ data: response(), isLoading: false, isError: false });

    render(<Rotation />);
    const row = screen.getByRole('button', { name: /AWS/ });
    fireEvent.click(row);
    fireEvent.click(row);

    expect(screen.queryByText('GPTEINFRA-3')).not.toBeInTheDocument();
    expect(row).toHaveAttribute('aria-expanded', 'false');
  });

  it('surfaces a failed load instead of an empty table', () => {
    useRotation.mockReturnValue({ data: undefined, isLoading: false, isError: true });

    render(<Rotation />);

    expect(screen.getByText(/Failed to load the rotation snapshot/i)).toBeInTheDocument();
  });
});
