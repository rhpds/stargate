# StarGate Platform

Continuous operations platform for Red Hat Demo Platform (RHDP) — monitors, evaluates, and remediates lab/demo environments across multiple OpenShift clusters.

## What It Does

StarGate provides a unified dashboard for managing the lifecycle of provisioned labs, demos, and workshops:

- **Cluster Scanning** — Monitors 8+ OpenShift clusters for node health, pod failures, VM status, and namespace readiness on a tiered schedule (5m/15m/1h)
- **Rubric Evaluation** — Evaluates each lab namespace against a pipeline of readiness rubrics (cluster-health, namespace-ready, deployment-ready, VM-runtime, showroom-healthy, storage-catalog-health, etc.)
- **AI Classification** — Unclassified failures are sent to a qualified LLM (llama-scout-17b via LiteLLM, 91.7% on the frozen qualification set) for automated failure class proposals
- **Durable Investigations** — Idempotent source events are claimed, diagnosed, reviewed, and linked to every failure covered by a representative investigation
- **Control-Plane Monitoring** — Babylon WorkshopProvision conditions distinguish failed or stalled provisions from successful empty results and collection failures; all 4 AAP controllers (prod + event) are collected
- **Outcome Contracts** — `provisioning-outcome/v1` and `reclamation-outcome/v1`: explicit, evidence-verified lifecycle outcomes with tri-state evidence semantics (observed/unobserved/indeterminate)
- **Causal Chains** — `GET /dashboard/causal-chain`: symptom → evidence → diagnosis → adjudication → action → remediation → verification eval, with `missing_legs` reporting what is not yet proven
- **MCP Server** — 15 tools (13 query + 2 review) + natural-language `ask` (RAG over 351+ documents, including the team's Confluence RCA record) at `/mcp`; any MCP-compatible agent can query the platform in plain English; see [docs/stargate-mcp-agent-guide.md](docs/stargate-mcp-agent-guide.md)
- **Change Correlation** — RHDP has no formal change management, so StarGate is the change record: GitHub PRs (merged + in review) and Jira tickets correlated against failure onset, path-matched to each lab's AgnosticV files; the investigation agent checks it before calling any failure novel
- **Saturation Correlation** — Detects the capacity-saturation signature (rate spike vs the cluster's own baseline + diverse symptom classes + labs failing here while passing elsewhere); validated against the documented Oct 13-14 2026 ocpv08 incident
- **Platform Health Monitoring** — Four loops watching what the platform depends on: LLM gateway model endpoints (native LiteLLM /health, 15m), external dependencies (SSO/api.openshift.com/registry — the Oct 21 5xx lesson, 5m), storage headroom + OLM catalog freshness (Ceph at 70%, stuck PVCs, stale snapshots, 5m), and saturation correlation. All persist as evaluations so degradation is a trend
- **Partner Catalog Visibility** — The breakdown the biweekly report lacks: registered partner items with documented baselines, current failure rates, and delta-vs-baseline
- **Incident Validation** — Retrospective accuracy audits against documented incidents: detection 4/4 on Confluence-documented incidents, attribution gaps quantified honestly (see `docs/incident-validation-2026-10.md`)
- **GeoLux Governance** — Pre-approval constraint checks (safe/unsafe/unknown) on investigation-sourced remediation actions; GeoLux advises, the human decides, the gated executor acts
- **Auto-Remediation** — Per-lab execution mode (recommend-only, low-risk-auto, full-auto) with risk-filtered catalog actions, rate limiting, and audit logging; no auto-remediation on provisioning clusters (verified via live RBAC probes)
- **Provisioning Intelligence** — Aggregates data from Babylon (AnarchySubjects, ResourcePools), Labagator (session schedule), AAP (provisioning jobs from all 4 controllers), Demolition (smoke tests), and AgnosticV (deployment constraints)
- **Capacity Forecasting** — Projects resource demand based on upcoming session schedules

## Architecture

```
Frontend (React 19 + Vite + Tailwind 4)
    |
    OAuth Proxy (Red Hat SSO)
    |
    FastAPI (Python 3.11)
    |
    +-- Scanner Workers (per-cluster, tiered schedule)
    +-- Babylon Worker (control plane collector)
    +-- AAP Collector (4 controllers: prod0, prod1, event0, event1)
    +-- LLM Integration (llama-scout for classify, qwen3-14b for ask, Sonnet for investigations)
    +-- Platform Health Loops (LLM gateways 15m, external deps 5m, storage/OLM 5m)
    +-- Change Correlation (GitHub PRs + Jira vs failure onset)
    +-- Policy Engine (deterministic recommendations)
    +-- GeoLux Governance (pre-approval constraint checks)
    +-- Remediation Executor (gated, audited)
    +-- MCP Server (15 tools + natural-language ask, at /mcp)
    +-- Causal Chain (symptom → evidence → diagnosis → remedy → proof)
    |
    PostgreSQL 15
```

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 22+
- PostgreSQL 15
- `oc` CLI (for cluster scanning)

### Local Development

```bash
# Start PostgreSQL
podman-compose up -d postgres

# Set environment
export STARGATE_DATABASE_URL=postgresql://stargate:changeme@localhost:5432/stargate

# Install Python deps
pip install -e .

# Start API
uvicorn api.app:app --host 0.0.0.0 --port 8090 --reload

# Start frontend (separate terminal)
cd frontend && npm ci && npm run dev
```

### OpenShift Deployment (RHDP Pipeline)

StarGate is packaged as an AgnosticV Catalog Item and deployed through the standard RHDP pipeline:

```
deploy/agnosticv/stargate-platform/
├── common.yaml        # Base CI definition
├── dev.yaml           # CNV clusters, mock execution
├── integration.yaml   # Staging, real scanners (3 clusters)
└── prod.yaml          # Production, all scanners + collectors
```

**Build and tag images:**
```bash
./scripts/build-and-tag.sh --push
```

**Manual deploy (ad-hoc, for development only):**
```bash
oc login --server=https://api.cluster.example.com:6443
./scripts/deploy-infra01.sh --build
```

## Configuration

All configuration via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `STARGATE_DATABASE_URL` | PostgreSQL connection string | (required) |
| `STARGATE_LITELLM_API_KEY` | LiteLLM API key for AI features | (optional) |
| `STARGATE_LITELLM_URL` | LiteLLM endpoint URL | (required for AI features) |
| `STARGATE_LABAGATOR_URL` | Labagator API base URL | (required for lab data) |
| `STARGATE_DEMOLITION_URL` | Demolition API base URL | (required for smoke tests) |
| `STARGATE_DASHBOARD_URL` | Public dashboard URL (for Slack notifications) | (optional) |
| `STARGATE_LLM_MODEL` | LLM model name | `llama-scout-17b` |
| `STARGATE_ADMIN_API_KEY` | Admin API authentication key | (required for API key auth) |
| `STARGATE_SSL_VERIFY` | Verify TLS certificates | `true` |
| `STARGATE_AGNOSTICV_TOKEN` | GitHub token for AgnosticV repo | (optional) |
| `STARGATE_EVENT_PREFIX` | Filter to event-specific pools (e.g., `summit-2026`) | (empty = continuous ops) |
| `STARGATE_EXECUTION_TARGET` | Remediation target: `mock`, `test`, `production` | `mock` |

The complete configuration reference, including investigation budgets, retention,
WorkshopProvision collection, and functional-alignment feature gates, is in
[docs/configuration.md](docs/configuration.md).

## Data Sources

| Source | What | How |
|--------|------|-----|
| Labagator | Lab catalog, session schedule, attendee counts | REST API |
| Babylon | ResourcePools, AnarchySubjects, CatalogItems | `oc` CLI via kubeconfigs |
| AAP | Provisioning job status, failure analysis | REST API (all 4 controllers: prod0, prod1, event0, event1) |
| AAP ETL archive | Historical job failures beyond API retention (14+ months) | Replay engine (`cli/aap_replay.py`) from bastion extracts — idempotent, historical timestamps preserved |
| Demolition | Smoke test results per lab | REST API |
| AgnosticV | Lab deployment constraints, cloud config | Git clone |
| Sandbox API | Rate limits, queue depth, DB health | Prometheus metrics scrape |
| Cluster Scanner | Node metrics, pod health, namespace evidence | `oc` CLI via kubeconfigs |

## Project Structure

```
api/                    FastAPI application and routers (incl. MCP server)
cli/                    Scanner scheduler, worker processes, AAP replay engine
collectors/             Data source collectors (AAP, Babylon, Demolition, etc.)
config/                 Maintained config (partner catalog registry)
constraints/            AgnosticV constraint loading and classification
contracts/              Outcome contracts (provisioning-outcome/v1, reclamation-outcome/v1)
db/                     SQLAlchemy models and repository
deploy/                 Helm charts, Tekton pipelines, OpenShift manifests
engine/                 Core logic: rubric evaluation, policy, remediation, LLM
events/                 Event bus and nano-agent pipeline
failure-classes/        Failure taxonomy (111 classes, YAML — 19 sourced from the team's Confluence RCA record)
frontend/               React 19 + Vite + Tailwind 4 dashboard
normalizers/            Data normalization across sources
prompts/                LLM prompt templates (YAML)
proposals/              AI proposal models and rubric proposer
remediations/           Remediation action catalog (YAML)
rubrics/                Readiness evaluation rubrics (YAML)
scripts/                Deployment and operations scripts
tests/                  Test suite
```

## Security

- **Authentication**: Red Hat SSO (OpenShift OAuth proxy) for browser access; API key (`X-API-Key` header) for programmatic access. Read-only admin endpoints accept same-origin browser requests; mutating endpoints (execute, approve, config changes) require API key or proxy auth.
- **Proxy auth**: When `STARGATE_TRUST_PROXY_AUTH=true`, the `x-forwarded-user` header from the OAuth proxy grants admin access.
- **Rate limiting**: Per-endpoint limits on all write and LLM operations via slowapi.
- **TLS verification**: Controlled by `STARGATE_SSL_VERIFY` env var across all outbound connections (collectors, LLM, Prometheus, AlertManager).
- **Input validation**: All `oc` command parameters validated via `_validate_k8s_name()` regex allowlist. Unrecognized command patterns are rejected. LLM prompt inputs are sanitized (control chars stripped, truncated, XML-bounded).
- **SSRF protection**: Webhook consumer URLs are resolved and checked against private/reserved IP ranges. AAP pagination validates hostname matches origin.
- **Execution gates**: Five independent gates before any remediation: namespace allowlist, lab execution mode, risk assessment, rate limiting, confidence threshold. All actions audit-logged.
- **Credential hygiene**: GitHub PAT uses temporary credential files (not env vars). No hardcoded passwords in source. Secrets directory gitignored. `.dockerignore` excludes `.env`, `*.key`, `*.pem`, `*.token`.
- **Container security**: Non-root container user, directory permissions 775 (not 777).

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/build-and-tag.sh` | Build images with git-SHA tags for reproducible deploys |
| `scripts/deploy.sh` | Build, push, and deploy to infra01 (`--build-only`, `--deploy-only`, `--sync-env`) |
| `scripts/deploy-infra01.sh` | Full Helm-based deploy with secrets and OAuth setup |
| `scripts/refresh-kubeconfigs.sh` | Create long-lived SA tokens for cluster scanning |
| `scripts/test-auto-remediation.sh` | E2E auto-remediation test suite |
| `scripts/confluence_sync.py` | Mirror docs to the Confluence page tree (idempotent, label-based change detection; run post-release) |

## Remediation Architecture

StarGate uses a **two-tier execution model** that respects the RHDP ecosystem:

**Tier 1 — Kubernetes-native (direct execution, safe):**
Pod restarts, deployment rollouts, health checks, log collection. These are idempotent Kubernetes operations that don't conflict with RHDP controllers.

**Tier 2 — RHDP-managed (routed through RHDP APIs):**
AnarchySubject lifecycle (retry/destroy via Anarchy), pool scaling (via Poolboy), namespace management (via Sandbox API), workload re-provisioning (via AgnosticD/ArgoCD). These go through RHDP controllers to maintain state consistency and audit trails.

Each catalog entry declares its `execution_method` (`kubernetes`, `rhdp_anarchy`, `rhdp_sandbox_api`, `rhdp_poolboy`) so the action executor routes to the correct API. A pre-flight check prevents remediation during active provisioning.


### Outcome Contracts (Shipped)

- **provisioning-outcome/v1** — explicit, evidence-verified provisioning outcomes (succeeded / failed / stalled / controller_lag / collection_unavailable / indeterminate)
- **reclamation-outcome/v1** — reclamation outcomes (reclaimed / destroy_failed / destroy_stalled / resource_leak / indeterminate) with artifact enumeration
- **Causal chains** — `GET /dashboard/causal-chain` assembles the full evidence chain per investigation with `missing_legs` honesty
- **MCP server** — 15 tools (13 query + 2 review) + natural-language `ask` (RAG, qwen3-14b, sub-3s) at `/mcp`; see [docs/stargate-mcp-agent-guide.md](docs/stargate-mcp-agent-guide.md)
- **Change correlation** — GitHub PRs + Jira tickets vs failure onset: `GET /dashboard/change-correlation`; RHDP has no formal change management, so this is the change record
- **Saturation correlation** — `GET /dashboard/saturation`: rate spike + diverse symptoms + lab differential, validated on the documented Oct 13-14 2026 incident
- **Platform health** — `GET /dashboard/llm-health`, `/dashboard/dependency-health`, `/dashboard/partner-visibility`: the dependencies and channels nobody was watching
- **GeoLux governance** — pre-approval constraint checks on remediation actions
- **Platform workflows** — step-through event flow diagrams in [docs/workflows.md](docs/workflows.md)
- **Proof lab** — 19/20 failure classes proven (13 remediation-proof, 6 detection-proof); gates decay on failure

## MCP Access

Anyone with an MCP-compatible agent (Claude, Cursor, etc.) can query the
platform in plain English:

```json
{
  "mcpServers": {
    "stargate": {
      "url": "https://stargate-api.apps.ocpv-infra01.dal12.infra.demo.redhat.com/mcp",
      "headers": { "X-API-Key": "YOUR-KEY" }
    }
  }
}
```

See [docs/stargate-mcp-agent-guide.md](docs/stargate-mcp-agent-guide.md) for
the full guide, and [docs/mcp-tool-cookbook.md](docs/mcp-tool-cookbook.md)
for per-tool examples — what to ask, what each tool returns.

## Roadmap

### Done (Oct–Nov 2026)

- [x] **Scanner SA tokens** — `stargate-scanner` SA + kubeconfigs on ocpv03/06/07/08/09 (ocpv04 pending cluster/token).
- [x] **Outcome contracts** — `provisioning-outcome/v1`, `reclamation-outcome/v1` with tri-state evidence.
- [x] **Incident validation** — retrospective accuracy audits against documented incidents: detection 4/4, attribution gaps quantified honestly (`docs/incident-validation-2026-10.md`).
- [x] **Saturation correlation** — rate-spike + symptom-diversity + lab-differential detector, validated on the documented Oct 13-14 ocpv08 incident.
- [x] **Change correlation** — GitHub PRs (merged + in review) and Jira tickets vs failure onset. RHDP has no formal change management; this is the change record.
- [x] **Platform health monitoring** — LLM gateway endpoints (15m), external dependencies (SSO/api/registry, 5m), storage headroom + OLM catalog freshness (5m), all persisted as evaluations.
- [x] **Partner catalog visibility** — the breakdown the biweekly report lacked, with documented baselines.
- [x] **MCP server** — 14 tools at `/mcp`, any AI agent, plain English, cited answers.
- [x] **Known-issues fleet rollup** — MCP `get_known_issues` + dashboard endpoint: groups investigations sharing one root cause into platform / platform-self / lab-family buckets.
- [x] **Knowledge corpus** — 351 documents including the team's Confluence RCA record and the incident validation study.
- [x] **Confluence mirror** — 12-page tree with idempotent sync (`scripts/confluence_sync.py`).
- [x] **AAP replay engine** — historical ETL archives into the platform, idempotent, historical timestamps preserved; partner channel (14 months) replayed.
- [x] **Evidence pipeline integrity** — fixed the silent ~1.6% evidence loss to random-ID collisions (56k dropped items) and the dead run-create race; both TDD'd and verified live.
- [x] **Data retention** — run-detail cascade (90d), GeoLux streams (60d), DB size budget with warn events; the previously unbounded 43GB database now drains.
- [x] **Revived snapshot persistence** — `scan_snapshots` sat empty (no DB URL, silent `except: pass`, no driver in the scanner image); all three fixed, history accumulating.
- [x] **Advisory capacity forecaster** — resource profiles from AgnosticV specs, per-hour demand projection, `capacity-forecast/v1` contract (tri-state, RAG, advisory by construction), fleet supply from observed peak density, per-pool demand join with roadshow-cohort semantics, event-grouped demand (the Summit/RH1-scale view: cohort and summed bounds, peak concurrent from real session times), and the **authority gate** — which refused promotion on its first real evaluation (false greens), flagged the documented event-pool exhaustion with 34 days of knowable lead time on its second, and now reads PASS/eligible under the evidence-based scope declaration: demand-shock authority to the forecaster, supply-degradation to the saturation detector (`docs/capacity-forecaster-plan.md`).
- [x] **Cascade Phase 0 backtest** — 2×2 engine matrix (both corpora × proof/OSS): hard gate PASS six times, compression 46.8–84.7%, the pin question answered empirically (`docs/cascade-backtest-2026-11.md`).

### Current

- [ ] **Adoption** — the remaining features ARE usage: first MCP calls by the team, first `review_diagnosis` (publishes the first knowledge entry), first classification reviews. Eight API keys distributed.
- [ ] **Alert wiring** — `SlackConsumer` exists but no webhook is configured; monitors emit events nobody receives. One env var.
- [ ] **Replay the remaining controllers** — prod0 in progress; event0 next; prod1/event1 behind bastion auth. Includes the deeper `archive/` directories (19GB on prod0 alone).
- [ ] **Partner controller in live collection** — the replay exposed that the partner AAP is not among the 4 live-collected controllers.
- [ ] **Value metrics endpoint** — detection lead time, coverage trend, investigation quality, action precision; computable from existing data.

### Medium-Term

- [ ] **Close the feedback loop** — review pending LLM proposals (614+), promote accurate ones to deterministic rules.
- [ ] **Remediation effectiveness tracking** — measure success rates by action type; auto-promote proven remediations.
- [ ] **Pre-flight event feed** — pre-flight failures (no AAP job) are invisible by construction; needs a Babylon-side feed (team decision).
- [ ] **Devel deployment via AgnosticV** — AgnosticD role + pipeline stages for dev/integration before prod.

### Longer-Term

- [ ] **Multi-tenant RBAC** — team leads see only their labs.
- [ ] **Prometheus /metrics expansion** — API latency, scan cycles, remediation success %, LLM cost.
- [ ] **AgnosticV webhook sync** — auto-detect new lab configs without restart.

Working rules live in [CONTRIBUTING.md](CONTRIBUTING.md): PRs only, Friday releases.

## License

Internal Red Hat use.
