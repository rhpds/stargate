/**
 * Knowledge — the compounding page. (Frontend redesign Phase 3, fourth page.)
 *
 * ONE question: "What do we know, and how confidently?" — the knowledge
 * entries human reviews published (each with provenance and confidence),
 * live proof-matrix coverage (X of Y failure classes proven), and the
 * shadow-mode strip. Per the redesign: every entry cites its investigation,
 * and rows lead with meaning (root cause) over identity (signature).
 */

import { useQuery } from '@tanstack/react-query';
import { MetricCard, SectionHeader, StatusBadge, relativeTime } from '../components/ui';
import { request } from '../api/client';
import { Link } from 'react-router-dom';

interface KnowledgeItem {
  id: number;
  signature: string;
  version: number;
  active: boolean;
  root_cause: string;
  remediation: string | null;
  confidence: number | null;
  investigation_id: number | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  acceptance_count?: number;
}

interface KnowledgeResponse {
  items: KnowledgeItem[];
}

/**
 * One failure class in GET /admin/proof/matrix. `gate` is the accumulated
 * proof state; `status` only reflects the cycle currently in flight (it
 * resets when the next cycle starts), so gate is what counts as proven.
 */
interface ProofClassEntry {
  status?: string;
  proof_type?: string;
  gate?: string;
  cycles_completed?: number;
  cycles_failed?: number;
  consecutive_passes?: number;
  last_run?: string | null;
  proven_ever?: boolean;
}

interface ProofMatrixResponse {
  matrix?: {
    failure_classes?: Record<string, ProofClassEntry>;
    updated_at?: string;
  };
  summary?: {
    total?: number;
    proven?: number;
    passed_not_proven?: number;
    failed?: number;
  };
}

/** GET /admin/shadow/status — shadow-mode tracking rollup. */
interface ShadowStatus {
  status?: string;
  last_run?: string | null;
  total_entries?: number;
  resolved?: number;
  unresolved?: number;
}

/**
 * Lead with meaning: the first sentence of the root cause becomes the row
 * title (max ~80 chars); whatever follows it stays as the body, so nothing
 * is lost and nothing is shown twice.
 */
function summarizeRootCause(text: string | null | undefined): { title: string; body: string } {
  const clean = (text || '').replace(/\s+/g, ' ').trim();
  if (!clean) return { title: '', body: '' };
  const sentence = clean.match(/^(.*?[.!?])\s+/);
  const first = sentence?.[1] ?? clean;
  if (first.length <= 80) {
    return { title: first, body: clean.slice(first.length).trim() };
  }
  // First sentence is too long for one line: cut at a word boundary near 80
  // chars and keep the full text as the body (the "…" marks the truncation).
  const head = clean.slice(0, 80);
  const cut = head.lastIndexOf(' ');
  const idx = cut > 40 ? cut : 80;
  return { title: head.slice(0, idx).trimEnd() + '…', body: clean };
}

