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

## License

Internal Red Hat use.
