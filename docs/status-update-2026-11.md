# StarGate Status Update — Failure Log Output & MCP (Nov 12 2026)

**Answers director question #2 (Nov 2026 review): "Enhancing log output after
failures (update from Juliano, Kersh, Victor) — did we make progress here?"**
plus current MCP adoption status. StarGate-side answer; AAP/bastion (Juliano)
and ops (Victor) updates come from their owners.

---

## 1. Enhancing log output after failures — yes, datable progress

**What failure-time output looks like now:**

| Capability | Since | Evidence |
|---|---|---|
| Every failed AAP job reduced to structured fields — failing task/play/role, normalized error (first failed event, `fatal:`/`FAILED!` preferred), bounded secret-sanitized evidence (64KB cap) | live collection, hardened Oct–Nov | 430k `source_events` |
| Failure logs outlive AAP's ~31-day retention — bastion ETL extracts replayed idempotently, historical timestamps preserved | Nov 2 (PRs #13–#16) | 14+ months partner-channel history durable; job-id dedupe fixed a real 42,850-record double count |
| Output is classified, not just stored — 111-class taxonomy, LLM proposals for the remainder, root-cause signature classes validated against documented incidents | ongoing; `json_decode_error` added Oct 30 | incident study: the exact Oct 21 SSO-5xx signature is now a named class |
| Investigation-time log collection with citations — read-only `oc logs`, redacted, assembled into causal chains instead of raw dumps | Nov (investigation agent) | causal-chain endpoint + MCP `get_causal_chain` |
| One root cause instead of N duplicate failures — fleet rollup with root-cause/remediation excerpts | Nov 10 (#25) | known-issues rollup live in production |
| Captured evidence no longer silently dropped — fixed random-ID collision bug (~1.6% of evidence lost; 56k items over 4 days) | Nov 10 (#27) | zero collisions since deploy |

**The honest gaps:**

- **Pre-flight failures produce no logs at all** (pre-flight exits before any
  AAP job runs — the Aug `environment_level` incident). Needs a Babylon-side
  event feed; team decision, on the roadmap.
- **Symptoms are captured better than causes.** Incident study (Oct 30):
  detection 4/4, root-cause attribution 0/4 — signature text present in 3 of 4
  but lacking taxonomy classes. The Cascade integration (in design review)
  targets exactly this.
- `showroom_not_ready` is 45% of failure volume — signal vs noise still
  ungoverned.
- **Alert wiring not connected** — the enhanced output emits events into a
  Slack consumer with no webhook configured. One env var.

## 2. MCP — first real usage observed; fixes shipping Friday

The agent surface (`/mcp`, 14 tools + natural-language `ask` over 351+ docs,
10 per-user keys, per-request audit with hashed key attribution):

- **First sustained external usage observed Nov 10–11**: an overnight agent
  caller (key_id `5d0ae4c9`) making tool calls nightly — found because its
  queries were hitting database timeouts. The adoption metric the roadmap
  tracks ("first MCP calls by the team") has its first data point.
- **The audit trail works** — verified by live reproduction Nov 11: every
  request logs method, tool, and hashed key id (this trail was silently dead
  until the Nov 3 fix).
- **Fixed this week, shipping Friday**: the two evaluation queries that timed
  out for the overnight caller (>30s → 2.7ms and 5.6ms with new indexes,
  measured on production data).
- **Known open**: `get_recent_changes` (change correlation) returns GitHub
  API errors — needs a GitHub token configured (config change, not code);
  occasional duplicate audit lines (cosmetic, attribution unaffected).

## 3. What ships Friday (Nov 14 release)

Data retention (bounds the 43GB database for the first time), the run-create
race fix, the MCP query-timeout fix, and the migration hardening — all
validated against production data in rolled-back transactions before merge.
