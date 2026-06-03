# StarGate Platform Architecture

## Overview

StarGate is a centralized validation layer for the Red Hat Demo Platform (RHDP).
It continuously collects evidence from live OpenShift clusters, evaluates that
evidence against YAML-defined rubrics, classifies failures, generates
provisioning recommendations via a policy engine, and surfaces the results
through a React dashboard and REST API. An LLM (Granite 3.2 8B on Intel Gaudi,
routed through LiteLLM) provides failure classification and executive summaries
when deterministic rules are insufficient.

The system monitors 6 scanner clusters from a deployment on ocpv-infra01 and
integrates with the Babylon control plane (Poolboy, Anarchy, AgnosticV),
Labagator, and Demolition to produce a unified view of lab readiness.

---

## Component Diagram

```
                          +--------------------------+
                          |      React Frontend      |
                          |    (Vite / PatternFly)   |
                          +------------+-------------+
                                       |
                                       | HTTP
                                       v
+------------------+          +--------+--------+         +-----------------+
|   LLM Service    | <------> |   FastAPI API   | <-----> |   PostgreSQL    |
| Granite 3.2 8B   |  REST    |   (api/app.py)  |  SQL    |   (15, 20Gi)    |
|  via LiteLLM     |          +--+-----------+--+         +-----------------+
+------------------+             |           |
                                 |           |
              +------------------+           +------------------+
              |                                                 |
              v                                                 v
   +----------+-----------+                       +-------------+----------+
   |   Scanner Scheduler  |                       |   Babylon Worker       |
   |  (cli/scheduler.py)  |                       |  (cli/babylon_worker)  |
   +---+--+--+--+--+--+---+                       +------------------------+
       |  |  |  |  |  |                                      |
       v  v  v  v  v  v                                      v
   +------+ +------+ +------+                   +------------+----------+
   |ocpv05| |ocpv07| |ocpv08|  ...              | ocp-us-east-1         |
   |ocpv09| |infra | |infra |                   | (Babylon ctrl plane)  |
   |      | |  01  | |  02  |                   | Poolboy / Anarchy     |
   +------+ +------+ +------+                   +-----------------------+
       |                                                     |
       v                                                     v
  +---------+     +------------+     +----------+     +-------------+
  | Rubric  |     |  Policy    |     | Event    |     | Labagator / |
  | Engine  |     |  Engine    |     |   Bus    |     | Demolition  |
  |(engine/)|     |(engine/    |     |(events/) |     | (external)  |
  |         |     | policy.py) |     |          |     +-------------+
  +---------+     +------------+     +----------+

              +-------------------------------------------+
              |     Synthetic Client Emulator             |
              |  (stargate-synthetic-client-emulator/)    |
              |  7 scenarios, feedback loop, substrate    |
              +-------------------------------------------+

              +-------------------------------------------+
              |     Mock Cluster                          |
              |  (stargate-mock-cluster/)                 |
              |  Phase B command validation               |
              +-------------------------------------------+
```

---

## Data Flow

### 1. Evidence Collection

Scanners run on a tiered schedule against each cluster via `oc` commands:

| Tier | Interval | What                              | API calls |
|------|----------|-----------------------------------|-----------|
| 1    | 5 min    | Node metrics (`oc adm top nodes`) | 1         |
| 2    | 5 min    | Pod delta scan (`oc get pods -A`) | 1         |
| 3    | 5 min    | Namespace evidence (rotated batch) | 10+       |

Workers stagger by 30 seconds so they never hit the API server simultaneously.
Tier 3 rotates through sandbox namespaces in batches (default 150), prioritizing
failing namespaces. For each namespace, the worker collects: namespace, pods,
services, endpoints, routes, deployments, VMs, VMIs, DataVolumes, PVCs, and
showroom HTTP health.

The Babylon worker runs every 3 minutes and collects: ResourcePool capacity
(Poolboy), AnarchySubject provisioning state, CatalogItem counts, Workshop
status, summit lab-to-namespace mapping, Labagator lab and session data, and
Demolition smoke test results.

All scan results are written to `scan-history/` as timestamped JSON files and
persisted to the `scan_snapshots` database table.

### 2. Rubric Evaluation

Evidence for each namespace is evaluated against YAML rubrics in
`rubrics/platform/`. Each rubric defines entry criteria, exit criteria, failure
classes, and allowed remediations.

**Pipeline stages** (11 total):

