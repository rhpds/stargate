# StarGate Production Reference Architecture — As Is

**Date: 2026-11-03. State: production deployment on infra01, namespace `stargate`.**
This documents what is actually running today, not what is planned. Items merged
to `main` but not yet released are marked **[Fri Nov 6]**.

---

## 1. Deployment topology

```
infra01 (api.ocpv-infra01.dal12.infra.demo.redhat.com:6443)
└── namespace: stargate
    ├── stargate-api          2× replicas, 2 containers each:
    │     ├── api             FastAPI (port 8090): dashboard API, integration
    │     │                   endpoints, MCP server (/mcp), event bus, all
    │     │                   background loops (in-process threads)
    │     └── oauth-proxy     Red Hat SSO for browser; /mcp exempt
    │                         (skip-auth-regex ^/mcp); dashboard API requires
    │                         OAuth session or port-forward
    ├── stargate-postgres     PostgreSQL 15 (320Gi class PVC, 108d uptime)
    ├── stargate-scheduler    cluster scanner scheduler (tiered scan cadence)
    ├── stargate-babylon-worker  Babylon control-plane collector
    ├── stargate-frontend     React 19 + Vite + Tailwind 4 dashboard (nginx)
    ├── stargate-api ImageStream + BuildConfig (builds from source dir)
    └── Secrets:
        ├── stargate-kubeconfigs        scanner SA kubeconfigs per cluster
        ├── stargate-aap-controllers    4 AAP controller credentials
        └── (env vars on deployment)    DB URL, API keys, LLM config
```

**Monitored clusters** (scanner SA, cluster-reader + port-forward role):

| Cluster | Role | Notes |
|---|---|---|
| ocpv03, ocpv06, ocpv07, ocpv08, ocpv09 | provisioning (CNV) | tiered scans; ocpv08 shows chronic elevated failures (documented) |
| ocpv04 | provisioning (London/lon3) | **not monitored** — token pending |
| infra01 | platform host | also scraped for control-plane state |

**Resource limits**: api 1 CPU / 2Gi per pod (2 pods). Known issue: CPU
saturation under heavy concurrent load (investigations + scans + MCP).

---

## 2. Data collection (inbound)

| Source | Cadence | Mechanism | Volume (current) |
|---|---|---|---|
| AAP controllers (prod0, prod1, event0, event1) | 75s cycle | REST polling → idempotent `source_events` | 84k+ live events since Oct 12 |
| AAP historical ETL archives | one-time replays | `cli/aap_replay` from bastion extracts (streaming, checkpointed, tar support) | 500k+ jobs replayed: partner 18k (14 mo), prod0 50k+192k archive (in progress), event0 70k (Feb→) |
| Cluster scanner | 5m nodes / 5m pods / 5m namespace batches (150/cycle) | `oc` via scanner SA kubeconfigs | 34k evaluations/day |
| Babylon control plane | 3m | worker → AnarchySubjects, ResourcePools, lab mappings | continuous |
| Labagator | 60s cache | REST | catalog + sessions |
| LLM gateway health | 15m | native LiteLLM `/health` (racmaas + primary) | 2.4k+ evaluations recorded |
| External dependencies (SSO, api.openshift.com, registry) | 5m | HTTP probes, 5xx = the Oct-21 signature | **[Fri Nov 6]** |
| Storage + OLM catalogs (Ceph ≥70%, stuck PVCs, stale snapshots) | 5m (Tier 1b) | `oc` reads per cluster | **[Fri Nov 6]** |
| Partner catalog visibility | on demand | registry + evaluations | **[Fri Nov 6]** |

**Ingestion invariants** (proven by the replay work): idempotent on
`(source_system, source_instance, source_event_id)` with secondary job-id
dedupe for replay-format records; historical timestamps preserved (`historical=True`);
outcome vocabulary normalized (failed→fail, error→fail, successful→pass).

---

## 3. Processing pipeline

