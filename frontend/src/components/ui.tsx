/**
 * Shared UI primitives — one definition site (frontend redesign Phase 2).
 * Visual pass: elevated cards with status accents, the RAG strip for
 * instant fleet reads, refined typography rhythm.
 */

import React from 'react';

export function MetricCard({
  label,
  value,
  sub,
  onClick,
  accent,
}: {
  label: string;
  value: string | number | React.ReactNode;
  sub?: string;
  onClick?: () => void;
  accent?: 'green' | 'amber' | 'red';
}) {
  const accentBorder =
    accent === 'green' ? 'border-l-[#3E8635]'
      : accent === 'amber' ? 'border-l-[#F0AB00]'
        : accent === 'red' ? 'border-l-[#EE0000]'
          : '';
  return (
    <div
      className={`bg-gradient-to-b from-[#252525] to-[#212121] border border-[#2e2e2e] border-l-2 ${accentBorder} rounded-lg p-4 shadow-sm ${onClick ? 'cursor-pointer hover:border-[#555] hover:shadow-md transition-all' : 'transition-shadow'}`}
      onClick={onClick}
    >
      <div
        className="text-2xl font-bold text-white tabular-nums"
        style={{ fontFamily: 'Red Hat Display' }}
      >
        {value}
      </div>
      <div className="text-xs text-[#6A6E73] uppercase tracking-wider mt-1">
        {label}
      </div>
      {sub && <div className="text-xs text-[#8a8a8a] mt-0.5">{sub}</div>}
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
      className={`flex items-center justify-between mb-3 ${onClick ? 'cursor-pointer hover:opacity-80 transition' : ''}`}
      onClick={onClick}
    >
      <h2 className="text-sm font-semibold text-white uppercase tracking-wide">
        {children}
      </h2>
      {right && <div className="text-xs text-[#6A6E73]">{right}</div>}
    </div>
  );
}

/**
 * The fleet strip: one colored segment per cluster — the instant visual
 * read the overview needed. Hover for the name; a screen-reader label
 * carries the full state (a11y rule: never color alone).
 */
export function FleetStrip({
  segments,
}: {
  segments: { name: string; rag: 'green' | 'amber' | 'red' | string }[];
}) {
  if (!segments.length) return null;
  const colors: Record<string, string> = {
    green: '#3E8635',
    amber: '#F0AB00',
    red: '#EE0000',
  };
  return (
    <div
      className="flex h-2 rounded-full overflow-hidden gap-px"
      role="img"
      aria-label={`Fleet: ${segments.filter((s) => s.rag === 'red').length} critical, ${segments.filter((s) => s.rag === 'amber').length} degraded, ${segments.filter((s) => s.rag === 'green').length} healthy`}
    >
      {segments.map((s) => (
        <div
          key={s.name}
          title={`${s.name}: ${s.rag}`}
          className="flex-1 transition-opacity hover:opacity-75"
          style={{ backgroundColor: colors[s.rag] ?? '#6A6E73' }}
        />
      ))}
    </div>
  );
}

/**
 * Canonical relative-time formatting. Never crashes on null.
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
