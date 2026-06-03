# StarGate Platform

Continuous operations platform for Red Hat Demo Platform (RHDP) — monitors, evaluates, and remediates lab/demo environments across multiple OpenShift clusters.

## What It Does

StarGate provides a unified dashboard for managing the lifecycle of provisioned labs, demos, and workshops:

- **Cluster Scanning** — Monitors 8+ OpenShift clusters for node health, pod failures, VM status, and namespace readiness on a tiered schedule (5m/15m/1h)
- **Rubric Evaluation** — Evaluates each lab namespace against a pipeline of readiness rubrics (cluster-health, namespace-ready, deployment-ready, VM-runtime, showroom-healthy, etc.)
- **AI Classification** — Unclassified failures are sent to an LLM (Granite 3.2 8B via LiteLLM) for automated failure class proposals
- **Auto-Remediation** — Per-lab execution mode (recommend-only, low-risk-auto, full-auto) with risk-filtered catalog actions, rate limiting, and audit logging
- **Provisioning Intelligence** — Aggregates data from Babylon (AnarchySubjects, ResourcePools), Labagator (session schedule), AAP (provisioning jobs), Demolition (smoke tests), and AgnosticV (deployment constraints)
- **Capacity Forecasting** — Projects resource demand based on upcoming session schedules

## Architecture

```
Frontend (React + PatternFly 6)
    |
    OAuth Proxy (Red Hat SSO)
    |
    FastAPI (Python 3.9)
    |
    +-- Scanner Workers (per-cluster, tiered schedule)
    +-- Babylon Worker (control plane collector)
    +-- LLM Integration (Granite via LiteLLM)
    +-- Policy Engine (deterministic recommendations)
    +-- Remediation Executor (gated, audited)
    |
    PostgreSQL 15
```

## Quick Start

### Prerequisites

- Python 3.9+
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
| `STARGATE_LLM_MODEL` | LLM model name | `granite-3-2-8b-instruct` |
| `STARGATE_ADMIN_API_KEY` | Admin API authentication key | (required for API key auth) |
| `STARGATE_SSL_VERIFY` | Verify TLS certificates | `true` |
| `STARGATE_AGNOSTICV_TOKEN` | GitHub token for AgnosticV repo | (optional) |
| `STARGATE_EVENT_PREFIX` | Filter to event-specific pools (e.g., `summit-2026`) | (empty = continuous ops) |
| `STARGATE_EXECUTION_TARGET` | Remediation target: `mock`, `test`, `production` | `mock` |

## Data Sources

| Source | What | How |
|--------|------|-----|
| Labagator | Lab catalog, session schedule, attendee counts | REST API |
| Babylon | ResourcePools, AnarchySubjects, CatalogItems | `oc` CLI via kubeconfigs |
| AAP | Provisioning job status, failure analysis | REST API (event0, event1 controllers) |
| Demolition | Smoke test results per lab | REST API |
| AgnosticV | Lab deployment constraints, cloud config | Git clone |
| Sandbox API | Rate limits, queue depth, DB health | Prometheus metrics scrape |
| Cluster Scanner | Node metrics, pod health, namespace evidence | `oc` CLI via kubeconfigs |

## Project Structure

```
api/                    FastAPI application and routers
cli/                    Scanner scheduler and worker processes
collectors/             Data source collectors (AAP, Babylon, Demolition, etc.)
constraints/            AgnosticV constraint loading and classification
db/                     SQLAlchemy models and repository
deploy/                 Helm charts, Tekton pipelines, OpenShift manifests
engine/                 Core logic: rubric evaluation, policy, remediation, LLM
events/                 Event bus and nano-agent pipeline
frontend/               React + PatternFly 6 dashboard
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

## Remediation Architecture

StarGate uses a **two-tier execution model** that respects the RHDP ecosystem:

**Tier 1 — Kubernetes-native (direct execution, safe):**
Pod restarts, deployment rollouts, health checks, log collection. These are idempotent Kubernetes operations that don't conflict with RHDP controllers.

**Tier 2 — RHDP-managed (routed through RHDP APIs):**
AnarchySubject lifecycle (retry/destroy via Anarchy), pool scaling (via Poolboy), namespace management (via Sandbox API), workload re-provisioning (via AgnosticD/ArgoCD). These go through RHDP controllers to maintain state consistency and audit trails.

Each catalog entry declares its `execution_method` (`kubernetes`, `rhdp_anarchy`, `rhdp_sandbox_api`, `rhdp_poolboy`) so the action executor routes to the correct API. A pre-flight check prevents remediation during active provisioning.

## Roadmap

### Ops Stability (Immediate)

- [ ] **Cluster scanner SA tokens** — Create `stargate-scanner` SA with `cluster-reader` role and 1-year token on each cluster. Use `scripts/refresh-kubeconfigs.sh`.
- [x] ~~Remove ocpv10~~ — Done. DNS unreachable, removed from scanner config.

### RHDP Integration (Current Sprint)

- [x] **RHDP-aware execution router** — Action executor routes RHDP-managed actions through `engine/rhdp_client.py` (Anarchy, Poolboy, Sandbox API) instead of raw `oc` commands.
- [x] **Pre-flight checks** — Skip remediation when AnarchySubject is mid-provision (`provisioning`, `starting` states).
- [x] **Catalog execution_method** — Each remediation entry declares whether it's Kubernetes-native or RHDP-managed.
- [ ] **E2E test with Launchpad labs** — Deploy labs via Launchpad, enable `low_risk_auto` in StarGate, inject failures, verify RHDP-routed remediation works end-to-end.
- [ ] **Approval queue UX** — Show action parameters, risk level, execution method (Kubernetes vs RHDP), and result after approval.

### RHDP Deployment Pipeline (Short-Term)

- [x] **AgnosticV Catalog Item** — StarGate packaged as a proper CI with dev/integration/prod stages.
- [x] **Git-SHA image tagging** — `scripts/build-and-tag.sh` produces reproducible tagged images.
- [ ] **AgnosticD role** — Create Ansible role `stargate_deploy` wrapping Helm install for RHDP pipeline.
- [ ] **Devel deployment** — Deploy StarGate dev CI on CNV cluster via AgnosticV/Babylon.
- [ ] **Integration gate** — Test on staging cluster before promoting to prod.
- [ ] **CI review with Ashok/Tony** — Get CI structure reviewed and approved for the pipeline.

### Intelligence (Medium-Term)

- [ ] **Close the feedback loop** — Review pending LLM proposals, promote accurate ones to deterministic rules.
- [ ] **Watch mode with alerting** — PASS→FAIL state transitions trigger Slack/PagerDuty via event bus consumers.
- [ ] **Remediation effectiveness tracking** — Measure success rates by action type. Auto-promote proven remediations from `manual_approval` to `auto_execute`.

### Platform (Longer-Term)

- [ ] **Multi-tenant RBAC** — Team leads see only their labs.
- [ ] **Prometheus /metrics** — API latency, scan cycles, failure rates, remediation success %, LLM cost.
- [ ] **AgnosticV webhook sync** — Auto-detect new lab configs without restart.
- [ ] **Capacity planning** — Weekly/monthly trends, pool exhaustion prediction.

## License

Internal Red Hat use.
