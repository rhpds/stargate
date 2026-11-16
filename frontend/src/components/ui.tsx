/**
 * Shared UI primitives — one definition site (frontend redesign Phase 2).
 * Visual pass: elevated cards with status accents, the RAG strip for
 * instant fleet reads, refined typography rhythm.
 */

import React from 'react';
import { Link } from 'react-router-dom';

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
  label,
}: {
  status: string;
  colors?: Record<string, string>;
  label?: string;
}) {
  const key = status?.toLowerCase?.() ?? '';
  const map = colors ?? STATUS_COLORS;
  const bg = map[key] ?? '#6A6E73';
  const isUnknown = key === 'unknown' || key === 'indeterminate';
  // dark-on-amber passes WCAG 4.5:1 where white-on-amber fails (~2:1)
  const fg = bg === '#F0AB00' ? '#151515' : '#fff';
  if (isUnknown) {
    return (
      <span className="text-xs font-semibold px-2 py-0.5 rounded-full w-fit border border-dashed border-[#6A6E73] text-[#8a8a8a]">
        ? {label ?? status}
      </span>
    );
  }
  return (
    <span
      className="text-xs font-semibold px-2 py-0.5 rounded-full w-fit"
      style={{ backgroundColor: bg, color: fg }}
    >
      {label ?? status}
    </span>
  );
}

/**
 * VerdictBanner — the page's answer, dominant. One per page, full width,
 * RAG tint + border + glyph + words (never color alone). The glance
 * grammar from the design brief: hue+size+position are preattentive;
 * the words confirm.
 */
export function VerdictBanner({
  state,
  headline,
  chips,
  meta,
  drillTo,
  drillLabel,
}: {
  state: 'green' | 'amber' | 'red' | 'unknown';
  headline: string;
  chips?: string[];
  meta?: string;
  drillTo?: string;
  drillLabel?: string;
}) {
  const conf = {
    green: { color: '#3E8635', glyph: '✓', shape: 'rounded-full' },
    amber: { color: '#F0AB00', glyph: '⚠', shape: '' },
    red: { color: '#EE0000', glyph: '✖', shape: '' },
    unknown: { color: '#6A6E73', glyph: '?', shape: 'border-dashed' },
  }[state];
  return (
    <div
      className={`w-full rounded-xl p-4 flex items-center gap-4 border-2 ${conf.shape}`}
      style={{
        backgroundColor: `${conf.color}22`,
        borderColor: conf.color,
      }}
      role="status"
      aria-label={headline}
    >
      <span
        className="shrink-0 w-10 h-10 rounded-full flex items-center justify-center text-lg font-bold"
        style={{ backgroundColor: conf.color, color: conf.color === '#F0AB00' ? '#151515' : '#fff' }}
        aria-hidden="true"
      >
        {conf.glyph}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-base font-bold text-white">{headline}</div>
        {chips && chips.length > 0 && (
          <div className="text-xs text-[#c7c7c7] mt-0.5 flex gap-3 flex-wrap">
            {chips.map((c) => <span key={c}>{c}</span>)}
          </div>
        )}
      </div>
      <div className="text-right shrink-0">
        {meta && <div className="text-xs text-[#8a8a8a]">{meta}</div>}
        {drillTo && (
          <Link to={drillTo} className="text-xs text-[#73BCF7] hover:underline">
            {drillLabel ?? 'drill in →'}
          </Link>
        )}
      </div>
    </div>
  );
}

/**
 * StateStrip — the generalized glance strip with the tri-state textures:
 * solid for observed states, diagonal HATCH for lower bounds ("at least"),
 * DASHED for unknown. Never color alone; never interpolate across gaps.
 *
 * `tooltip` upgrades hover from the browser's delayed title tooltip to an
 * immediate floating card below the strip, positioned under the hovered
 * cell — a plain positioned div, no library. Without it, cells keep their
 * title attributes for the simple embeds.
 */
