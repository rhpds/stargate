# StarGate — Milestone 2 Summary

**Date**: 2026-05-07

## What's Built

| Stage | Status | Tests | Description |
|---|---|---|---|
| Stage 0 | Complete | 235 | Core engine — rubric evaluator, collectors, normalizers, proposals |
| Stage 1 | Complete | +27 | PostgreSQL persistence, FastAPI service, podman-compose |
| Stage 2 | Complete | +16 | Live collection from 10 clusters, CLI tools |
| Stage 3 | Complete | +21 | Evidence bundles with history, AgnosticV constraint classification |
| Stage 4 | Complete | +18 | Event bus, 4 nanoagents (Filter/Correlate/Triage/Impact), Slack/webhook consumers |
| **Total** | | **317 tests** | |

## What's Running

- **PostgreSQL** on podman (port 5433) — 750+ runs persisted
- **StarGate API** on podman (port 8090) — full REST API with events
- **Scheduler** with 10 workers — 9 cluster workers + 1 Babylon control plane worker
- **Tiered scanning** — Tier 1 (nodes/5min), Tier 2 (pod delta/15min), Tier 3 (namespace evidence/1hr)
- **Staggered execution** — 30-second offsets between cluster scans
- **Delta detection** — tracks new failures and recoveries between scans
- **Event pipeline** — every evaluation flows through Filter → Correlate → Triage → Impact

## Data Collected

| Source | Records | Clusters |
|---|---|---|
| Namespace evidence runs | 750+ | 8 lab + 2 infra |
| AnarchySubjects | 2,923 | ocp-us-east-1 |
| ResourcePools | 164 | ocp-us-east-1 |
| ResourceHandles | 2,308 | ocp-us-east-1 |
| ResourceClaims | 2,273 | ocp-us-east-1 |
| CatalogItems | 535 | ocp-us-east-1 |
| Workshops | 155 | ocp-us-east-1 |
| AgnosticV constraints | 54 Summit labs | Local repo |

## API Endpoints

| Endpoint | Purpose |
|---|---|
| `POST /runs` | Create validation run |
| `POST /runs/{id}/evidence` | Submit evidence |
| `POST /runs/{id}/evaluate` | Evaluate against rubrics → emits event |
| `GET /runs/{id}/report` | Full run report |
| `GET /runs/{id}/bundle` | Evidence bundle with history + constraints |
| `GET /labs/{lab_code}/history` | Evaluation history for a lab |
| `GET /labs/{lab_code}/failures` | Failure class frequency |
| `GET /clusters/{name}/summary` | Cluster health aggregate |
| `GET /clusters/{name}/failures` | Cluster failure distribution |
| `GET /events` | Query recent events |
| `GET /events/summary` | Event pipeline metrics |
| `POST /events/consumers` | Register webhook consumer |
| `GET /constraints/{lab_id}` | AgnosticV constraints for a lab |
| `GET /constraints` | All Summit 2026 lab constraints |

## Findings from Live Scans

### Platform Health
- 10 clusters scanned, ~4,200 sandbox namespaces, ~2,800 active labs
- **98.6% lab health rate** platform-wide
- **Monitoring blind on all clusters** — ccm-monitoring push failing everywhere
- **27,000+ Ceph cleanup error pods** accumulating across all lab clusters
- **CPU saturation root cause identified**: nested OCP control-plane VMs consuming 6-18 cores each, no concurrency gate

### Summit 2026 Provisioning
- 147 Summit subjects, 84 started, **49 failed (33.3% failure rate)**
- 164 pools, 101 low capacity
- AI Lightning labs near 100% failure rate

### DNS Root Cause Analysis
- DNS probe failures traced to specific nodes at 90-100% CPU
- Direct correlation: nodes with >50 VMs/node → DNS probes timeout → intermittent resolution failures
- Threshold: 30 VMs/node = healthy, >50 = saturating
- **ocpv09 proof**: 248 labs, 40 nodes, 24.5 VMs/node, 0 DNS failures

## What's Needed for Stage 5

### Demolition Integration
- **Need**: `DEMOLITION_INTEGRATION_API_KEY` value
- **URL**: `https://demolition.apps.cluster.example.com`
- **Available endpoints**: `GET/POST /integration/sessions`, `POST /integration/sessions/{id}/trigger`, `GET /integration/sessions/{id}/status`
- **Missing**: Callback endpoint — Demolition doesn't POST results back to StarGate

### Labagator Integration
- **Need**: Service account in `rhdp-labagator-writers` group, or API key endpoint added to Labagator
- **URL**: `https://labagator-api.apps.cluster.example.com/api`
- **Available endpoints**: `GET /ops/dashboard/{event_id}`, `POST /ops/room-sessions/{id}/transition`, `GET /labs/`, `GET /room-sessions/`
- **Auth**: OAuth proxy with OpenShift group-based RBAC
- **Missing**: StarGate config, validation result ingest endpoint

### Both Systems
- Both APIs are reachable from external network (no VPN needed)
- Both run on `ocpv-infra01` — StarGate should deploy there for internal service network access
- Read access works now. Write access (triggering runs, updating ops status) needs auth coordination.

## Deployment Readiness

StarGate is ready to deploy on `ocpv-infra01` alongside Demolition and Labagator:
- Containerfile builds on UBI9
- podman-compose tested locally (PostgreSQL + API)
- Same deployment pattern as Demolition/Labagator (FastAPI + PostgreSQL + Ansible playbook)
- Scheduler runs as a sidecar process

## Next Steps

1. **Get Demolition API key** from the team
2. **Get Labagator write access** (service account or API key endpoint)
3. **Deploy StarGate to ocpv-infra01** — Ansible playbook matching existing pattern
4. **Wire Demolition callback** — small PR to POST results back after run completion
5. **Wire Labagator ops status update** — small PR to add validation result endpoint
6. **HITL feedback** — Slack interactive messages for proposal review
7. **LLM integration** — Claude via Vertex AI for unclassified failures with full evidence bundle
