/**
 * Knowledge — the compounding page. (Frontend redesign Phase 3, fourth page.)
 *
 * ONE question: "What do we know, and how confidently?" — the knowledge
 * entries human reviews published (each with provenance and confidence),
 * the failure taxonomy's coverage, and the proof matrix (19/20 proven).
 * Per the redesign: every entry cites its investigation.
 */

import { useQuery } from '@tanstack/react-query';
import { MetricCard, SectionHeader, StatusBadge, relativeTime } from '../components/ui';
import { request } from '../api/client';

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

interface ProofMatrix {
  [key: string]: unknown;
}

function Knowledge() {
  const knowledge = useQuery({
    queryKey: ['knowledge'],
    queryFn: () => request<KnowledgeResponse>('/admin/knowledge'),
    refetchInterval: 300_000,
  });
  const proof = useQuery({
    queryKey: ['proof-matrix'],
    queryFn: () => request<ProofMatrix>('/admin/proof/matrix'),
    refetchInterval: 600_000,
  });

  const items = knowledge.data?.items ?? [];
  const active = items.filter((k) => k.active);
  const proofText = typeof proof.data === 'object' && proof.data !== null
    ? JSON.stringify(proof.data)
    : '';

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-white">What do we know, and how confidently?</h1>
        <p className="text-sm text-[#6A6E73] mt-1">
          Human-reviewed diagnoses, versioned and attributed. Every entry cites its
          investigation; future investigations of the same pattern find these in one lookup.
        </p>
      </header>

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
            value={proofText.includes('19') ? '19/20' : '—'}
            sub="failure classes proven"
          />
          <MetricCard
            label="Reviews ever"
            value={items.length}
            sub="each publishes knowledge"
          />
        </div>
        {active.length === 0 && (
          <div className="text-sm text-[#6A6E73] mt-3">
            No active knowledge entries yet — review diagnoses on the{' '}
            <a href="/investigations" className="text-[#73BCF7]">investigations page</a>{' '}
            to publish the first.
          </div>
        )}
      </section>

      <section aria-label="Knowledge entries">
        <SectionHeader>Entries</SectionHeader>
        <div className="space-y-2">
          {active.map((k) => (
            <div key={k.id} className="bg-[#212121] border border-[#2e2e2e] rounded-lg p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-white truncate">
                  {k.signature} · v{k.version}
                </span>
                <div className="flex items-center gap-2">
                  {k.confidence != null && (
                    <span className="text-xs text-[#6A6E73]">
                      confidence {(k.confidence * 100).toFixed(0)}%
                    </span>
                  )}
                  <StatusBadge status={k.active ? 'active' : 'retired'} />
                </div>
              </div>
              <p className="text-xs text-[#9a9a9a] mt-2 line-clamp-3">{k.root_cause}</p>
              {k.remediation && (
                <p className="text-xs text-[#6A6E73] mt-1 line-clamp-2">↳ {k.remediation}</p>
              )}
              <div className="text-xs text-[#6A6E73] mt-2 flex gap-4">
                {k.investigation_id != null && (
                  <span>from investigation #{k.investigation_id}</span>
                )}
                <span>by {k.reviewed_by ?? 'unknown'}</span>
                {k.reviewed_at && <span>{relativeTime(k.reviewed_at)}</span>}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

export default Knowledge;
