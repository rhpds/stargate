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

### OpenShift Deployment

```bash
# Login to cluster
oc login --server=https://api.cluster.example.com:6443

# Deploy (builds images + helm install)
./scripts/deploy-infra01.sh --build
```

## Configuration

All configuration via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `STARGATE_DATABASE_URL` | PostgreSQL connection string | (required) |
| `STARGATE_LITELLM_API_KEY` | LiteLLM API key for AI features | (optional) |
| `STARGATE_LITELLM_URL` | LiteLLM endpoint URL | (optional) |
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

- Red Hat SSO (OpenShift OAuth proxy) protects all endpoints
- Admin API key authentication for programmatic access
- Per-endpoint rate limiting on all write/LLM operations
- SSL/TLS verification enabled by default
- Input validation on all command execution parameters
- Audit logging for all remediation actions
- NetworkPolicies for pod-to-pod isolation

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/deploy-infra01.sh` | Build and deploy to ocpv-infra01 |
| `scripts/refresh-kubeconfigs.sh` | Create long-lived SA tokens for cluster scanning |
| `scripts/test-auto-remediation.sh` | E2E auto-remediation test suite |

## Roadmap

### Ops Stability (Immediate)

- [ ] **Cluster scanner SA tokens** — Create `stargate-scanner` ServiceAccount with `cluster-reader` role and 1-year token on each cluster (ocpv05-09, infra02, ocp-us-east-1). Use `scripts/refresh-kubeconfigs.sh` per cluster. Currently using user OAuth tokens that expire daily.
- [ ] **Remove ocpv10** — DNS unreachable (`api.ocpv10.dal10.infra.demo.redhat.com`), likely decommissioned. Already removed from scanner config, verify no other references.

### Auto-Remediation (Short-Term)

- [ ] **E2E test with real lab** — Pick a low-risk lab, set to `low_risk_auto` via Admin > Auto-Remediation tab, trigger a known failure in `stargate-test`, verify detect → classify → recommend → execute → verify cycle works end-to-end. Run `scripts/test-auto-remediation.sh`.
- [ ] **Approval queue UX** — The approval queue stores and executes on approval, but the frontend `ApprovalQueue` component needs richer detail: show action parameters, risk level, evidence context, and execution result after approval.
- [ ] **Remediation effectiveness tracking** — When auto-remediation executes, measure: did the failure resolve? How long did recovery take? Build a dashboard view showing success rates by action type and failure class.

### CI/CD (Short-Term)

- [ ] **Automated builds** — Set up OpenShift BuildConfig or connect existing Tekton pipeline (`deploy/tekton/pipelines/stargate-ci.yaml`) to trigger on git push. Currently builds are manual from laptop via `podman build`.
- [ ] **Helm-first deployment** — Install helm, switch from ad-hoc `oc` commands to `helm upgrade --install` using the existing Helm chart (`deploy/helm/stargate/`). Chart already has full templates for API, scanner, frontend, postgres, OAuth, RBAC.
- [ ] **Environment promotion** — Add ArgoCD or Tekton deploy stages for dev → staging → production promotion.

### Intelligence (Medium-Term)

- [ ] **Close the feedback loop** — 625 LLM classification proposals are pending review. Wire the approval flow: ops reviews proposal → approved proposals become deterministic rules → rules run without LLM. Track accuracy over time.
- [ ] **Watch mode with alerting** — Add state-transition detection (PASS→FAIL) that triggers Slack/PagerDuty notifications. The event bus and nano-agent pipeline exist but no external notification consumers are wired.
- [ ] **Remediation learning** — Track which remediations succeed/fail. Automatically adjust confidence scores and promote proven remediations from `manual_approval` to `auto_execute`.

### Platform (Longer-Term)

- [ ] **Multi-tenant RBAC** — Add role-based access so team leads only see their labs. Currently all authenticated users see everything.
- [ ] **Prometheus metrics export** — Expose StarGate's own metrics (`/metrics`) for Grafana: API latency, scan cycle times, failure rates, remediation success %, LLM cost tracking.
- [ ] **AgnosticV webhook sync** — Currently cloned at startup. Set up a webhook or periodic git pull so new lab configs are picked up automatically.
- [ ] **Capacity planning dashboard** — Extend the forecast tab beyond 7-hour projections. Add weekly/monthly capacity trends, cluster growth modeling, and pool exhaustion prediction.

## License

Internal Red Hat use.