export function StateStrip({
  cells,
  height = 'h-3',
  tooltip,
}: {
  cells: { state: 'green' | 'amber' | 'red' | 'floor' | 'unknown'; title?: string }[];
  height?: string;
  tooltip?: (index: number) => React.ReactNode;
}) {
  const solid = {
    green: '#3E8635',
    amber: '#F0AB00',
    red: '#EE0000',
  };
  const wrapRef = React.useRef<HTMLDivElement>(null);
  const [hover, setHover] = React.useState<{ index: number; left: number } | null>(null);

  const TOOLTIP_WIDTH = 224; // w-56 — keep in sync with the class on the card
  const onCellEnter = (i: number, e: React.MouseEvent<HTMLDivElement>) => {
    if (!tooltip) return;
    const wrap = wrapRef.current;
    if (!wrap) return;
    const cell = e.currentTarget;
    const center = cell.offsetLeft + cell.offsetWidth / 2;
    const maxLeft = Math.max(0, wrap.offsetWidth - TOOLTIP_WIDTH);
    setHover({ index: i, left: Math.min(Math.max(center - TOOLTIP_WIDTH / 2, 0), maxLeft) });
  };

  return (
    <div ref={wrapRef} className="relative"
      onMouseLeave={tooltip ? () => setHover(null) : undefined}>
      <div className={`flex ${height} rounded-full overflow-hidden gap-px`} role="img"
        aria-label={`Strip: ${cells.filter((c) => c.state === 'red').length} deficit, ${cells.filter((c) => c.state === 'floor').length} lower-bound, ${cells.filter((c) => c.state === 'unknown').length} unknown, ${cells.filter((c) => c.state === 'green').length} headroom`}>
        {cells.map((c, i) => {
          const onEnter = (e: React.MouseEvent<HTMLDivElement>) => onCellEnter(i, e);
          if (c.state === 'floor') {
            return (
              <div key={i} title={tooltip ? undefined : (c.title ?? 'at least (lower bound)')}
                onMouseEnter={onEnter} className="flex-1"
                style={{ background: 'repeating-linear-gradient(45deg, #F0AB00, #F0AB00 3px, #212121 3px, #212121 6px)' }} />
            );
          }
          if (c.state === 'unknown') {
            return <div key={i} title={tooltip ? undefined : (c.title ?? 'not measured')}
              onMouseEnter={onEnter} className="flex-1 border-y border-dashed border-[#6A6E73] bg-[#1a1a1a]" />;
          }
          return <div key={i} title={tooltip ? undefined : c.title} onMouseEnter={onEnter}
            className="flex-1" style={{ backgroundColor: solid[c.state] }} />;
        })}
      </div>
      {tooltip && hover && hover.index < cells.length && (
        <div role="tooltip"
          className="absolute top-full mt-1.5 w-56 z-20 bg-[#1a1a1a] border border-[#3a3a3a] rounded-lg shadow-xl p-3 pointer-events-none"
          style={{ left: hover.left }}>
          {tooltip(hover.index)}
        </div>
      )}
    </div>
  );
}

/**
 * LegendRow — the tri-state vocabulary, in words, next to what it explains.
 */
export function LegendRow() {
  return (
    <div className="flex gap-4 text-xs text-[#8a8a8a] flex-wrap">
      <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm inline-block" style={{ backgroundColor: '#3E8635' }} /> headroom (observed)</span>
      <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm inline-block" style={{ backgroundColor: '#EE0000' }} /> deficit</span>
      <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm inline-block" style={{ background: 'repeating-linear-gradient(45deg, #F0AB00, #F0AB00 2px, #212121 2px, #212121 4px)' }} /> at least (floor)</span>
      <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-sm inline-block border border-dashed border-[#6A6E73]" /> unknown</span>
    </div>
  );
}


/**
 * Parse an investigation's markdown analysis into sections — ported
 * verbatim from the old Operations page (the salvage manifest's item 1:
 * the parser is pure string logic, and the old page's biggest strength
 * was showing the full Diagnosis → Root Cause → Remediation chain).
 */
export function splitAnalysisSections(text: string) {
  const labels = [
    'Diagnosis', 'Root Cause', 'Remediation Strategy', 'Shadow Remediation',
    'Owner', 'Verdict', 'Confidence', 'Additional Recommendations',
  ];
  const headingPattern = (label: string) => new RegExp(
    `^(?:#{1,6}\\s*(?:\\d+\\.\\s*)?|\\*\\*)${label}(?:\\*\\*)?\\s*:?[ \\t]*(.*)$`,
    'im',
  );
  const extract = (label: string): string | null => {
    const match = headingPattern(label).exec(text);
    if (!match || match.index == null) return null;
    const bodyStart = match.index + match[0].length;
    const remainder = text.slice(bodyStart);
    let bodyEnd = remainder.length;
    for (const nextLabel of labels) {
      if (nextLabel === label) continue;
      const next = headingPattern(nextLabel).exec(remainder);
      if (next?.index != null) bodyEnd = Math.min(bodyEnd, next.index);
    }
    const inline = match[1]?.trim() || '';
    const body = remainder.slice(0, bodyEnd).trim();
    const content = [inline, body].filter(Boolean).join('\n\n');
    return content.length > 5 ? content : null;
  };
  const verdictMatch = text.match(/\*?\*?Verdict\*?\*?[:\s]*(TRANSIENT|ACTIONABLE|UNKNOWN)/i);
  return {
    diagnosis: extract('Diagnosis'),
    rootCause: extract('Root Cause'),
    shadowRemediation: extract('Shadow Remediation'),
    owner: extract('Owner'),
    remaining: extract('Remediation Strategy'),
    verdict: verdictMatch && verdictMatch[1] ? verdictMatch[1].toUpperCase() : null,
  };
}