1. `cluster-health` -- Node CPU, memory, alerts
2. `run-created` -- Run exists, demo ID valid
3. `provision-complete` -- AnarchySubject started, no errors
4. `namespace-ready` -- Namespace exists, not terminating
5. `deployment-ready` -- Deployments exist, replicas ready
6. `storage-clone-ready` -- DataVolumes succeeded, PVCs bound
7. `route-ready` -- Routes exist, TLS valid, endpoints ready
8. `vm-runtime-ready` -- VMIs running, guest agent connected
9. `smoke-test-ready` -- Smoke test pass criteria
10. `showroom-healthy` -- Showroom pod, route reachable, content loaded
11. `model-endpoint-ready` -- InferenceService ready, latency acceptable

Outcomes: `pass`, `warn`, `fail`. Failed evaluations are classified into
specific failure classes (e.g., `showroom_not_reachable`, `namespace_missing`,
`deployment_missing`) by matching conditions against evidence.

### 3. Policy Recommendations

`engine/policy.py` generates allocation recommendations based on current state.
Five recommendation types:

| Type                  | Urgency  | Trigger                                     |
|-----------------------|----------|----------------------------------------------|
| `provision_blocked_lab` | critical | Sessions > 0, zero provisioning             |
| `cleanup_stuck`       | high     | AnarchySubjects in failed state             |
| `pool_exhaustion`     | high     | Pool available <= 1 with min > 0            |
| `cluster_capacity`    | medium/high | CPU > 70% or VMs/node > 80               |
| `smoke_test_failing`  | high/medium | Demolition fail + sessions scheduled      |

Each recommendation includes targeted evidence from the specific data sources
that informed it (source_labagator, source_babylon, source_poolboy,
source_agnosticv, source_cluster_scanner, source_demolition) plus a
decision_logic string. Recommendations are augmented with rubric context and
constraint violation correlations. All output is advisory -- no writes to any
external system.

### 4. Event Processing

The event bus (`events/bus.py`) processes events through a nanoagent pipeline:

```
Event --> FilterAgent --> CorrelateAgent --> TriageAgent --> ImpactAgent --> Consumers
```

- **FilterAgent**: Drops routine passes, deduplicates same failure class within
  15-minute window, applies custom suppress rules.
- **CorrelateAgent**: Detects systemic patterns (>20% same failure class on
  cluster), cross-cluster correlation.
- **TriageAgent**: Calculates priority 0-10 based on severity scores, boosts
  for systemic issues and upcoming sessions.
- **ImpactAgent**: Estimates blast radius (failing labs / total labs), escalates
  when >10 labs or >30% failure rate.

Events are persisted to the `event_log` database table.

### 5. Action Execution (Gated)

`api/action_executor.py` enforces five independent gates before any action:

1. **Namespace allowlist** -- Target namespace must match configured prefixes
   (`STARGATE_REMEDIATION_NS`). Prevents action on system namespaces.
2. **Lab execution mode** -- Per-lab config (`recommend_only`, `low_risk_auto`,
   `full_auto`) controls whether actions execute or only recommend.
3. **Risk assessment** -- Catalog entry risk level must be within the lab's
   allowed risk threshold.
4. **Rate limiting** -- Per-lab action count must be below configured
   `max_actions_per_hour`.
5. **Confidence gate** -- If confidence < threshold (default 0.8), queue to
   `pending_actions` for human approval.

All actions are logged to `audit_log` before and after execution. Dry-run mode
(`STARGATE_DRY_RUN=true`) logs without executing. The remediation playbook
endpoint routes through these same gates via `execute_action()`.

### 6. LLM Integration

The LLM (`api/llm.py`) is called through LiteLLM for:
- Failure classification (`prompts/classify.yaml`)
- Remediation suggestions (`prompts/remediation.yaml`)
- Executive summaries (`prompts/executive-summary.yaml`)

Calls are instrumented with: token counts, latency, cost estimation, circuit
breaker (5 failures = 60s cooldown), and full metrics persisted to `llm_metrics`
table. Proposed classifications go to `proposed_classifications` for HITL review.

---

## Projects

### Platform (this repository)