```
source_events / scans
      │
      ▼
┌─ deterministic classification ─────────────────────────────┐
│  111-class taxonomy (failure-classes/*.yaml):              │
│  regex patterns, severity, team, remediation guidance      │
│  19 classes sourced from the team's Confluence RCA record  │
└──────────────┬─────────────────────────────────────────────┘
               ▼ (unclassified only)
┌─ LLM classifier ──────────────────────────────────────────┐
│  llama-scout-17b via LiteLLM (maas-rhdp)                   │
│  quality-gated proposals → proposed_classifications        │
│  650+ proposals; human review workflow built, unexercised  │
└──────────────┬─────────────────────────────────────────────┘
               ▼
┌─ rubric evaluation ───────────────────────────────────────┐
│  13 stages + storage-catalog-health [Fri]: cluster-health, │
│  namespace-ready, deployment-ready, ..., destroy-complete  │
│  tri-state evidence (observed/unobserved/indeterminate)    │
└──────────────┬─────────────────────────────────────────────┘
               ▼
┌─ investigation loop (auto, rate-limited) ─────────────────┐
│  Sonnet agent, 15 read-only tools, 12 iterations/480s      │
│  tools include: oc reads, change correlation (GitHub PRs   │
│  + Jira), saturation detection, knowledge search (RAG)     │
│  ~14-79/day; 83.5% produce root_cause with citations       │
└──────────────┬─────────────────────────────────────────────┘
               ▼
┌─ adjudication ────────────────────────────────────────────┐
│  granite blind reviewer (endpoint degraded — known issue)  │
│  verdicts: confirmed / needs_human_review / model_supported│
└──────────────┬─────────────────────────────────────────────┘
               ▼
┌─ action & remediation (human-gated) ──────────────────────┐
│  PendingActions → 5-gate executor → GeoLux pre-check →     │
│  human approval → execution → verification evals           │
│  NO auto-remediation on provisioning clusters (RBAC-       │
│  verified). 10.5k actions queued historically; 0 executed  │
│  (auto-resolve dominates — the honest state)               │
└───────────────────────────────────────────────────────────┘
```

**Background loops (in-process threads on stargate-api):**

| Loop | Interval | Function |
|---|---|---|
| MV refresh | 60s | materialized views, scanner health |
| Shadow mode | 5m | failure tracking without execution |
| Babylon collection | 3m | control-plane state |
| Corpus mining | 30m | failure knowledge base |
| Investigation queue | continuous (rate-limited) | claims source_events, diagnoses |
| LLM health | 15m | model endpoint monitoring |
| Dependency health | 5m | **[Fri Nov 6]** |
| Storage/OLM | 5m (with Tier 1) | **[Fri Nov 6]** |

---

## 4. Storage

**PostgreSQL (`stargate` database)** — 5.15M+ evaluations, 174k+ source_events:

| Table | Contents | Count |
|---|---|---|
| `evaluations` | every stage pass/fail/warn per workload | 5.15M+ |
| `source_events` | idempotent AAP events (live + replayed history) | 174k+ |
| `investigations` | Sonnet agent diagnoses with evidence | 2k+ |
| `proposed_classifications` | quality-gated LLM class proposals | 650+ |
| `pending_actions` | remediation queue (awaiting human) | 10.5k |
| `resolution_records` | fail→pass transitions with cause | 1.3k+ |
| `knowledge_entries` | reviewed diagnoses (versioned) | **0** — review workflow unexercised |
| `investigation_source_events` | claim links | — |
| `adjudications` | blind-review verdicts | — |
| `lab_mappings` | canonical lab identity (103k rows) | 103k |
| `event_log` | bus events | continuous |
| `remediations` | executed remediations | **0** |
| Pool snapshots, scan snapshots, receipts | monitoring state | rotating |

**Knowledge corpus (filesystem)**: 351 documents — 111-class taxonomy,
team Confluence RCA record (43 files), workflows, architecture, runbook,
incident validation study. Serves the `ask` MCP tool (qwen3-14b synthesis,
3-tier retrieval).

---

## 5. Serving surfaces

### 5.1 Dashboard + API

- **Frontend**: React 19 dashboard (clusters, labs, investigations, actions,
  proof matrix, capacity, causal chains)
