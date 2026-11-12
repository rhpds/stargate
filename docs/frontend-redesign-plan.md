# Frontend Redesign — Contracts, Data, UX

**Status: DRAFT for discussion — the thinking, not yet the build plan**
**Author: Nov 13 2026, grounded in the platform review's frontend findings
and the session's new surfaces (forecaster, known issues, events)**

Related: [reference-architecture.md](reference-architecture.md) §5.1,
[mcp-tool-cookbook.md](mcp-tool-cookbook.md) (the persona questions are
the same ones agents ask).

---

## 1. The problem, in numbers (from the review)

| Finding | Number | User cost |
|---|---|---|
| Pages | 18 files, 16 routed, 1 dead, **8 orphan routes** (URL-only, zero inbound links) | Nobody finds half the product |
| Shared UI primitives | **4** (MetricCard re-implemented ×14, SectionHeader ×12, STATUS_COLORS ×11) | Inconsistent; every change is 14 changes |
| Untyped API surface | **37** `request<any>` calls; ~130 `: any` in pages; `types.ts` hand-written 1,016 lines | Contract drift between API and UI is invisible until it 500s |
| Top-nav exposure | **4** of 16 routes | The overview is a scavenger hunt |
| Accessibility | Zero `aria-*`/`role`; clickable `<div>`s; emoji-only buttons | Unusable for part of the audience |
| Bundle | 530KB single chunk, no route splitting | Slow first paint everywhere |

The deeper issue is not any of these — it is that **the pages are
organized by data source, not by question**. A person asking "why did
lab X fail?" crosses Operations → Failures → Remediation →
Investigations, because those are the tables, not the answer.

## 2. The design principle: question-first

Every page answers **one primary question for one persona**, stated in
its header, and everything below it serves that answer. The personas
and their questions (the same ones the MCP cookbook documents for
agents — the frontend serves humans asking the same things):

| Persona | The 30-second question | The page that must answer it |
|---|---|---|
| **On-call ops** | "Is anything on fire right now?" | Overview — fleet RAG, saturation, known issues, budget |
| **Investigator** | "Why did lab X fail — and is it one bug or many?" | Lab detail → causal chain → known issue |
| **Manager / director** | "How are we doing, honestly?" | KPIs: detection, MTTR, adoption, coverage — with the incident-validation honesty |
| **Planner** | "Will the schedule fit the fleet?" | Capacity: event view (bounds), pool deficits, forecast authority state |
| **Approver** | "What needs my decision?" | The queue: pending actions, review diagnoses, adjudications |

## 3. The information architecture

```
Overview (RAG fleet state, 30s)
├── Labs          → lab list → lab detail (causal chain, evidence)
├── Clusters      → cluster detail (saturation, capacity, health)
├── Capacity      → events (RH1/Summit bounds) → pools → forecast
├── Investigations→ queue → detail (the workhorse triage flow)
├── Knowledge     → known issues → taxonomy → proof matrix
└── Admin         → config, keys, receipts (gated)
```

- **Kill the orphans**: every route either gains an inbound path or
  dies. The 8 URL-only routes merge into the tree above.
- **Progressive disclosure**: overview answers in headlines; every
  number drills to its evidence (a RAG badge opens the underlying
  evaluations; a forecast opens its citations; a known issue opens its
  representative causal chain). **Every number links to its evidence**
  — the platform's EDD philosophy, expressed as navigation.
- **Context preservation**: drill-downs keep the time-range and
  cluster filters (the TimeRangeContext already exists — make it
  universal).

## 4. API contracts — CDD for the frontend

The backend's newer surfaces (forecaster, deepfield, geolux, proof,
operations, lifecycle matrix...) return **raw dicts** — 37 untyped
client calls against them. The fix is contract-first, both directions:

1. **Response models on every endpoint** (Pydantic, like the core
   schemas) — the OpenAPI document becomes complete and true.
2. **Generate the TS types from OpenAPI** (`openapi-typescript`) —
   retire the hand-written 1,016-line `types.ts`; the drift class
   disappears structurally.
3. **Contract tests pin the shapes** (the existing
   `test_api_openapi_schema.py` pattern, extended to the dashboard
   routers) — a breaking API change fails CI, not the UI at runtime.
4. **The same contracts serve MCP and the frontend** — one definition
   site: the response models, the OpenAPI, the generated types, and
   the MCP tool outputs all derive from the same Pydantic schemas.

The forecaster surfaces define the pattern to follow: the
`capacity-forecast/v1` contract (tri-state, RAG, citations) IS the
response model — the UI renders the contract, not a shaped dict.

## 5. UX tightness rules (small, enforceable)

1. **One question per page**, stated in the header.
2. **RAG is consistent and labeled** — the same red/amber/green
   semantics everywhere (contract risk, saturation, budget, health),
   never color-only (icon + text).
3. **Universal states** — loading, error, empty on every query; the
   error states link to the API's own health surface.
4. **Advisory is visible** — forecaster surfaces badge their authority
   state (`advisory`) and their bounds (`cohort vs summed`) in plain
   words; the gate's verdict is one click away.
5. **No naked numbers** — every metric carries its window, its
   coverage, and its drill link.
6. **Keyboard and screen-reader baseline** — real buttons, labeled
   controls, table semantics. Not a rewrite; a discipline.

## 6. Build order (contracts before paint)

| Phase | Work | Size |
|---|---|---|
| 1 | Response models on the 37 untyped endpoints + OpenAPI-generated TS types + contract tests | the foundation; days |
| 2 | Shared primitives extracted (one MetricCard, one SectionHeader, one RAG badge, one EvidenceLink) | days; deletes ~10× duplication |
| 3 | The six-page tree above, one page at a time, starting with Overview and Capacity (the new surfaces deserve first-class UX) | per-page increments |
| 4 | Route-level code splitting, the nav, the a11y pass | polish |

## 7. What we are NOT doing

- No framework change (React 19 / Tailwind 4 stays).
- No big-bang rewrite — page-at-a-time, main stays shippable.
- No new design system — Tailwind primitives plus the six shared
  components above.
- The MCP surface is not redesigned — it inherits the contracts.
