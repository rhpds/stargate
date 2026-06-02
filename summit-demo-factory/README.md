# StarGate — Demo Validation Control Plane

Control plane for provisioning, validating, observing, and improving demo environments. Part of the **Launchpad + StarGate** platform — two products that integrate via webhook events.

Built on Red Hat native tooling: UBI container images, Podman, OpenShift-ready.

## Role in the Platform

```
                    +-------------------+
                    +--------+----------+
                             |
                  monitors clusters that
                  Launchpad provisions on
                             |
+------------------+    +----v----------------+
|  StarGate (you)  |    |     Launchpad       |   PROVISIONING + DEMOS
| Rubric evaluator |<-->| 17-state lifecycle  |
| Evidence bundles |    | Inference gateway   |
| Failure classes  |    | Workshop batching   |
+------------------+    +---------------------+
```

- **Launchpad** provisions demo environments and pushes lifecycle events to StarGate
- **StarGate** evaluates those events against YAML rubrics and classifies failures
- Each product deploys independently; integration is optional via env vars

## Quick Start

```bash
# Install (tests only, no PostgreSQL driver needed)
pip install -e ".[dev]"

# Install (full API with PostgreSQL)
pip install -e ".[dev,api]"

# Run all tests (uses in-memory storage, no external deps)
python3 -m pytest tests/ -v

# Start the API (in-memory mode, no database required)
cd api && uvicorn app.main:app --port 8080

# Start with PostgreSQL
DATABASE_URL=postgresql://user:pass@localhost:5432/stargate \
  cd api && uvicorn app.main:app --port 8080
```

The API runs at `http://localhost:8080`. Swagger docs at `http://localhost:8080/docs`.
Health check at `http://localhost:8080/health`.

## API Endpoints

All API routes are under `/api/v1/`.

### Runs
- `POST /api/v1/runs` — create a demo run
- `GET /api/v1/runs/{run_id}` — get run details
- `GET /api/v1/runs` — list runs

### Stages
- `POST /api/v1/runs/{run_id}/stages/{stage_id}/start` — start a stage
- `POST /api/v1/runs/{run_id}/stages/{stage_id}/evidence` — submit evidence
- `POST /api/v1/runs/{run_id}/stages/{stage_id}/evaluate` — evaluate stage against rubric
- `POST /api/v1/runs/{run_id}/stages/{stage_id}/complete` — complete a stage

### Rubrics
- `POST /api/v1/rubrics/validate` — validate a rubric definition
- `GET /api/v1/rubrics/{stage_id}` — get a rubric
- `POST /api/v1/rubrics/{stage_id}/evaluate` — evaluate evidence against a rubric

### Reports
- `GET /api/v1/runs/{run_id}/report` — full run report
- `GET /api/v1/runs/{run_id}/bottlenecks` — timing bottlenecks

### AI Proposals
- `POST /api/v1/runs/{run_id}/proposals/summary` — failure summary with hypothesis
- `POST /api/v1/runs/{run_id}/proposals/rubric-diffs` — proposed rubric rule changes
- `POST /api/v1/runs/{run_id}/proposals/pr-text` — complete PR text from proposals

### Integration
- `POST /integration/events` — receive lifecycle events from Launchpad
- `GET /integration/evaluate` — pre-flight check for Launchpad provisioning

### Health
- `GET /health` — `{"status": "ok", "service": "stargate"}`

## Integration

StarGate integrates with Launchpad via webhook push. All integrations fail silently when targets are not configured.

| Direction | What | Endpoint |
|-----------|------|----------|
| Launchpad → StarGate | Lifecycle events (session provisioned, failed, reclaimed) | `POST /integration/events` |
| Launchpad → StarGate | Pre-flight check before provisioning | `GET /integration/evaluate` |
| StarGate → Launchpad | Cleanup results after remediation | `POST {LAUNCHPAD_API_URL}/callbacks/cleanup-result` |

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | No | PostgreSQL connection string. Falls back to in-memory storage if not set. |
| `LAUNCHPAD_API_URL` | No | Launchpad base URL for pushing cleanup results. |
| `LAUNCHPAD_API_KEY` | No | API key for Launchpad authentication. |

## Tech Stack

- **Python** >=3.11, **FastAPI** >=0.115, **Pydantic** >=2.10
- **Database:** asyncpg + PostgreSQL (with in-memory fallback)
- **HTTP client:** httpx >=0.28 (outbound webhooks)
- **Container:** UBI9 base image, Podman
- **Deployment:** Kustomize + AgnosticV/AgnosticD + OpenShift

## Project Structure

```
summit-demo-factory/
  api/
    app/
      api/                # FastAPI routers (runs, stages, rubrics, reports, proposals, integration)
      integrations/       # Outbound event publisher (Launchpad)
      models.py           # Pydantic domain models
      database.py         # asyncpg pool + in-memory fallback
      repository.py       # Data access layer
      rubric_evaluator.py # Deterministic pass/fail/warn evaluation
      rubric_loader.py    # YAML rubric loading
      ai/                 # AI proposal modules (failure summarizer, rubric proposer, PR generator)
    migrations/           # Numbered SQL migration files
  rubrics/platform/       # Platform readiness rubrics (YAML)
  collectors/             # Evidence collectors (Anarchy, Showroom, cluster-scheduler)
  tests/                  # All tests (45 passing)
  deploy/
    base/                 # Kustomize base manifests
    overlays/dev/         # Dev overlay
    openshift/            # Legacy raw YAML (deprecated)
  agnosticv-catalog/      # AgnosticV catalog entries (common/dev/prod)
  agnosticd-config/       # Ansible deployment playbooks
  Containerfile           # UBI9-based API image
  podman-compose.yml      # Local dev with Podman
```

## Design Rules

- No stage promotes because a command completed — only when evidence satisfies the rubric.
- No feature graduates because it was coded — only when tests pass.
- AI is not part of the first execution path. Deterministic rubrics catch 80%+.
- Containers use Red Hat UBI base images.
- All integrations fail open — StarGate works standalone without Launchpad.
