/**
 * Shared UI primitives — one definition site (frontend redesign Phase 2).
 *
 * These replace the per-page copies: MetricCard ×14, SectionHeader ×12,
 * relativeTime ×7, statusColor ×7. The props are the superset of every
 * variant found across the pages; all previously-supported call shapes
 * remain valid.
 */

import React from 'react';

export function MetricCard({
  label,
  value,
  sub,
  onClick,
}: {
  label: string;
  value: string | number;
  sub?: string;
  onClick?: () => void;
}) {
  return (
    <div
      className={`bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 ${
        onClick ? 'cursor-pointer hover:border-[#555] transition' : ''
      }`}
      onClick={onClick}
    >
      <div
        className="text-2xl font-bold text-white"
        style={{ fontFamily: 'Red Hat Display' }}
      >
        {value}
      </div>
      <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">
        {label}
      </div>
      {sub && <div className="text-xs text-[#6A6E73] mt-0.5">{sub}</div>}
    </div>
  );
}

export function SectionHeader({
  children,
  right,
  onClick,
}: {
  children: React.ReactNode;
  right?: React.ReactNode;
  onClick?: () => void;
}) {
  return (
    <div
      className={`flex items-center justify-between mb-3 ${
        onClick ? 'cursor-pointer hover:opacity-80 transition' : ''
      }`}
      onClick={onClick}
    >
      <h2 className="text-base font-semibold text-white">{children}</h2>
      {right && <div className="text-xs text-[#6A6E73]">{right}</div>}
    </div>
  );
}

/**
 * Canonical relative-time formatting. Never color-only, never crashes on
 * null — the a11y rule "no naked values" applies to time too.
 */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '--';
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff)) return '--';
  if (diff < 0) return 'just now';
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  return `${months}mo ago`;
}

/**
 * Shared status palette — the consistent RAG semantics. Domain maps
 * extend it; the fallback is always the neutral gray, never a crash.
 */
export const STATUS_COLORS: Record<string, string> = {
  ok: '#3E8635',
  good: '#3E8635',
  healthy: '#3E8635',
  green: '#3E8635',
  pass: '#3E8635',
  running: '#3E8635',
  active: '#3E8635',
  ready: '#3E8635',
  warn: '#F0AB00',
  warning: '#F0AB00',
  amber: '#F0AB00',
  degraded: '#F0AB00',
  pending: '#F0AB00',
  fail: '#EE0000',
  failed: '#EE0000',
  error: '#EE0000',
  red: '#EE0000',
  critical: '#EE0000',
  down: '#EE0000',
  unavailable: '#EE0000',
};

export function statusColor(status: string | null | undefined): string {
  if (!status) return '#6A6E73';
  return STATUS_COLORS[status.toLowerCase()] ?? '#6A6E73';
}

/**
 * StatusBadge — color PLUS text, never color alone (the a11y rule).
 */
export function StatusBadge({
  status,
  colors,
}: {
  status: string;
  colors?: Record<string, string>;
}) {
  const map = colors ?? STATUS_COLORS;
  const bg = map[status?.toLowerCase?.() ?? ''] ?? '#6A6E73';
  return (
    <span
      className="text-xs font-semibold px-2 py-0.5 rounded-full w-fit"
      style={{ backgroundColor: bg, color: '#fff' }}
    >
      {status}
    </span>
  );
}