```
stargate-platform/
  api/
    app.py              FastAPI application shell
    llm.py              Instrumented LLM wrapper
    action_executor.py  Gated execution: dry-run, confidence, audit
    resilience.py       Circuit breaker
    metrics.py          Prometheus metrics
    schemas.py          Pydantic request/response schemas
    routers/
      admin.py          Scheduler, scan history, LLM admin, synthetic toggle
      dashboard.py      Dashboard data aggregation, summit readiness
      health.py         /health and /metrics
      integration.py    External evidence, HITL feedback, lab status
      runs.py           Run lifecycle: create, start stage, evidence, evaluate
      _shared.py        Shared state, caches, auth, config
  engine/
    models.py           Pydantic domain models (Run, Stage, Evidence, Rubric)
    rubric_evaluator.py Deterministic rubric evaluation
    rubric_loader.py    YAML rubric parser
    schema_validator.py JSON schema validation for evidence
    policy.py           Provisioning recommendation engine
    substrate_router.py Gaudi vs Xeon6 workload routing
    feedback_loop.py    Signal-Decision-Action-Verify-Learn cycle
    action_simulator.py Simulated action state transforms
    rollback.py         Rollback capture and restore
  cli/
    scan.py             One-shot cluster scanner
    worker.py           Per-cluster evidence worker (tiered)
    scheduler.py        Multi-cluster scheduler with staggered offsets
    babylon_worker.py   Babylon control plane collector
    stargate.py         CLI entry point
    api_client.py       HTTP client for API persistence
  db/
    database.py         SQLAlchemy engine, session, init
    models.py           ORM models (17 tables)
    repository.py       Data access layer
  events/
    bus.py              Event bus with nanoagent pipeline
    nanoagents.py       Filter, Correlate, Triage, Impact agents
    models.py           Event dataclass
    consumers.py        Log consumer
  collectors/
    openshift/          Pod, node, namespace collectors
    babylon/            AnarchySubject state
    poolboy/            ResourcePool capacity
    labagator/          Lab and session data
    demolition/         Smoke test results
    showroom/           Showroom health checks
    cluster_scheduler/  Cluster scheduling data
    tekton/             Pipeline run state
  constraints/
    agnosticv_loader.py AgnosticV constraint loading
  rubrics/
    platform/           11 stage rubrics (YAML)
    build/              Build pipeline rubrics
  prompts/
    classify.yaml       LLM failure classification prompt
    remediation.yaml    LLM remediation prompt
    executive-summary.yaml  LLM executive summary prompt
  frontend/             React + Vite + PatternFly dashboard
  deploy/
    helm/stargate/      Helm chart for infra01
    openshift/          Raw OpenShift manifests
    tekton/             Tekton pipeline definitions
  scripts/
    deploy-infra01.sh   Deployment script
    db-backup.sh        Database backup (pg_dump, 7-day retention)
    db-restore.sh       Database restore
    generate-receipts.py Phase gate receipt generator
```

### Synthetic Client Emulator

Location: `stargate-synthetic-client-emulator/`

7 scenarios that generate synthetic cluster state and evidence for testing:

| Scenario            | What it simulates                               |
|---------------------|-------------------------------------------------|
| `healthy_baseline`  | All systems nominal                             |
| `gaudi_saturation`  | Gaudi accelerator utilization > 90%             |
| `node_failure`      | Failed compute nodes                            |
| `provision_blocked` | Labs with sessions but no provisioning          |
| `memory_pressure`   | High memory utilization across nodes            |
| `mixed_contention`  | Simultaneous crashloops, failures, stuck jobs   |
| `xeon_underutil`    | Xeon6 idle while Gaudi overloaded               |

Each scenario implements `generate_state()`, `generate_evidence()`,
`expected_recommendations`, and `validate_outcomes()`. The feedback loop engine
uses these to run closed-loop tests: generate before-state, evaluate rubrics,
apply simulated actions, evaluate after-state, verify resolution.

### Mock Cluster

Location: `stargate-mock-cluster/`

Simulated cluster API for Phase B gate testing. Validates that `oc apply`,
`oc scale`, and `oc delete` commands produce correct state changes. Maintains
an audit log and tracks state diffs.

---

## Infrastructure

### Deployment Target

- **Cluster**: ocpv-infra01 (Dallas 12 datacenter)
- **Namespace**: `stargate`
- **URL**: `https://stargate.apps.cluster.example.com`
- **API**: `https://stargate-api.apps.cluster.example.com`
- **Internal registry**: `image-registry.openshift-image-registry.svc:5000/stargate`

### Scanner Clusters (8)

| Cluster       | Kubeconfig file      | Role                     |
|---------------|----------------------|--------------------------|
| ocpv05        | kubeconfig-ocpv05    | Lab workloads            |
| ocpv06        | kubeconfig-cnv       | Lab workloads (CNV)      |
| ocpv07        | kubeconfig-ocpv07    | Lab workloads            |
| ocpv08        | kubeconfig-ocpv08    | Lab workloads            |
| ocpv09        | kubeconfig-ocpv09    | Lab workloads            |
| ocpv-infra01  | kubeconfig-infra01   | Infrastructure + StarGate|
| ocpv-infra02  | kubeconfig-infra02   | Infrastructure           |
| ocp-us-east-1 | kubeconfig           | Babylon control plane    |