- **Key API endpoints**: `/dashboard/saturation`, `/dashboard/change-correlation`,
  `/dashboard/llm-health`, `/dashboard/causal-chain`, `/dashboard/mttr`,
  `/dashboard/partner-visibility` **[Fri]**, `/dashboard/dependency-health` **[Fri]**
- Auth: OAuth (browser) or `X-API-Key`; 10 per-user keys (Billy, John, Or,
  Victor, Patrick, J, Shrey, Panos, Tony, Perry), each audit-attributed via
  hashed key_id

### 5.2 MCP server (the agent surface)

| Property | Value |
|---|---|
| Endpoint | `https://stargate-api.apps.ocpv-infra01.../mcp` (stateless HTTP) |
| Tools | 13 (11 query + 2 review) + `ask` RAG |
| Auth | per-user API keys; rate limit 60/min/key |
| Audit | `mcp request: method tool key_id` per request (fixed Nov 3 — was silently dead) |
| Usage | 1 client handshake observed Nov 3; **0 tool calls to date** |

### 5.3 Event bus (in-process)

Consumers: LogConsumer, WebhookConsumer, DeepFieldConsumer (stage events out;
incident push-back in), GeoLuxConsumer (governance), InvestigationConsumer.
**SlackConsumer exists but is unwired — no webhook configured.** Alerts
currently reach nobody (the known operational gap).

### 5.4 Confluence mirror

12-page tree in the RHPDS space; idempotent sync via
`scripts/confluence_sync.py` (label-based change detection, runs post-release).

---

## 6. External integrations

| System | Direction | Purpose | State |
|---|---|---|---|
| maas-rhdp LiteLLM | outbound | classification (llama-scout), ask (qwen3-14b), investigations (claude-sonnet), adjudication (granite — **degraded**) | live |
| racmaas LiteLLM | outbound (monitor) | model endpoint health checks | live |
| GitHub API | outbound | change correlation (PRs), AgnosticV clone | live |
| Jira (redhat.atlassian.net) | outbound | change correlation (tickets) | live |
| Confluence | outbound | doc mirror sync | live |
| GeoLux | outbound | remediation governance pre-checks | live |
| DeepField | bidirectional | stage events out / incidents in | thin (stage-level only) |
| AAP bastions (ETL archives) | outbound (SSH, 2 keys) | historical replay sources | on demand |
| Kafka (ecosystem) | — | **dead 4.5 months**, no app references it | decommission candidate |

---

## 7. Security model

- **Remediation**: 5 independent gates (namespace allowlist, execution mode,
  risk, rate, confidence) + GeoLux + human approval. Scanner SAs are
  read-only (verified via live RBAC probes).
- **MCP**: read + review only; no execution, no cluster access through MCP.
- **API keys**: constant-time comparison, per-key rate limit, hashed audit
  attribution.
- **oc command validation**: `_validate_k8s_name()` allowlist; read-only verbs
  enforced for agent tools.
- **Known debt**: DeepField's plaintext DB credentials in its deployment spec
  (not StarGate's, but in-ecosystem); stargate-api CPU saturation under load.

---

## 8. Operational state (honest)

| Metric | Value |
|---|---|
| Evaluations processed | 5.15M+ total; ~34k/day live |
| Investigation quality | 83.5% root-cause rate |
| Classification coverage | 3.8% unclassified (was 45% Oct 14 week) |
| Incident validation | 4/4 documented incidents detected on correct dates |
| Knowledge entries | 0 — the review workflow awaits first use |
| MCP usage | 1 handshake, 0 tool calls |
| Alerting | **nonexistent** — monitors emit to an unwired consumer |
| Release cadence | Fridays (PRs merge any day; deploys Friday-only) |

---

## 9. Change process

- **PRs only** to `main` (no direct commits); user reviews and merges
- **Friday releases**: build + rollout from `main` only on Fridays unless an
  out-of-band hotfix is approved
- **Config changes** (API keys, env vars, RBAC) are not releases — `oc set env`
  any day
- Post-release: `scripts/confluence_sync.py` refreshes the doc mirror

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full working rules.
