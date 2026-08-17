# StarGate

Continuous operations platform for Red Hat Demo Platform (RHDP). Monitors, evaluates, and remediates lab/demo environments across 8+ OpenShift clusters using rubric-based readiness scoring and AI-powered failure classification (Granite 3.2 8B via LiteLLM).

## Quick Start

```bash
# Backend
pip install -e ".[dev,api]"
export STARGATE_DATABASE_URL=postgresql://stargate:changeme@localhost:5432/stargate
uvicorn api.app:app --host 0.0.0.0 --port 8090 --reload

# Frontend (port 3000, proxies API to :8090)
cd frontend && npm ci && npm run dev

# Full stack
podman-compose up -d
```

## Testing

```bash
make test                # Unit tests (SQLite in-memory, no Postgres needed)
make test-all            # All tests including integration
make test-integration    # Requires PostgreSQL
make test-cov            # Coverage report
cd frontend && npm test  # Frontend tests (vitest + jsdom)
```

Unit tests use in-memory SQLite via conftest.py (StaticPool, overrides `get_db`). Auth header: `X-API-Key: test-key-for-ci`.

## File Structure

| Directory | Purpose |
|-----------|---------|
| `api/` | FastAPI app, routers (admin, capacity, dashboard, health, integration, runs), schemas, LLM client, action executor |
| `cli/` | Scanner scheduler, scan worker, Babylon worker, replay tools |
| `collectors/` | Data source collectors: AAP, Babylon, Demolition, Labagator, OpenShift, Poolboy, Sandbox API, Showroom, Tekton, Zerotouch |
| `db/` | SQLAlchemy 2.0 models (20+ tables), database setup, repository layer |
| `engine/` | Core logic (46 modules): rubric evaluation, policy engine, remediation, LLM quality eval, capacity projector |
| `events/` | In-process event bus, consumers, nanoagent pipeline |
| `frontend/` | React 19 + TypeScript + Tailwind 4 + Vite dashboard (18 pages) |
| `prompts/` | LLM prompt templates (9 YAML files) |
| `rubrics/` | Readiness evaluation rubrics (build, platform, remediation-proof, etc.) |
| `deploy/` | Helm charts, Tekton pipelines, AgnosticV catalog items |
| `tests/` | 104 test files |

## Architecture

```
Frontend (React 19 / Vite / Tailwind 4)
  -> Vite proxy (dev) / nginx (prod)
  -> FastAPI (port 8090)
     +-- Scanner Workers (tiered schedule: 5m/15m/1h per cluster)
     +-- Babylon Worker (control plane collector)
     +-- LLM (Granite via LiteLLM, prompts in YAML)
     +-- Policy Engine (deterministic recommendations)
     +-- Remediation Executor (5 independent gates before action)
     +-- Event Bus + Nanoagent Pipeline
  -> PostgreSQL 15 (SQLAlchemy + Alembic)
```

## Key Conventions

- Config via `STARGATE_*` env vars (see `.env.example`)
- Python 3.9+, Pydantic v2, FastAPI, SQLAlchemy 2.0 with Alembic migrations
- Frontend: React 19, Tailwind 4 (not PatternFly), TanStack React Query, React Router 7
- API key auth (`X-API-Key` header) + OAuth proxy support
- Remediation: two-tier (K8s-native direct vs RHDP-managed via Anarchy/Poolboy)
- LLM prompts are YAML templates under `prompts/`
- Pre-commit: gitleaks for secret scanning
- Container: multi-stage Containerfile (Node 22 Alpine frontend + UBI9 Python 3.11 backend)