Scanner service accounts have `cluster-reader` (read-only) access.

### Test Namespace

- **Cluster**: ocpv-infra01
- **Namespace**: `stargate-test`
- **Service Account**: `stargate-executor`
- **Role**: `stargate-executor-role` (namespace-scoped write for Phase C)

### Database

PostgreSQL 15, 20Gi PVC. 17 ORM tables:

- `runs`, `stages`, `evidence` -- Run lifecycle
- `evaluations` -- Rubric evaluation results
- `event_log` -- Persistent event history
- `proposed_classifications` -- LLM proposals awaiting review
- `audit_log` -- Action audit trail
- `pending_actions` -- Actions queued for human approval
- `scan_snapshots` -- Persisted scan data
- `constraint_violations` -- AgnosticV constraint violations
- `llm_feedback` -- Human feedback on LLM responses
- `llm_metrics` -- LLM call instrumentation
- `remediations` -- Remediation tracking
- `mv_cluster_summary` -- Materialized view: cluster health
- `mv_pipeline_stages` -- Materialized view: stage pass rates
- `mv_lab_eval_summary` -- Materialized view: lab evaluation health

Materialized views are refreshed every 60 seconds by a background thread.

### LLM

- **Model**: Granite 3.2 8B Instruct
- **Hardware**: Intel Gaudi accelerator
- **Proxy**: LiteLLM (`litellm.example.com`)
- **Circuit breaker**: 5 failures = 60s cooldown

---

## Gated Execution

StarGate uses a four-phase gate model to progressively increase trust in
automated actions:

### Phase A: Shadow Mode

- Run synthetic scenarios through the feedback loop engine.
- Evaluate rubrics against emulator-generated evidence.
- Apply simulated actions (state transforms, no real execution).
- Verify all stages pass after simulated fix.
- **Gate**: All 7 scenarios resolve after simulated action.

### Phase B: Mock Cluster

- Validate `oc apply`, `oc scale`, `oc delete` commands against the mock
  cluster API.
- Verify audit log records all commands.
- Verify state diffs are tracked.
- **Gate**: All mock cluster commands validate correctly.

### Phase C: Test Namespace

- Execute real `oc` commands against `stargate-test` namespace on ocpv-infra01.
- Use the `stargate-executor` service account with namespace-scoped write.
- Verify rollback: capture state, delete, restore.
- **Gate**: Real create/scale/delete and rollback verified.

### Phase D: Production

- Full production execution (future).
- Requires all prior gates passed.
- Currently placeholder in the receipt generator.

Phase gate results are captured as structured JSON receipts by
`scripts/generate-receipts.py` in the `receipts/` directory.

---

## Substrate Routing

`engine/substrate_router.py` decides workload placement between Intel Gaudi
accelerators and Intel Xeon6 processors based on cluster state:

| Condition                        | Routing           | Inference | Compute |
|----------------------------------|-------------------|-----------|---------|
| Normal operation                 | gaudi_preferred   | Gaudi     | Xeon6   |
| Gaudi saturated (>90%)          | xeon6_fallback    | Xeon6     | Xeon6   |
| Node failure                     | xeon6_fallback    | Xeon6     | Xeon6   |
| Workload contention (crashloops) | isolate           | Gaudi     | Xeon6   |
| Xeon6 idle, Gaudi busy          | rebalance_to_xeon6| Gaudi     | Xeon6   |
| Memory pressure (>80%)          | gaudi_preferred   | Gaudi     | Gaudi   |
| Provisioning issue               | no_change         | Default   | Xeon6   |

Routing decisions are included in feedback loop results and policy
recommendations for operator visibility.

---

## Container Images

| Image                 | Containerfile            | Contents                          |
|-----------------------|--------------------------|-----------------------------------|
| stargate-api          | Containerfile            | API server (uvicorn on :8090)     |
| stargate-combined     | Containerfile.combined   | API + scanner + frontend (single) |
| stargate-scanner      | Containerfile.scanner    | Scanner CLI + oc binary           |
| stargate-frontend     | Containerfile.frontend   | React dev server (node:22-alpine) |

The combined image is a multi-stage build: Node 22 for frontend, UBI9 Python 3.9
for the backend, with the `oc` 4.20 client baked in. Production deployment uses
this combined image.