function Knowledge() {
  const knowledge = useQuery({
    queryKey: ['knowledge'],
    queryFn: () => request<KnowledgeResponse>('/admin/functional/knowledge'),
    refetchInterval: 300_000,
  });
  const proof = useQuery({
    queryKey: ['proof-matrix'],
    queryFn: () => request<ProofMatrixResponse>('/admin/proof/matrix'),
    refetchInterval: 600_000,
  });
  const shadow = useQuery({
    queryKey: ['shadow-status'],
    queryFn: () => request<ShadowStatus>('/admin/shadow/status'),
    refetchInterval: 30_000,
  });

  const items = knowledge.data?.items ?? [];
  const active = items.filter((k) => k.active);

  // Real proof counts from the matrix entries. Proven = accumulated gate,
  // mirroring ProofTracker.get_summary on the backend: full_auto /
  // investigation_proven met the consecutive-pass threshold (low_risk_auto
  // has at least one pass but is not proven yet).
  const proofClasses = Object.entries(proof.data?.matrix?.failure_classes ?? {});
  const isProven = (fc: ProofClassEntry) =>
    fc.gate === 'full_auto' || fc.gate === 'investigation_proven';
  const provenCount = proofClasses.filter(([, fc]) => isProven(fc)).length;
  const unprovenNames = proofClasses
    .filter(([, fc]) => !isProven(fc))
    .map(([name]) => name)
    .sort();

  const shadowActive = shadow.data?.status === 'running';
  const shadowLabel = shadowActive
    ? 'active'
    : shadow.data?.status === 'not_started'
      ? 'not started'
      : 'inactive';

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-white">What do we know, and how confidently?</h1>
        <p className="text-sm text-[#6A6E73] mt-1">
          Human-reviewed diagnoses, versioned and attributed. Every entry cites its
          investigation; future investigations of the same pattern find these in one lookup.
        </p>
      </header>

      {/* Shadow strip — one live line from the shadow tracker. */}
      {shadow.data && shadow.data.status !== 'error' && (
        <div className="bg-[#1a1a1a] border border-[#2e2e2e] rounded-lg px-4 py-2.5 flex flex-wrap items-center gap-2 text-xs">
          <span className="text-[#6A6E73] font-bold uppercase tracking-wider">Shadow mode</span>
          <span
            className={`px-2 py-0.5 rounded-full font-semibold ${
              shadowActive ? 'bg-[#3E8635]/20 text-[#3E8635]' : 'bg-[#2e2e2e] text-[#8a8a8a]'
            }`}
          >
            {shadowLabel}
          </span>
          <span className="px-2 py-0.5 rounded-full bg-[#212121] border border-[#2e2e2e] text-[#C9C9C9]">
            <span className="font-bold text-white tabular-nums">{shadow.data.total_entries ?? 0}</span> failures tracked
          </span>
          <span className="px-2 py-0.5 rounded-full bg-[#212121] border border-[#2e2e2e] text-[#C9C9C9]">
            <span className="font-bold text-white tabular-nums">{shadow.data.resolved ?? 0}</span> resolved
          </span>
          {shadow.data.last_run && (
            <span className="px-2 py-0.5 rounded-full bg-[#212121] border border-[#2e2e2e] text-[#6A6E73]">
              last run {relativeTime(shadow.data.last_run)}
            </span>
          )}
        </div>
      )}

      {knowledge.error && (
        <div className="bg-[#2e2e2e] border border-[#EE0000]/40 rounded-lg p-4 text-sm text-white">
          Failed to load knowledge: {String(knowledge.error)}
        </div>
      )}
      {knowledge.isLoading && !knowledge.data && (
        <div className="text-sm text-[#6A6E73]">Loading knowledge base…</div>
      )}

      <section aria-label="Knowledge summary">
        <SectionHeader right="approve = publish; reject = re-examine">
          Knowledge base
        </SectionHeader>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <MetricCard label="Active entries" value={active.length} sub="human-reviewed" />
          <MetricCard label="Total versions" value={items.length} sub="including retired" />
          <MetricCard
            label="Proof lab"
            value={proofClasses.length > 0 ? `${provenCount}/${proofClasses.length}` : '—'}
            sub="failure classes proven"
          />
          <MetricCard
            label="Reviews ever"
            value={items.length}
            sub="each publishes knowledge"
          />
        </div>

        {/* Proof coverage — one segment per failure class: green = proven,
            gray dashed = unproven. Counts come from the same entries. */}
        {proofClasses.length > 0 && (
          <div className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4 mt-4">
            <div className="flex items-baseline justify-between gap-2 flex-wrap">
              <span className="text-sm font-semibold text-white">
                {provenCount} of {proofClasses.length} failure classes proven
              </span>
              <span className="text-xs text-[#6A6E73]">{unprovenNames.length} unproven</span>
            </div>
            <div
              className="flex h-2 rounded-full overflow-hidden gap-px mt-3"
              role="img"
              aria-label={`Proof coverage: ${provenCount} of ${proofClasses.length} failure classes proven`}
            >
              {proofClasses.map(([name, fc]) => {
                const proven = isProven(fc);
                return (
                  <div
                    key={name}
                    className={
                      proven
                        ? 'flex-1'
                        : 'flex-1 border border-dashed border-[#6A6E73] bg-[#1a1a1a]'
                    }
                    title={
                      proven
                        ? `${name}: proven (${fc.gate})`
                        : `${name}: unproven — ${fc.status ?? 'UNTESTED'} (gate ${fc.gate ?? 'manual'})`
                    }
                    style={proven ? { backgroundColor: '#3E8635' } : undefined}
                  />
                );
              })}
            </div>
            {unprovenNames.length > 0 && (
              <div className="text-xs text-[#8a8a8a] mt-2">
                <span className="text-[#6A6E73]">Unproven: </span>
                {unprovenNames.join(' · ')}
              </div>
            )}
          </div>
        )}

        {active.length === 0 && (
          <div className="text-sm text-[#6A6E73] mt-3">
            No active knowledge entries yet — review diagnoses on the{' '}
            <Link to="/investigations" className="text-[#73BCF7]">investigations page</Link>{' '}
            to publish the first.
          </div>
        )}
      </section>

      <section aria-label="Knowledge entries">
        <SectionHeader>Entries</SectionHeader>
        <div className="space-y-2">
          {active.map((k) => {
            const { title, body } = summarizeRootCause(k.root_cause);
            const confPct =
              k.confidence != null
                ? Math.round(Math.max(0, Math.min(1, k.confidence)) * 100)
                : null;
            return (
              <div key={k.id} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    {title && (
                      <div className="text-sm font-semibold text-white leading-snug">
                        {title}
                      </div>
                    )}
                    <div className="text-xs font-mono text-[#6A6E73] mt-0.5 truncate">
                      {k.signature} · v{k.version}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {confPct != null && (
                      <span
                        className="flex items-center gap-1.5"
                        title={`confidence ${confPct}%`}
                      >
                        <span
                          className="block w-14 h-1.5 rounded-full bg-[#2e2e2e] overflow-hidden"
                          aria-hidden="true"
                        >
                          <span
                            className="block h-full rounded-full"
                            style={{ width: `${confPct}%`, backgroundColor: '#73BCF7' }}
                          />
                        </span>
                        <span className="text-xs text-[#6A6E73] tabular-nums">{confPct}%</span>
                      </span>
                    )}
                    <StatusBadge status={k.active ? 'active' : 'retired'} />
                  </div>
                </div>
                {body && (
                  <p className="text-xs text-[#9a9a9a] mt-2 line-clamp-3">{body}</p>
                )}
                {k.remediation && (
                  <p className="text-xs text-[#6A6E73] mt-1 line-clamp-2">↳ {k.remediation}</p>
                )}
                <div className="text-xs text-[#6A6E73] mt-2 flex gap-4">
                  {k.investigation_id != null && (
                    <span>
                      from{' '}
                      <Link to="/investigations" className="text-[#73BCF7] hover:underline">
                        investigation #{k.investigation_id}
                      </Link>
                    </span>
                  )}
                  <span>by {k.reviewed_by ?? 'unknown'}</span>
                  {k.reviewed_at && <span>{relativeTime(k.reviewed_at)}</span>}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

export default Knowledge;
